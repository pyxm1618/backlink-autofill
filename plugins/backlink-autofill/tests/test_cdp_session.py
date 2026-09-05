#!/usr/bin/env python3
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "scripts" / "browser_cli.py"
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from browser_runtime import BrowserRuntime, BrowserRuntimeError


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _read_cdp_version(port: int) -> dict | None:
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5) as resp:
            data = json.load(resp)
            return data if isinstance(data, dict) and data.get("Browser") else None
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return None


class CDPSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cdp_port = _find_free_port()
        cls.user_data_dir = tempfile.mkdtemp(prefix="backlink-cdp-profile-")

        chrome_binary = None
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            chrome_binary = pw.chromium.executable_path
            pw.stop()
        except Exception:
            pass

        if not chrome_binary or not Path(chrome_binary).is_file():
            candidates = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
                shutil.which("google-chrome"),
                shutil.which("chromium"),
                shutil.which("chromium-browser"),
            ]
            chrome_binary = next((c for c in candidates if c and Path(c).is_file()), None)

        cls.chrome_log = tempfile.NamedTemporaryFile(mode="w+", prefix="cdp-chrome-log-", delete=False)
        cls.chrome_process = subprocess.Popen(
            [
                chrome_binary,
                "--headless=new",
                f"--remote-debugging-port={cls.cdp_port}",
                f"--user-data-dir={cls.user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "about:blank",
            ],
            stdout=cls.chrome_log,
            stderr=subprocess.STDOUT,
        )

        deadline = time.time() + 15
        while time.time() < deadline:
            if cls.chrome_process.poll() is not None:
                break
            if _read_cdp_version(cls.cdp_port) is not None:
                break
            time.sleep(0.2)
        else:
            cls.chrome_process.terminate()
            cls.chrome_log.seek(0)
            log_output = cls.chrome_log.read()
            raise RuntimeError(f"CDP browser did not become available on port {cls.cdp_port}. Log:\n{log_output}")

        if cls.chrome_process.poll() is not None:
            cls.chrome_log.seek(0)
            log_output = cls.chrome_log.read()
            raise RuntimeError(f"CDP browser exited early with code {cls.chrome_process.returncode}. Log:\n{log_output}")

        cls.cdp_url = f"http://127.0.0.1:{cls.cdp_port}"

    @classmethod
    def tearDownClass(cls):
        if cls.chrome_process.poll() is None:
            cls.chrome_process.terminate()
            cls.chrome_process.wait(timeout=5)
        cls.chrome_log.close()
        Path(cls.chrome_log.name).unlink(missing_ok=True)
        shutil.rmtree(cls.user_data_dir, ignore_errors=True)

    def test_cdp_session_reuse_and_external_chrome_preserved(self):
        """RED 1: 两次调用复用同一 CDP endpoint，Session 跨调用保留，且 disconnect 时绝对不杀外部 Chrome"""
        with BrowserRuntime(
            profile_dir=Path(self.user_data_dir),
            cdp_url=self.cdp_url,
        ) as rt1:
            self.assertTrue(getattr(rt1, "is_external_cdp", False), "Expected is_external_cdp to be True")
            assert rt1.context is not None
            rt1.context.add_cookies([
                {"name": "test_session_token", "value": "TOKEN_ABC_123", "domain": "example.com", "path": "/"}
            ])

        # 验证外部 Chrome 依然存活，Chrome 进程绝不能被 browser.close() 杀死
        self.assertIsNone(self.chrome_process.poll(), "External Chrome process was killed by runtime teardown!")
        self.assertIsNotNone(_read_cdp_version(self.cdp_port), "CDP endpoint is not responding after Client 1 teardown")

        # Client 2: 重新连接同一个 CDP endpoint，验证 Cookie 跨调用保留在同一个 context 中
        with BrowserRuntime(
            profile_dir=Path(self.user_data_dir),
            cdp_url=self.cdp_url,
        ) as rt2:
            self.assertTrue(getattr(rt2, "is_external_cdp", False))
            assert rt2.context is not None
            cookies = rt2.context.cookies(["https://example.com/"])
            by_name = {c["name"]: c["value"] for c in cookies}
            self.assertEqual(by_name.get("test_session_token"), "TOKEN_ABC_123", "Session token was lost across calls!")

        # 验证 Client 2 退出后外部 Chrome 依然健康存活
        self.assertIsNone(self.chrome_process.poll(), "External Chrome process was killed after Client 2 teardown!")

    def test_fail_visible_refuses_silent_fallback_when_cdp_unavailable(self):
        """RED 2: 生产环境拒绝静默 fallback。当 CDP 端口不可用时，不带 allow_local_fallback 必须显式报错"""
        dead_port = _find_free_port()
        dead_url = f"http://127.0.0.1:{dead_port}"

        # 生产默认配置：当未显式开启 allow_local_fallback 时，必须显式抛出 BROWSER_HOST_UNAVAILABLE
        with self.assertRaises(BrowserRuntimeError) as ctx:
            with BrowserRuntime(
                profile_dir=Path(self.user_data_dir),
                cdp_url=dead_url,
                allow_local_fallback=False,
            ) as rt:
                rt.navigate("https://example.com")

        self.assertEqual(ctx.exception.code, "BROWSER_HOST_UNAVAILABLE")
        self.assertIn("unavailable", ctx.exception.message.lower())


if __name__ == "__main__":
    unittest.main()
