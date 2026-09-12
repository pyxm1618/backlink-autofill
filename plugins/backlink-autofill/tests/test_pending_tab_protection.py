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
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import urlopen

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "scripts" / "browser_cli.py"
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from browser_runtime import BrowserRuntime
from execution_state import find_human_pending, save_human_pending


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


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class PendingTabProtectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures_dir = Path(__file__).resolve().parent / "fixtures"
        handler = partial(QuietHandler, directory=str(fixtures_dir))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

        cls.cdp_port = _find_free_port()
        cls.user_data_dir = tempfile.mkdtemp(prefix="backlink-pending-protection-")

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

        if not chrome_binary:
            raise RuntimeError("No Chromium/Chrome binary available for pending-tab lifecycle test")

        cls.chrome_log = tempfile.NamedTemporaryFile(mode="w+", prefix="pending-protection-chrome-", delete=False)
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
            raise RuntimeError("CDP browser did not become available")

        if cls.chrome_process.poll() is not None:
            cls.chrome_log.seek(0)
            raise RuntimeError(f"CDP browser exited early: {cls.chrome_log.read()}")

        cls.cdp_url = f"http://127.0.0.1:{cls.cdp_port}"

    @classmethod
    def tearDownClass(cls):
        if cls.chrome_process.poll() is None:
            cls.chrome_process.terminate()
            cls.chrome_process.wait(timeout=5)
        cls.chrome_log.close()
        Path(cls.chrome_log.name).unlink(missing_ok=True)
        shutil.rmtree(cls.user_data_dir, ignore_errors=True)
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)

    def _page_targets(self) -> list[dict]:
        with urlopen(f"{self.cdp_url}/json/list", timeout=1) as resp:
            return [item for item in json.load(resp) if item.get("type") == "page"]

    def _close_target(self, target_id: str) -> None:
        try:
            with urlopen(f"{self.cdp_url}/json/close/{target_id}", timeout=1):
                pass
        except Exception:
            pass

    def test_blank_pending_target_is_never_reused_or_compacted_as_worker(self):
        """A durable HUMAN_PENDING target stays protected even if the human navigates it to about:blank."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            project_id = "pending-blank-project"
            backlink_id = "pending-blank-site"

            with patch.dict(os.environ, {"BACKLINK_RUNTIME_ROOT": str(runtime_root)}):
                with BrowserRuntime(
                    profile_dir=Path(self.user_data_dir),
                    cdp_url=self.cdp_url,
                    keep_on_human_blocker=True,
                ) as pending_rt:
                    result = pending_rt.navigate(f"{self.base_url}/challenge.html")
                    self.assertIsNotNone(result.get("human_blocker"))
                    pending_target = pending_rt.target_id
                    self.assertIsNotNone(pending_target)
                    save_human_pending(
                        runtime_root=runtime_root,
                        project_id=project_id,
                        backlink_id=backlink_id,
                        domain="challenge.test",
                        blocker_type=result["human_blocker"]["code"],
                        current_url=f"{self.base_url}/challenge.html",
                        target_id=pending_target,
                    )
                    assert pending_rt.page is not None
                    # Simulate the human moving the still-unresolved pending page to blank.
                    pending_rt.page.goto("about:blank", wait_until="commit")

                with BrowserRuntime(
                    profile_dir=Path(self.user_data_dir),
                    cdp_url=self.cdp_url,
                ) as worker_rt:
                    worker_target = worker_rt.target_id
                    self.assertNotEqual(
                        pending_target,
                        worker_target,
                        "An unresolved HUMAN_PENDING target was reused as the AI worker merely because its URL was blank",
                    )

                targets = self._page_targets()
                self.assertIn(
                    pending_target,
                    [item.get("id") for item in targets],
                    "An unresolved HUMAN_PENDING blank target was compacted/closed as an idle worker",
                )
                self.assertIsNotNone(find_human_pending(runtime_root, project_id, backlink_id))

                self._close_target(pending_target)

    def test_resumed_pending_target_stays_open_until_explicit_resolve(self):
        """Clearing the visible blocker is not terminal business completion; only human-pending-resolve may close the tab."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            project_id = "pending-resume-project"
            backlink_id = "pending-resume-site"

            with patch.dict(os.environ, {"BACKLINK_RUNTIME_ROOT": str(runtime_root)}):
                with BrowserRuntime(
                    profile_dir=Path(self.user_data_dir),
                    cdp_url=self.cdp_url,
                    keep_on_human_blocker=True,
                ) as blocked_rt:
                    result = blocked_rt.navigate(f"{self.base_url}/challenge.html")
                    self.assertIsNotNone(result.get("human_blocker"))
                    pending_target = blocked_rt.target_id
                    self.assertIsNotNone(pending_target)
                    save_human_pending(
                        runtime_root=runtime_root,
                        project_id=project_id,
                        backlink_id=backlink_id,
                        domain="challenge.test",
                        blocker_type=result["human_blocker"]["code"],
                        current_url=f"{self.base_url}/challenge.html",
                        target_id=pending_target,
                    )

                # Simulate the human solving the CAPTCHA and landing on a normal, still-unsubmitted form.
                # A single inspect sees no blocker, but the durable pending record is intentionally unresolved.
                with BrowserRuntime(
                    profile_dir=Path(self.user_data_dir),
                    cdp_url=self.cdp_url,
                    resume_target_id=pending_target,
                ) as resumed_rt:
                    inspected = resumed_rt.inspect(f"{self.base_url}/form.html")
                    self.assertIsNone(inspected.get("human_blocker"))

                targets_after_inspect = self._page_targets()
                self.assertIn(
                    pending_target,
                    [item.get("id") for item in targets_after_inspect],
                    "A resumed HUMAN_PENDING target was closed before explicit terminal resolution",
                )
                self.assertIsNotNone(
                    find_human_pending(runtime_root, project_id, backlink_id),
                    "Inspecting a cleared blocker must not implicitly resolve the durable pending record",
                )

                cmd = [
                    sys.executable,
                    str(CLI),
                    "human-pending-resolve",
                    "--runtime-root", str(runtime_root),
                    "--project-id", project_id,
                    "--backlink-id", backlink_id,
                    "--terminal-status", "已提交",
                    "--cdp-url", self.cdp_url,
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                resolve_result = json.loads(proc.stdout)
                self.assertTrue(resolve_result["resolved"])
                self.assertEqual(resolve_result.get("tab_cleanup"), "CLOSED")

                targets_after_resolve = self._page_targets()
                self.assertNotIn(pending_target, [item.get("id") for item in targets_after_resolve])
                self.assertIsNone(find_human_pending(runtime_root, project_id, backlink_id))


if __name__ == "__main__":
    unittest.main()
