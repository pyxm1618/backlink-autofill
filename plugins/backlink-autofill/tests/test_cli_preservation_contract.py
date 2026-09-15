#!/usr/bin/env python3
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

import browser_cli


class _FakeRuntime:
    last_kwargs = None

    def __init__(self, *args, **kwargs):
        type(self).last_kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, url, actions):
        return {"ok": True, "url": url, "actions": actions}


class CliPreservationContractTests(unittest.TestCase):
    def test_execute_preserves_human_blocker_without_optional_flag(self):
        argv = [
            "browser_cli.py",
            "execute",
            "--profile-dir", "/tmp/profile",
            "--url", "https://example.com/submit",
            "--actions-json", "[]",
        ]
        stdout = io.StringIO()
        with patch.object(sys, "argv", argv), patch.object(browser_cli, "BrowserRuntime", _FakeRuntime), patch("sys.stdout", stdout):
            rc = browser_cli.main()
        self.assertEqual(rc, 0)
        self.assertIs(_FakeRuntime.last_kwargs["keep_on_human_blocker"], True)
        self.assertEqual(json.loads(stdout.getvalue())["ok"], True)

    def test_keep_tab_option_is_forwarded_to_runtime(self):
        argv = [
            "browser_cli.py",
            "execute",
            "--profile-dir", "/tmp/profile",
            "--url", "https://example.com/submit",
            "--actions-json", "[]",
            "--keep-tab",
        ]
        stdout = io.StringIO()
        with patch.object(sys, "argv", argv), patch.object(browser_cli, "BrowserRuntime", _FakeRuntime), patch("sys.stdout", stdout):
            rc = browser_cli.main()
        self.assertEqual(rc, 0)
        self.assertIs(_FakeRuntime.last_kwargs["keep_tab"], True)


if __name__ == "__main__":
    unittest.main()
