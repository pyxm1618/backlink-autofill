#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "execution_state.py"
spec = importlib.util.spec_from_file_location("execution_state", MODULE_PATH)
execution_state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(execution_state)


class ExecutionStateTests(unittest.TestCase):
    def test_sheet_status_mapping_uses_canonical_chinese_values(self):
        cases = {
            "待提交": "PENDING",
            "处理中": "IN_PROGRESS",
            "已提交": "SUBMITTED",
            "审核中": "UNDER_REVIEW",
            "已排期": "SCHEDULED",
            "已上线": "LIVE",
            "需人工": "NEEDS_HUMAN",
            "失败": "FAILED",
            "不适用": "NOT_APPLICABLE",
        }
        for sheet_value, internal in cases.items():
            self.assertEqual(execution_state.sheet_status_to_internal(sheet_value), internal)
            self.assertEqual(execution_state.internal_to_sheet_status(internal), sheet_value)

        self.assertIsNone(execution_state.sheet_status_to_internal(""))
        self.assertIsNone(execution_state.sheet_status_to_internal("未知状态"))
        with self.assertRaises(ValueError):
            execution_state.internal_to_sheet_status("UNKNOWN")

    def test_checkpoint_is_project_isolated_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = {
                "schema_version": 1,
                "project_id": "quick-iching",
                "row_number": 17,
                "backlink_id": "bl-123",
                "domain": "example.com",
                "url": "https://example.com/submit",
                "state": "IN_PROGRESS",
                "replay_actions": [],
                "evidence": {"title": "Submit"},
            }
            path = execution_state.save_checkpoint(root, checkpoint)
            self.assertEqual(path, root / "runtime" / "quick-iching" / "row-17.json")
            self.assertTrue(path.is_file())
            self.assertEqual(
                execution_state.load_checkpoint(root, "quick-iching", 17),
                checkpoint,
            )
            self.assertIsNone(execution_state.load_checkpoint(root, "project-b", 17))

            execution_state.delete_checkpoint(root, "quick-iching", 17)
            self.assertFalse(path.exists())

    def test_checkpoint_rejects_cross_project_or_invalid_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                execution_state.save_checkpoint(root, {
                    "schema_version": 1,
                    "project_id": "../project-b",
                    "row_number": 3,
                    "backlink_id": "bl-1",
                    "state": "IN_PROGRESS",
                })
            with self.assertRaises(ValueError):
                execution_state.save_checkpoint(root, {
                    "schema_version": 1,
                    "project_id": "quick-iching",
                    "row_number": 0,
                    "backlink_id": "bl-1",
                    "state": "IN_PROGRESS",
                })

    def test_recipe_round_trips_by_canonical_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipe = {
                "schema_version": 1,
                "domain": "Example.COM",
                "entry_url": "https://example.com/submit",
                "selectors": {"website": "#url"},
                "success_indicators": ["Submission received"],
            }
            path = execution_state.save_recipe(root, "https://WWW.Example.COM/path", recipe)
            self.assertEqual(path, root / "recipes" / "example.com.json")
            loaded = execution_state.load_recipe(root, "example.com")
            self.assertEqual(loaded["entry_url"], recipe["entry_url"])
            self.assertEqual(loaded["selectors"], recipe["selectors"])
            self.assertEqual(loaded["domain"], "example.com")

    def test_recipe_rejects_sensitive_keys_recursively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad_payloads = [
                {"password": "x"},
                {"auth": {"passwd": "x"}},
                {"nested": [{"secret": "x"}]},
                {"headers": {"access_token": "x"}},
                {"headers": {"api_key": "x"}},
            ]
            for payload in bad_payloads:
                with self.subTest(payload=payload):
                    with self.assertRaises(ValueError):
                        execution_state.save_recipe(root, "example.com", payload)

    def test_atomic_json_output_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = {
                "schema_version": 1,
                "project_id": "quick-iching",
                "row_number": 4,
                "backlink_id": "bl-4",
                "state": "NEEDS_HUMAN",
            }
            path = execution_state.save_checkpoint(root, checkpoint)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), checkpoint)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
