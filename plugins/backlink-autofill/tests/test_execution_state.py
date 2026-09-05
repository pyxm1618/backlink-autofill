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

    def test_checkpoint_rejects_cross_project_invalid_identity_or_sensitive_data(self):
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
            with self.assertRaises(ValueError):
                execution_state.save_checkpoint(root, {
                    "schema_version": 1,
                    "project_id": "quick-iching",
                    "row_number": 3,
                    "backlink_id": "bl-1",
                    "state": "IN_PROGRESS",
                    "replay_actions": [{"field": "password", "value": "do-not-store"}],
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

    def test_human_pending_strict_project_isolation_and_no_overwrite(self):
        """RED: 两个不同项目对同一域名平台同时存在 HUMAN_PENDING，互不覆盖且严格隔离"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 项目 A (quick-iching) 遇阻
            path_a = execution_state.save_human_pending(
                runtime_root=root,
                project_id="quick-iching",
                backlink_id="foundrlist",
                domain="foundrlist.com",
                blocker_type="EMAIL_OTP",
                current_url="https://foundrlist.com/register/verify",
                target_id="target-quick-iching-1",
            )
            # 项目 B (project-b) 对同一域名也遇阻
            path_b = execution_state.save_human_pending(
                runtime_root=root,
                project_id="project-b",
                backlink_id="foundrlist",
                domain="foundrlist.com",
                blocker_type="CAPTCHA",
                current_url="https://foundrlist.com/register/captcha",
                target_id="target-project-b-2",
            )

            # 两个文件路径完全独立
            self.assertNotEqual(str(path_a), str(path_b))
            self.assertTrue(path_a.exists())
            self.assertTrue(path_b.exists())

            # 数据互不覆盖
            item_a = execution_state.load_human_pending(root, project_id="quick-iching", backlink_id="foundrlist")
            item_b = execution_state.load_human_pending(root, project_id="project-b", backlink_id="foundrlist")
            self.assertEqual(item_a["target_id"], "target-quick-iching-1")
            self.assertEqual(item_b["target_id"], "target-project-b-2")

            # list 必须要求 project_id 上下文，缺省必须抛出 ValueError
            with self.assertRaises(ValueError):
                execution_state.list_human_pending(root, project_id=None)

            list_a = execution_state.list_human_pending(root, project_id="quick-iching")
            self.assertEqual(len(list_a), 1)
            self.assertEqual(list_a[0]["target_id"], "target-quick-iching-1")

            list_b = execution_state.list_human_pending(root, project_id="project-b")
            self.assertEqual(len(list_b), 1)
            self.assertEqual(list_b[0]["target_id"], "target-project-b-2")

    def test_human_pending_resolve_and_clear_lifecycle(self):
        """RED: 正常恢复生命周期使用 resolve_human_pending；clear 仅作为显式 admin override"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            execution_state.save_human_pending(
                runtime_root=root,
                project_id="quick-iching",
                backlink_id="toollisted",
                domain="toollisted.com",
                blocker_type="EMAIL_OTP",
                current_url="https://toollisted.com/verify",
                target_id="target-toollisted-99",
            )

            # resolve 时若非稳定终态，拒绝 resolve
            with self.assertRaises(ValueError):
                execution_state.resolve_human_pending(
                    root,
                    project_id="quick-iching",
                    backlink_id="toollisted",
                    terminal_status="IN_PROGRESS",
                )

            # clear_human_pending 若未加 admin_override，拒绝删除
            with self.assertRaises(PermissionError):
                execution_state.clear_human_pending(
                    root,
                    project_id="quick-iching",
                    backlink_id="toollisted",
                    admin_override=False,
                )

            # 正常使用稳定终态 resolve
            res = execution_state.resolve_human_pending(
                root,
                project_id="quick-iching",
                backlink_id="toollisted",
                terminal_status="已提交",
            )
            self.assertTrue(res)
            self.assertIsNone(execution_state.load_human_pending(root, "quick-iching", "toollisted"))


if __name__ == "__main__":
    unittest.main()
