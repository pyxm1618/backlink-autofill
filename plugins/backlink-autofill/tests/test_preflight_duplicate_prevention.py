#!/usr/bin/env python3
"""Tests for universal Existing Account + Existing Submission Preflight and Resource Lifecycle Regression."""

import json
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
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from execution_state import (
    normalize_canonical_url,
    detect_existing_project_submission,
    classify_project_status,
    ProductionSheetGate,
    EvidenceContractError,
)
from browser_runtime import BrowserRuntime


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


class PreflightAndLifecycleTests(unittest.TestCase):
    def test_normalize_canonical_url(self):
        """1. Canonical URL 归一化：忽略协议、www、末尾斜杠、大小写"""
        cases = [
            ("https://quickiching.com/", "quickiching.com"),
            ("http://www.quickiching.com", "quickiching.com"),
            ("https://QuickIChing.COM///", "quickiching.com"),
            ("http://quickiching.com/app/", "quickiching.com/app"),
            ("https://www.quickiching.com/app", "quickiching.com/app"),
            ("", ""),
            (None, ""),
        ]
        for raw, expected in cases:
            self.assertEqual(normalize_canonical_url(raw), expected)

    def test_preflight_existing_account_and_existing_project_found(self):
        """2. Existing account + existing project -> FOUND -> 禁止 Final Submit，提取排期事实"""
        dashboard_items = [
            {
                "title": "Other Tool",
                "url": "https://othertool.com",
                "status": "Active",
            },
            {
                "title": "Quick I Ching",
                "url": "https://www.quickiching.com/",
                "status": "Scheduled for launch",
                "scheduled_date": "2026-09-21",
            },
        ]
        res = detect_existing_project_submission(
            content=dashboard_items,
            project_name="Quick I Ching",
            canonical_url="https://quickiching.com",
        )
        self.assertEqual(res["verdict"], "FOUND")
        self.assertEqual(res["scheduled_date"], "2026-09-21")
        self.assertIn("Scheduled", res["status_hint"])

        # 结合 Evidence Contract 分类状态：必须识别为 已排期
        evidence = {
            "existing_submission_found": True,
            "scheduled_date": res["scheduled_date"],
            "platform_status_text": res["status_hint"],
        }
        status = classify_project_status(evidence)
        self.assertEqual(status, "已排期")

        # 尝试通过 ProductionSheetGate：排期状态安全写入，若试图标记审核中则自动规范化为已排期
        mutation = ProductionSheetGate.validate_project_mutation(
            evidence=evidence,
            proposed={"状态": "审核中", "结果链接": ""},
            strict_schedule=False,
        )
        self.assertEqual(mutation["状态"], "已排期")

    def test_preflight_existing_account_no_project_not_found(self):
        """3. Existing account + no project -> NOT_FOUND -> 允许正常创建与提交"""
        dashboard_items = [
            {
                "title": "Unrelated Project A",
                "url": "https://unrelated-a.com",
                "status": "Live",
            },
            {
                "title": "Unrelated Project B",
                "url": "https://unrelated-b.com",
                "status": "Pending",
            },
        ]
        res = detect_existing_project_submission(
            content=dashboard_items,
            project_name="Quick I Ching",
            canonical_url="https://quickiching.com",
        )
        self.assertEqual(res["verdict"], "NOT_FOUND")
        self.assertIsNone(res["matched_identity"])

    def test_preflight_empty_listings_dashboard_not_found(self):
        """4. 确认在用户 listings 页面但列表为空 -> NOT_FOUND -> 允许创建提交"""
        dom_text = """
        <div class="dashboard-container">
            <h2>Your Listings</h2>
            <p>You haven't submitted any products yet.</p>
            <a href="/submit">Submit a new tool</a>
        </div>
        """
        res = detect_existing_project_submission(
            content=dom_text,
            project_name="Quick I Ching",
            canonical_url="https://quickiching.com",
        )
        self.assertEqual(res["verdict"], "NOT_FOUND")

    def test_preflight_ambiguous_page_returns_unknown_and_rejects_guessing(self):
        """5. 结构不确定 / 非 listings 页面 / target lost -> UNKNOWN -> 绝不盲目提交"""
        ambiguous_page = """
        <html><body>
            <h1>Welcome to Founder Directory</h1>
            <p>Explore top AI tools and start submitting today.</p>
        </body></html>
        """
        res = detect_existing_project_submission(
            content=ambiguous_page,
            project_name="Quick I Ching",
            canonical_url="https://quickiching.com",
        )
        self.assertEqual(res["verdict"], "UNKNOWN")

    def test_preflight_dom_text_avoids_false_positives_from_nav_or_footer(self):
        """6. 避免全局字符串查找误判：仅导航栏或搜索历史出现项目名，无 submission context 时不判 FOUND"""
        page_with_search_history = """
        <header>
            <input value="Quick I Ching" placeholder="Search tools..." />
            <nav>Top Tools</nav>
        </header>

        <div class="dashboard-container">
            <h2>Your Listings</h2>
            <div class="card">
                <h3>My Tarot App</h3>
                <p>Status: Published</p>
            </div>
        </div>
        """
        res = detect_existing_project_submission(
            content=page_with_search_history,
            project_name="Quick I Ching",
            canonical_url="https://quickiching.com",
        )
        self.assertNotEqual(res["verdict"], "FOUND")


class ResourceLifecycleScaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cdp_port = _find_free_port()
        cls.user_data_dir = tempfile.mkdtemp(prefix="backlink-lifecycle-profile-")

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

        cls.cdp_url = f"http://127.0.0.1:{cls.cdp_port}"

    @classmethod
    def tearDownClass(cls):
        if cls.chrome_process.poll() is None:
            cls.chrome_process.terminate()
            cls.chrome_process.wait(timeout=5)
        cls.chrome_log.close()
        Path(cls.chrome_log.name).unlink(missing_ok=True)
        shutil.rmtree(cls.user_data_dir, ignore_errors=True)

    def test_lifecycle_scale_completed_tasks_do_not_linearly_accumulate_pages(self):
        """资源规模验收：模拟连续处理 10 个普通 terminal tasks，页面数在退出后回落至基线；1 个挂起任务保留。
        确认：completed_tasks 增长 != remaining task pages 线性增长。
        """
        # 1. 记录初始页面数量（基线）
        with urlopen(f"{self.cdp_url}/json/list") as resp:
            baseline_pages = len(json.load(resp))

        # 2. 连续运行 10 个普通任务（模拟访问 example.com 并达到终端状态关闭）
        for i in range(10):
            with BrowserRuntime(
                profile_dir=Path(self.user_data_dir),
                cdp_url=self.cdp_url,
                allow_local_fallback=False,
            ) as rt:
                rt.navigate("https://example.com")
                # 普通任务结束，__exit__ 会执行 page.close()

        # 3. 检查处理完 10 个任务后的外部 Chrome 页面数：必须严格等于基线，未发生线性累加！
        with urlopen(f"{self.cdp_url}/json/list") as resp:
            after_10_pages = len(json.load(resp))
        self.assertEqual(
            after_10_pages,
            baseline_pages,
            f"Expected page count to return to baseline ({baseline_pages}), but found {after_10_pages}!",
        )

        # 4. 模拟 1 个带有 human blocker 的任务（开启 keep_on_human_blocker）
        with BrowserRuntime(
            profile_dir=Path(self.user_data_dir),
            cdp_url=self.cdp_url,
            keep_on_human_blocker=True,
            allow_local_fallback=False,
        ) as rt_block:
            rt_block._stopped_for_human = True
            blocked_tid = rt_block.target_id

        # 5. 再次检查：此时应仅增加 1 个保留 Tab（基线 + 1），而不是 10 + 1 个！
        with urlopen(f"{self.cdp_url}/json/list") as resp:
            current_pages = json.load(resp)
            self.assertEqual(
                len(current_pages),
                baseline_pages + 1,
                "Expected exactly baseline + 1 retained human-pending tab!",
            )

        # 清理该 blocked tab
        if blocked_tid:
            with urlopen(f"{self.cdp_url}/json/close/{blocked_tid}"):
                pass


if __name__ == "__main__":
    unittest.main()
