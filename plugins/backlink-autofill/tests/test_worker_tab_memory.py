#!/usr/bin/env python3
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


class WorkerTabMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cdp_port = _find_free_port()
        cls.user_data_dir = tempfile.mkdtemp(prefix="backlink-worker-memory-")

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
            raise RuntimeError("No Chromium/Chrome binary available for worker-tab lifecycle test")

        cls.chrome_log = tempfile.NamedTemporaryFile(mode="w+", prefix="worker-memory-chrome-", delete=False)
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

    def _page_targets(self) -> list[dict]:
        with urlopen(f"{self.cdp_url}/json/list", timeout=1) as resp:
            return [item for item in json.load(resp) if item.get("type") == "page"]

    def test_sequential_ordinary_runtimes_reuse_single_idle_worker_tab(self):
        """Ordinary AI work must reuse one idle worker tab instead of new/close churn."""
        with BrowserRuntime(
            profile_dir=Path(self.user_data_dir),
            cdp_url=self.cdp_url,
            allow_local_fallback=False,
        ) as first_runtime:
            first_target_id = first_runtime.target_id
            self.assertIsNotNone(first_target_id)
            self.assertEqual(first_runtime.page.url, "about:blank")

        after_first = self._page_targets()
        self.assertIn(
            first_target_id,
            [item.get("id") for item in after_first],
            "Ordinary worker tab was closed instead of being retained idle for reuse",
        )

        with BrowserRuntime(
            profile_dir=Path(self.user_data_dir),
            cdp_url=self.cdp_url,
            allow_local_fallback=False,
        ) as second_runtime:
            second_target_id = second_runtime.target_id
            self.assertEqual(
                first_target_id,
                second_target_id,
                "Sequential ordinary runtime created a fresh worker tab instead of reusing the idle one",
            )

        final_pages = self._page_targets()
        self.assertEqual(
            1,
            len(final_pages),
            f"Expected exactly one idle AI worker tab, found {len(final_pages)}: {final_pages}",
        )
        self.assertEqual(final_pages[0].get("url"), "about:blank")


if __name__ == "__main__":
    unittest.main()
