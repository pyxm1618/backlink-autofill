import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from execution_state import (
    evaluate_post_submit_recheck,
    ProductionSheetGate,
    EvidenceContractError,
)


class TestPostSubmitRecheck(unittest.TestCase):
    """测试问题 8: Post-submit Recheck 复核逻辑与证据驱动状态变迁。"""

    def setUp(self):
        self.project_name = "Quick I Ching"
        self.canonical_url = "https://quickiching.com"
        self.current_date = "2026-09-07"

    def test_a_submitted_to_live_with_dom_rel(self):
        """测试 A: 已提交 -> 公开上线 + rel 实测写入"""
        project_row = {
            "项目ID": "quick-iching",
            "外链ID": "example.com",
            "状态": "已提交",
            "目标URL": self.canonical_url,
            "结果链接": "",
            "原因/备注": "已提交待审核",
            "证据摘要": "",
        }
        recheck_evidence = {
            "dashboard_status": "published",
            "public_listing_url": "https://example.com/tools/quick-iching",
            "public_access_verified": True,
            "listing_identity_verified": True,
            "live_dom_rel": "dofollow",
        }

        res = evaluate_post_submit_recheck(
            project_row=project_row,
            recheck_evidence=recheck_evidence,
            current_date=self.current_date,
        )

        self.assertTrue(res["ok"])
        self.assertEqual(res["proposed_status"], "已上线")
        self.assertEqual(res["project_mutation"]["状态"], "已上线")
        self.assertEqual(
            res["project_mutation"]["结果链接"],
            "https://example.com/tools/quick-iching",
        )
        # 总表实测链接属性写入 Follow
        self.assertIsNotNone(res.get("master_mutation"))
        self.assertEqual(res["master_mutation"]["实测链接属性"], "Follow")

    def test_b_scheduled_future_date_remains_scheduled(self):
        """测试 B: 已排期未到期 -> 保持 已排期"""
        project_row = {
            "项目ID": "quick-iching",
            "外链ID": "launchsite.io",
            "状态": "已排期",
            "目标URL": self.canonical_url,
            "结果链接": "",
            "原因/备注": "排期发布",
            "证据摘要": "预计上线日: 2026-10-15",
        }
        recheck_evidence = {
            "dashboard_status": "scheduled",
            "scheduled_date": "2026-10-15",
            "public_listing_url": None,
            "public_access_verified": False,
            "listing_identity_verified": False,
        }

        res = evaluate_post_submit_recheck(
            project_row=project_row,
            recheck_evidence=recheck_evidence,
            current_date=self.current_date,
        )

        self.assertTrue(res["ok"])
        self.assertEqual(res["proposed_status"], "已排期")
        self.assertEqual(res["project_mutation"]["状态"], "已排期")
        self.assertEqual(res["project_mutation"]["结果链接"], "")
        # 未上线，总表不可有实测链接属性
        if res.get("master_mutation"):
            self.assertEqual(res["master_mutation"].get("实测链接属性", ""), "")

    def test_c_dashboard_live_without_public_url_rejects_live(self):
        """测试 C: 仅 dashboard 显示 live，无公开 URL -> 拒绝 已上线"""
        project_row = {
            "项目ID": "quick-iching",
            "外链ID": "directory.net",
            "状态": "审核中",
            "目标URL": self.canonical_url,
            "结果链接": "",
            "原因/备注": "审核中",
        }
        recheck_evidence = {
            "dashboard_status": "live",
            "public_listing_url": None,
            "public_access_verified": False,
            "listing_identity_verified": False,
        }

        res = evaluate_post_submit_recheck(
            project_row=project_row,
            recheck_evidence=recheck_evidence,
            current_date=self.current_date,
        )

        self.assertTrue(res["ok"])
        self.assertNotEqual(res["proposed_status"], "已上线")
        self.assertEqual(res["project_mutation"]["状态"], "审核中")
        self.assertEqual(res["project_mutation"]["结果链接"], "")

    def test_d_public_url_not_accessible_or_mismatched_rejects_result_url(self):
        """测试 D: 公开 URL 404 / 无法匿名访问 / 身份不匹配 -> 拒绝写结果链接且不标已上线"""
        project_row = {
            "项目ID": "quick-iching",
            "外链ID": "aitools.co",
            "状态": "已提交",
            "目标URL": self.canonical_url,
            "结果链接": "",
        }
        recheck_evidence = {
            "dashboard_status": "published",
            "public_listing_url": "https://aitools.co/tools/quick-iching",
            "public_access_verified": False,  # 404 or auth required
            "listing_identity_verified": False,
        }

        res = evaluate_post_submit_recheck(
            project_row=project_row,
            recheck_evidence=recheck_evidence,
            current_date=self.current_date,
        )

        self.assertNotEqual(res["proposed_status"], "已上线")
        self.assertEqual(res["project_mutation"]["结果链接"], "")

    def test_e_live_page_without_dom_rel_check_leaves_attr_blank(self):
        """测试 E: 未检查 DOM rel -> 实测链接属性 保持为空，严禁猜测"""
        project_row = {
            "项目ID": "quick-iching",
            "外链ID": "saasdir.com",
            "状态": "审核中",
            "目标URL": self.canonical_url,
            "结果链接": "",
        }
        recheck_evidence = {
            "dashboard_status": "approved",
            "public_listing_url": "https://saasdir.com/products/quick-iching",
            "public_access_verified": True,
            "listing_identity_verified": True,
            "live_dom_rel": None,  # 未实际抓取/分析 DOM 中的 rel 属性
        }

        res = evaluate_post_submit_recheck(
            project_row=project_row,
            recheck_evidence=recheck_evidence,
            current_date=self.current_date,
        )

        self.assertEqual(res["proposed_status"], "已上线")
        self.assertEqual(
            res["project_mutation"]["结果链接"],
            "https://saasdir.com/products/quick-iching",
        )
        # 总表实测链接属性必须严格保持为空
        if res.get("master_mutation"):
            self.assertEqual(res["master_mutation"].get("实测链接属性", ""), "")

    def test_f_recheck_forbids_submit_actions(self):
        """测试 F: Recheck 过程严禁再次触发提交动作"""
        project_row = {
            "项目ID": "quick-iching",
            "外链ID": "recheck-test.org",
            "状态": "已提交",
        }
        recheck_evidence = {
            "dashboard_status": "pending",
        }

        res = evaluate_post_submit_recheck(
            project_row=project_row,
            recheck_evidence=recheck_evidence,
            current_date=self.current_date,
        )
        self.assertTrue(res["is_readonly"])
        self.assertNotIn("submit", res.get("allowed_actions", []))
        self.assertIn("submit", res.get("forbidden_actions", []))

    def test_g_cli_recheck_evaluate(self):
        """测试 G: browser_cli.py recheck-evaluate 命令输出符合预期"""
        import json
        import subprocess

        project_row = {
            "项目ID": "quick-iching",
            "外链ID": "example.com",
            "状态": "已提交",
            "目标URL": self.canonical_url,
            "结果链接": "",
        }
        recheck_evidence = {
            "dashboard_status": "published",
            "public_listing_url": "https://example.com/tools/quick-iching",
            "public_access_verified": True,
            "listing_identity_verified": True,
            "live_dom_rel": "dofollow",
        }

        cmd = [
            sys.executable,
            str(PLUGIN_ROOT / "scripts" / "browser_cli.py"),
            "recheck-evaluate",
            "--project-row-json",
            json.dumps(project_row),
            "--recheck-evidence-json",
            json.dumps(recheck_evidence),
            "--current-date",
            self.current_date,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"CLI failed: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["proposed_status"], "已上线")
        self.assertEqual(
            data["project_mutation"]["结果链接"],
            "https://example.com/tools/quick-iching",
        )
        self.assertEqual(data["master_mutation"]["实测链接属性"], "Follow")


if __name__ == "__main__":
    unittest.main()
