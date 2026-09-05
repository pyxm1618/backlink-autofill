#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
import threading
import time
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


class BrowserHandoffTests(unittest.TestCase):
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

    def run_cli(self, *args, expect_ok=True, timeout=40):
        proc = subprocess.run(
            [sys.executable, str(CLI), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if expect_ok and proc.returncode != 0:
            self.fail(f"CLI failed ({proc.returncode})\nstdout={proc.stdout}\nstderr={proc.stderr}")
        return proc

    def wait_for_state(self, handoff_root, handoff_id, wanted, timeout=15):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            proc = self.run_cli(
                "handoff-status",
                "--handoff-root", str(handoff_root),
                "--handoff-id", handoff_id,
                expect_ok=False,
            )
            if proc.returncode == 0:
                last = json.loads(proc.stdout)
                if last.get("state") == wanted:
                    return last
                if last.get("state") == "ERROR":
                    self.fail(f"handoff worker errored: {last}")
            time.sleep(0.2)
        self.fail(f"handoff did not reach {wanted}; last={last}")

    def test_challenge_is_detected_as_human_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            proc = self.run_cli(
                "inspect",
                "--profile-dir", str(profile),
                "--browser-channel", "chromium",
                "--url", f"{self.base_url}/challenge.html",
            )
            result = json.loads(proc.stdout)
            blocker = result["page"].get("human_blocker")
            self.assertIsNotNone(blocker)
            self.assertEqual(blocker["code"], "CAPTCHA")
            self.assertIn("human", blocker["reason"].lower())

    def test_headed_handoff_runs_detached_restores_fields_and_releases_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "profile"
            handoff_root = root / "handoffs"
            handoff_id = "quick-iching-row-2"
            replay = [
                {"type": "fill", "selector": "#name", "value": "Tachyon Wang"},
                {"type": "fill", "selector": "#website", "value": "https://quickiching.com/"},
            ]

            started = self.run_cli(
                "handoff-start",
                "--profile-dir", str(profile),
                "--browser-channel", "chromium",
                "--url", f"{self.base_url}/form.html",
                "--handoff-root", str(handoff_root),
                "--handoff-id", handoff_id,
                "--replay-actions-json", json.dumps(replay),
            )
            start_result = json.loads(started.stdout)
            self.assertEqual(start_result["ok"], True)
            self.assertEqual(start_result["state"], "STARTING")
            self.assertGreater(start_result["pid"], 0)

            ready = self.wait_for_state(handoff_root, handoff_id, "READY_FOR_HUMAN")
            self.assertEqual(ready["headed"], True)
            self.assertEqual(ready["page"]["title"], "Backlink Test Form")
            by_selector = {item["selector"]: item for item in ready["page"]["interactive"]}
            self.assertEqual(by_selector["#name"].get("value"), "Tachyon Wang")
            self.assertEqual(by_selector["#website"].get("value"), "https://quickiching.com/")

            finished = self.run_cli(
                "handoff-finish",
                "--handoff-root", str(handoff_root),
                "--handoff-id", handoff_id,
            )
            finish_request = json.loads(finished.stdout)
            self.assertEqual(finish_request["ok"], True)
            self.assertEqual(finish_request["state"], "FINISH_REQUESTED")

            final = self.wait_for_state(handoff_root, handoff_id, "FINISHED")
            self.assertEqual(final["headed"], True)
            self.assertEqual(final["page"]["title"], "Backlink Test Form")

            inspect_again = self.run_cli(
                "inspect",
                "--profile-dir", str(profile),
                "--browser-channel", "chromium",
                "--url", f"{self.base_url}/form.html",
            )
            self.assertEqual(json.loads(inspect_again.stdout)["ok"], True)

    def test_headed_handoff_can_replay_generated_site_password_without_leaking_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "profile"
            handoff_root = root / "handoffs"
            credential_root = root / "credentials"
            handoff_id = "credential-row-2"
            replay = [
                {"type": "fill", "selector": "#email", "value": "test@example.com"},
                {
                    "type": "credential_fill",
                    "selector": "#password",
                    "credential": "site_password",
                    "mode": "create_or_reuse",
                    "account": "test@example.com",
                },
                {
                    "type": "credential_fill",
                    "selector": "#confirm-password",
                    "credential": "site_password",
                    "mode": "create_or_reuse",
                    "account": "test@example.com",
                },
            ]

            started = self.run_cli(
                "handoff-start",
                "--profile-dir", str(profile),
                "--browser-channel", "chromium",
                "--url", f"{self.base_url}/form.html",
                "--credential-root", str(credential_root),
                "--handoff-root", str(handoff_root),
                "--handoff-id", handoff_id,
                "--replay-actions-json", json.dumps(replay),
            )
            self.assertEqual(json.loads(started.stdout)["state"], "STARTING")

            ready = self.wait_for_state(handoff_root, handoff_id, "READY_FOR_HUMAN")
            credential_evidence = [x for x in ready["replay_evidence"] if x["type"] == "credential_fill"]
            self.assertEqual(len(credential_evidence), 2)
            self.assertTrue(all(x["readback"] == {"credential": "site_password", "verified": True} for x in credential_evidence))

            files = list(credential_root.glob("*.json"))
            self.assertEqual(len(files), 1)
            password = json.loads(files[0].read_text())["password"]
            self.assertNotIn(password, started.stdout)
            self.assertNotIn(password, json.dumps(ready))

            self.run_cli(
                "handoff-finish",
                "--handoff-root", str(handoff_root),
                "--handoff-id", handoff_id,
            )
            self.wait_for_state(handoff_root, handoff_id, "FINISHED")


if __name__ == "__main__":
    unittest.main()
