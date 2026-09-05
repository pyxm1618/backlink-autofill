#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CLI = PLUGIN_ROOT / "scripts" / "browser_cli.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class BrowserRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = partial(QuietHandler, directory=str(FIXTURES))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def run_cli(self, *args, expect_ok=True):
        proc = subprocess.run(
            [sys.executable, str(CLI), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=40,
        )
        if expect_ok and proc.returncode != 0:
            self.fail(f"CLI failed ({proc.returncode})\nstdout={proc.stdout}\nstderr={proc.stderr}")
        return proc

    def test_inspect_returns_compact_interactive_snapshot_and_redacts_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            proc = self.run_cli(
                "inspect",
                "--profile-dir", str(profile),
                "--browser-channel", "chromium",
                "--url", f"{self.base_url}/form.html",
            )
            result = json.loads(proc.stdout)
            self.assertEqual(result["ok"], True)
            self.assertEqual(result["page"]["title"], "Backlink Test Form")
            by_selector = {item["selector"]: item for item in result["page"]["interactive"]}
            self.assertIn("#name", by_selector)
            self.assertIn("#email", by_selector)
            self.assertIn("#logo", by_selector)
            self.assertIn("#submit", by_selector)
            self.assertEqual(by_selector["#password"]["sensitive"], True)
            self.assertNotIn("value", by_selector["#password"])
            self.assertLessEqual(len(result["page"]["body_excerpt"]), 4000)

    def test_execute_fills_uploads_submits_and_persists_session_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "profile"
            asset_root = root / "project-assets"
            asset_root.mkdir()
            logo = asset_root / "logo.png"
            logo.write_bytes(b"test-image-bytes")

            actions = [
                {"type": "fill", "selector": "#name", "value": "Tachyon Wang"},
                {"type": "fill", "selector": "#email", "value": "pyxm1618@gmail.com"},
                {"type": "fill", "selector": "#website", "value": "https://quickiching.com/"},
                {"type": "fill", "selector": "#description", "value": "Free online I Ching casting and hexagram reading tool."},
                {"type": "select", "selector": "#category", "value": "Reference"},
                {"type": "check", "selector": "#agree"},
                {"type": "upload", "selector": "#logo", "path": str(logo)},
                {"type": "submit", "selector": "#submit"},
            ]

            proc = self.run_cli(
                "execute",
                "--profile-dir", str(profile),
                "--browser-channel", "chromium",
                "--allowed-upload-root", str(asset_root),
                "--url", f"{self.base_url}/form.html",
                "--actions-json", json.dumps(actions),
            )
            result = json.loads(proc.stdout)
            self.assertEqual(result["ok"], True)
            self.assertEqual(len(result["actions"]), len(actions))
            self.assertTrue(all(item["status"] == "verified" for item in result["actions"]))
            self.assertIn("Submission received", result["page"]["body_excerpt"])
            self.assertTrue(result["page"]["url"].endswith("/success"))
            upload_evidence = next(item for item in result["actions"] if item["type"] == "upload")
            self.assertEqual(upload_evidence["readback"], "logo.png")

            inspect_again = self.run_cli(
                "inspect",
                "--profile-dir", str(profile),
                "--browser-channel", "chromium",
                "--url", f"{self.base_url}/form.html",
            )
            persisted = json.loads(inspect_again.stdout)
            self.assertIn("Previous session present", persisted["page"]["body_excerpt"])

    def test_password_fill_is_refused_without_echoing_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            secret = "super-secret-value-123"
            actions = [{"type": "fill", "selector": "#password", "value": secret}]
            proc = self.run_cli(
                "execute",
                "--profile-dir", str(profile),
                "--browser-channel", "chromium",
                "--url", f"{self.base_url}/form.html",
                "--actions-json", json.dumps(actions),
                expect_ok=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertNotIn(secret, proc.stdout)
            self.assertNotIn(secret, proc.stderr)
            error = json.loads(proc.stderr)
            self.assertEqual(error["ok"], False)
            self.assertEqual(error["error_code"], "SENSITIVE_FIELD")

    def test_upload_must_stay_inside_selected_project_asset_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "profile"
            asset_root = root / "project-assets"
            asset_root.mkdir()
            outside = root / "other-project-logo.png"
            outside.write_bytes(b"other-project")
            actions = [{"type": "upload", "selector": "#logo", "path": str(outside)}]
            proc = self.run_cli(
                "execute",
                "--profile-dir", str(profile),
                "--browser-channel", "chromium",
                "--allowed-upload-root", str(asset_root),
                "--url", f"{self.base_url}/form.html",
                "--actions-json", json.dumps(actions),
                expect_ok=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            error = json.loads(proc.stderr)
            self.assertEqual(error["error_code"], "UPLOAD_OUTSIDE_PROJECT")


if __name__ == "__main__":
    unittest.main()
