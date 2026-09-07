import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from execution_state import (
    evaluate_post_submit_recheck,
    filter_recheck_queue,
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
        # P1 - 问题 2: 未检查 DOM rel 时，master mutation 不得包含 实测链接属性 键，绝不覆盖清空历史事实
        self.assertIsNotNone(res.get("master_mutation"))
        self.assertNotIn("实测链接属性", res["master_mutation"])

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

    def test_h_existing_master_rel_not_overwritten_when_live_dom_rel_is_none(self):
        """测试 H (问题 2): 已有 master_row 实测链接属性=Follow，本次 live_dom_rel=None -> 绝不清空原 Follow"""
        master_row = {
            "外链ID": "existing-dir.com",
            "平台域名": "existing-dir.com",
            "基础状态": "候选",
            "实测链接属性": "Follow",
            "实测免费": "免费",
        }
        project_row = {
            "项目ID": "quick-iching",
            "外链ID": "existing-dir.com",
            "状态": "已提交",
            "目标URL": self.canonical_url,
            "结果链接": "",
        }
        recheck_evidence = {
            "dashboard_status": "published",
            "public_listing_url": "https://existing-dir.com/tools/quick-iching",
            "public_access_verified": True,
            "listing_identity_verified": True,
            "live_dom_rel": None,  # 未查 rel
        }

        res = evaluate_post_submit_recheck(
            project_row=project_row,
            recheck_evidence=recheck_evidence,
            current_date=self.current_date,
            master_row=master_row,
        )
        self.assertTrue(res["ok"])
        # master_mutation 不得包含空的 实测链接属性 覆盖操作
        self.assertIsNotNone(res["master_mutation"])
        self.assertNotIn("实测链接属性", res["master_mutation"])

    def test_i_scheduled_status_preserved_when_scheduled_date_missing(self):
        """测试 I (问题 3): current_status=已排期，scheduled_date missing，dashboard_status=pending -> 必须仍为 已排期"""
        project_row = {
            "项目ID": "quick-iching",
            "外链ID": "scheduled-dir.com",
            "状态": "已排期",
            "目标URL": self.canonical_url,
            "原因/备注": "已排期待发布",
            "证据摘要": "之前记录的排期",
        }
        recheck_evidence = {
            "dashboard_status": "pending",
            "scheduled_date": None,  # 本次未取得新的排期日期
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

    def test_j_filter_recheck_queue(self):
        """测试 J (问题 4): filter_recheck_queue 仅筛选选定项目的已提交/审核中/已排期"""
        rows = [
            {"项目ID": "quick-iching", "外链ID": "a.com", "状态": "已提交"},
            {"项目ID": "quick-iching", "外链ID": "b.com", "状态": "审核中"},
            {"项目ID": "quick-iching", "外链ID": "c.com", "状态": "已排期"},
            {"项目ID": "quick-iching", "外链ID": "d.com", "状态": "待提交"},  # 排除
            {"项目ID": "quick-iching", "外链ID": "e.com", "状态": "需人工"},  # 排除
            {"项目ID": "quick-iching", "外链ID": "f.com", "状态": "失败"},    # 排除
            {"项目ID": "quick-iching", "外链ID": "g.com", "状态": "不适用"},  # 排除
            {"项目ID": "other-proj", "外链ID": "h.com", "状态": "已提交"},    # 跨项目排除
        ]

        selected, err = filter_recheck_queue(rows, selected_project_id="quick-iching", limit=10)
        self.assertIsNone(err)
        self.assertEqual(len(selected), 3)
        self.assertEqual([r["外链ID"] for r in selected], ["a.com", "b.com", "c.com"])

        # 缺少 project_id fail-closed
        empty_res, empty_err = filter_recheck_queue(rows, selected_project_id="")
        self.assertIsNotNone(empty_err)
        self.assertEqual(len(empty_res), 0)

    def test_k_cli_filter_recheck_queue(self):
        """测试 K (问题 4): browser_cli.py filter-recheck-queue 命令行端到端测试"""
        import json
        import subprocess

        rows = [
            {"项目ID": "quick-iching", "外链ID": "a.com", "状态": "已提交"},
            {"项目ID": "quick-iching", "外链ID": "b.com", "状态": "待提交"},
            {"项目ID": "other-project", "外链ID": "c.com", "状态": "已提交"},
        ]
        cmd = [
            sys.executable,
            str(PLUGIN_ROOT / "scripts" / "browser_cli.py"),
            "filter-recheck-queue",
            "--project-rows-json",
            json.dumps(rows),
            "--selected-project-id",
            "quick-iching",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"CLI failed: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["selected_rows"][0]["外链ID"], "a.com")


if __name__ == "__main__":
    unittest.main()
