#!/usr/bin/env python3
import json
import os
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


class ResultLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["BACKLINK_ALLOW_LOCAL_FALLBACK"] = "1"
        handler = partial(QuietHandler, directory=str(FIXTURES))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("BACKLINK_ALLOW_LOCAL_FALLBACK", None)
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def run_cli(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    *args,
                    "--profile-dir",
                    str(Path(tmp) / "profile"),
                    "--browser-channel",
                    "chromium",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=40,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_submit_waits_for_delayed_result_but_keeps_business_result_unconfirmed(self):
        result = self.run_cli(
            "execute",
            "--url",
            f"{self.base_url}/delayed-submit.html",
            "--actions-json",
            json.dumps([{"type": "submit", "selector": "#submit"}]),
        )
        self.assertIn("Submission received after delay", result["page"]["body_excerpt"])
        self.assertTrue(result["requires_business_confirmation"])
        self.assertEqual(result["business_result"], "unconfirmed")
        self.assertGreaterEqual(result["post_action_observation"]["waited_ms"], 900)

    def test_recaptcha_incorrect_is_detected_as_human_blocker(self):
        result = self.run_cli(
            "inspect",
            "--url",
            f"{self.base_url}/recaptcha-incorrect.html",
        )
        self.assertEqual(result["page"]["human_blocker"]["code"], "CAPTCHA")

    def test_ordinary_registration_validation_is_not_business_success_or_permanent_failure(self):
        result = self.run_cli(
            "execute",
            "--url",
            f"{self.base_url}/registration-validation.html",
            "--actions-json",
            json.dumps([{"type": "submit", "selector": "#register"}]),
        )
        self.assertIn("Date of birth is required", result["page"]["body_excerpt"])
        self.assertIsNone(result["page"]["human_blocker"])
        self.assertTrue(result["requires_business_confirmation"])
        self.assertEqual(result["business_result"], "unconfirmed")


if __name__ == "__main__":
    unittest.main()
