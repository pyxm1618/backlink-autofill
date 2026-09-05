#!/usr/bin/env python3
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "scripts" / "browser_cli.py"
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from browser_runtime import BrowserRuntime, BrowserRuntimeError
from execution_state import (
    clear_human_pending,
    find_human_pending,
    list_human_pending,
    load_human_pending,
    save_human_pending,
)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class TabIsolationAndResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures_dir = Path(__file__).resolve().parent / "fixtures"
        handler = partial(QuietHandler, directory=str(fixtures_dir))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

        # 启动受控本地 CDP Chrome 实例
        cls.cdp_port = _find_free_port()
        cls.user_data_dir = tempfile.mkdtemp(prefix="backlink-tab-profile-")

        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
        ]
        chrome_binary = next((c for c in candidates if c and Path(c).is_file()), None)
        if not chrome_binary:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            chrome_binary = pw.chromium.executable_path
            pw.stop()

        cls.chrome_process = subprocess.Popen(
            [
                chrome_binary,
                "--headless=new",
                f"--remote-debugging-port={cls.cdp_port}",
                f"--user-data-dir={cls.user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{cls.cdp_port}/json/version", timeout=0.5) as resp:
                    if json.load(resp).get("Browser"):
                        break
            except Exception:
                time.sleep(0.2)
        else:
            cls.chrome_process.terminate()
            raise RuntimeError(f"CDP browser did not become available on port {cls.cdp_port}")

        cls.cdp_url = f"http://127.0.0.1:{cls.cdp_port}"

    @classmethod
    def tearDownClass(cls):
        if cls.chrome_process.poll() is None:
            cls.chrome_process.terminate()
            cls.chrome_process.wait(timeout=5)
        shutil.rmtree(cls.user_data_dir, ignore_errors=True)
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)

    def test_tab_isolation_and_human_pending_persistence(self):
        """RED 5: Task A 遇阻挂起并获得 target_id，Tab A 保持存活；Task B 在新 Tab 执行且不干扰 Tab A"""
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            project_id = "test-project"

            # Task A: 访问 challenge.html，触发 CAPTCHA blocker
            with BrowserRuntime(
                profile_dir=Path(self.user_data_dir),
                cdp_url=self.cdp_url,
                keep_on_human_blocker=True,
            ) as rt_a:
                res_a = rt_a.navigate(f"{self.base_url}/challenge.html")
                self.assertIsNotNone(res_a.get("human_blocker"))
                target_id_a = rt_a.target_id
                self.assertIsNotNone(target_id_a, "target_id must be exposed in CDP mode")

                # 持久化保存 human pending 记录
                save_human_pending(
                    runtime_root=runtime_root,
                    project_id=project_id,
                    backlink_id="site-a",
                    domain="challenge.test",
                    blocker_type=res_a["human_blocker"]["code"],
                    current_url=f"{self.base_url}/challenge.html",
                    target_id=target_id_a,
                )

            # 验证 Tab A 在断开后依然没有被关闭，Chrome 中仍能查到该 targetId
            with urlopen(f"{self.cdp_url}/json/list") as resp:
                targets = json.load(resp)
                target_ids = [t.get("id") for t in targets]
                self.assertIn(target_id_a, target_ids, "Tab A was closed unexpectedly!")

            # Task B: 访问 form.html，进行普通交互
            with BrowserRuntime(
                profile_dir=Path(self.user_data_dir),
                cdp_url=self.cdp_url,
            ) as rt_b:
                target_id_b = rt_b.target_id
                self.assertNotEqual(target_id_a, target_id_b, "Task B must receive an isolated tab!")
                res_b = rt_b.navigate(f"{self.base_url}/form.html")
                self.assertIsNone(res_b.get("human_blocker"))

            # 验证 Task B 完成后，Tab A 依然完好无损，且 URL 仍为 challenge.html
            with urlopen(f"{self.cdp_url}/json/list") as resp:
                targets = json.load(resp)
                tab_a = next((t for t in targets if t.get("id") == target_id_a), None)
                self.assertIsNotNone(tab_a, "Tab A disappeared after Task B!")
                self.assertIn("challenge.html", tab_a.get("url", ""))

    def test_resume_protocol_attaches_target_and_prevents_duplicate_submit(self):
        """RED 6: 跨客户端凭 target_id 找回挂起 Tab，确认 blocker 清除后继续执行；原 target 丢失时严禁重试"""
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            project_id = "test-project"

            # 1. 初始执行：打开页面并在挂起状态断开
            with BrowserRuntime(
                profile_dir=Path(self.user_data_dir),
                cdp_url=self.cdp_url,
                keep_tab=True,
            ) as rt1:
                rt1.navigate(f"{self.base_url}/form.html")
                target_id = rt1.target_id
                save_human_pending(
                    runtime_root=runtime_root,
                    project_id=project_id,
                    backlink_id="site-resume",
                    domain="example.com",
                    blocker_type="EMAIL_OTP",
                    current_url=f"{self.base_url}/form.html",
                    target_id=target_id,
                )

            # 2. 模拟新会话（Client 2）：凭 target_id 重新 attach 到原 Tab
            with BrowserRuntime(
                profile_dir=Path(self.user_data_dir),
                cdp_url=self.cdp_url,
                resume_target_id=target_id,
            ) as rt2:
                self.assertEqual(rt2.target_id, target_id, "Did not attach to the requested target tab!")
                # 在原 Tab 上继续执行动作（填入姓名并提交）
                res2 = rt2.execute(
                    f"{self.base_url}/form.html",
                    [
                        {"type": "fill", "selector": "#name", "value": "Resumed User"},
                        {"type": "fill", "selector": "#email", "value": "resumed@example.com"},
                        {"type": "fill", "selector": "#website", "value": "https://resumed.com/"},
                        {"type": "submit", "selector": "#submit"},
                    ],
                )
                self.assertEqual(res2["ok"], True)
                self.assertIn("Submission received", res2["page"]["body_excerpt"])

            # 3. 达到终态后清理 pending 记录
            clear_human_pending(runtime_root, project_id, "site-resume")
            self.assertIsNone(find_human_pending(runtime_root, project_id, "site-resume"))

            # 4. 若 target_id 丢失/不存在，严禁自动重复注册或提交，必须抛出 TARGET_TAB_LOST
            with self.assertRaises(BrowserRuntimeError) as ctx:
                with BrowserRuntime(
                    profile_dir=Path(self.user_data_dir),
                    cdp_url=self.cdp_url,
                    resume_target_id="NON_EXISTENT_TARGET_ID",
                ) as rt3:
                    rt3.navigate(f"{self.base_url}/form.html")

            self.assertEqual(ctx.exception.code, "TARGET_TAB_LOST")


if __name__ == "__main__":
    unittest.main()
