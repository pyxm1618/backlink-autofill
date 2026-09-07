import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from execution_state import (
    detect_existing_project_submission,
    detect_anonymous_submission_preflight,
)


class TestAnonymousSubmissionPreflight(unittest.TestCase):
    """测试问题 6: 匿名免费表单 Preflight 机制与防重复提交约束。"""

    def setUp(self):
        self.project_name = "Quick I Ching"
        self.canonical_url = "https://quickiching.com/"

    def test_a_ordinary_anonymous_form_passes_preflight(self):
        """测试 A: 普通匿名免费 submission form -> 可以通过 preflight (SAFE/NOT_FOUND)"""
        page_evidence = {
            "is_anonymous_form": True,
            "requires_login": False,
            "form_fields": ["website", "title", "description", "email"],
        }
        project_row = {
            "项目ID": "quick-iching",
            "状态": "待提交",
            "尝试次数": "0",
            "原因/备注": "",
            "证据摘要": "",
        }

        res = detect_anonymous_submission_preflight(
            page_evidence=page_evidence,
            project_row=project_row,
            project_name=self.project_name,
            canonical_url=self.canonical_url,
            public_search_content=None,
        )
        self.assertIn(res["verdict"], ("SAFE", "NOT_FOUND"))
        self.assertIn("passed", res["reason"].lower())

    def test_b_existing_final_submit_evidence_rejects_duplicate(self):
        """测试 B: 当前行已有 final-submit / 已提交 evidence -> 拒绝重复提交"""
        page_evidence = {
            "is_anonymous_form": True,
            "requires_login": False,
        }
        # 已经在控制面中提交过
        project_row = {
            "项目ID": "quick-iching",
            "状态": "已提交",
            "尝试次数": "1",
            "原因/备注": "已提交待审核",
            "证据摘要": "提交成功提示",
        }

        res = detect_anonymous_submission_preflight(
            page_evidence=page_evidence,
            project_row=project_row,
            project_name=self.project_name,
            canonical_url=self.canonical_url,
        )
        self.assertEqual(res["verdict"], "FOUND")
        self.assertIn("already", res["reason"].lower())

    def test_c_uncertain_outcome_halts_for_human_and_rejects_auto_retry(self):
        """测试 C: 当前 submission outcome uncertain -> 需人工，绝不自动 retry"""
        page_evidence = {
            "is_anonymous_form": True,
            "requires_login": False,
        }
        project_row = {
            "项目ID": "quick-iching",
            "状态": "需人工",
            "尝试次数": "1",
            "原因/备注": "已执行提交但结果不明确，避免重复提交",
            "证据摘要": "网络超时，提交可能已到达服务器",
        }

        res = detect_anonymous_submission_preflight(
            page_evidence=page_evidence,
            project_row=project_row,
            project_name=self.project_name,
            canonical_url=self.canonical_url,
        )
        self.assertEqual(res["verdict"], "UNKNOWN")
        self.assertIn("uncertain", res["reason"].lower())

    def test_d_account_based_platform_routes_to_dashboard_preflight(self):
        """测试 D: 需要登录的平台不能走匿名通过，必须由原 dashboard preflight 接管"""
        page_evidence = {
            "is_anonymous_form": False,
            "requires_login": True,
        }
        project_row = {
            "项目ID": "quick-iching",
            "状态": "待提交",
            "尝试次数": "0",
        }

        res = detect_anonymous_submission_preflight(
            page_evidence=page_evidence,
            project_row=project_row,
            project_name=self.project_name,
            canonical_url=self.canonical_url,
        )
        self.assertEqual(res["verdict"], "REQUIRES_LOGIN")

    def test_e_account_based_unknown_still_forbids_final_submit(self):
        """测试 E: 原有的 account-based listings UNKNOWN 仍然绝对禁止自动 Final Submit"""
        ambiguous_html = "<div>Welcome to member dashboard! Profile details and user settings.</div>"
        res = detect_existing_project_submission(
            content=ambiguous_html,
            project_name=self.project_name,
            canonical_url=self.canonical_url,
        )
        self.assertEqual(res["verdict"], "UNKNOWN")

    def test_regression_1_empty_page_evidence_returns_unknown(self):
        """Regression 1: page_evidence={} -> UNKNOWN"""
        res = detect_anonymous_submission_preflight(
            page_evidence={},
            project_row={"项目ID": "quick-iching", "状态": "待提交"},
            project_name=self.project_name,
            canonical_url=self.canonical_url,
        )
        self.assertEqual(res["verdict"], "UNKNOWN")

    def test_regression_2_missing_requires_login_returns_unknown(self):
        """Regression 2: is_anonymous_form=True 但 requires_login 缺失 -> UNKNOWN"""
        res = detect_anonymous_submission_preflight(
            page_evidence={"is_anonymous_form": True},
            project_row={"项目ID": "quick-iching", "状态": "待提交"},
            project_name=self.project_name,
            canonical_url=self.canonical_url,
        )
        self.assertEqual(res["verdict"], "UNKNOWN")

    def test_regression_3_failed_status_rejects_safe(self):
        """Regression 3: 状态=失败 -> 不得 SAFE (必须 fail-closed 为 UNKNOWN)"""
        page_evidence = {"is_anonymous_form": True, "requires_login": False}
        res = detect_anonymous_submission_preflight(
            page_evidence=page_evidence,
            project_row={"项目ID": "quick-iching", "状态": "失败"},
            project_name=self.project_name,
            canonical_url=self.canonical_url,
        )
        self.assertNotEqual(res["verdict"], "SAFE")
        self.assertEqual(res["verdict"], "UNKNOWN")

    def test_regression_4_needs_human_without_uncertain_cues_rejects_safe(self):
        """Regression 4: 状态=需人工但无 uncertain 文案 -> 不得 SAFE"""
        page_evidence = {"is_anonymous_form": True, "requires_login": False}
        res = detect_anonymous_submission_preflight(
            page_evidence=page_evidence,
            project_row={"项目ID": "quick-iching", "状态": "需人工", "原因/备注": "验证码阻塞"},
            project_name=self.project_name,
            canonical_url=self.canonical_url,
        )
        self.assertNotEqual(res["verdict"], "SAFE")
        self.assertEqual(res["verdict"], "UNKNOWN")

    def test_regression_5_in_progress_status_can_be_safe(self):
        """Regression 5: 状态=处理中且页面证据完整 -> 可 SAFE"""
        page_evidence = {"is_anonymous_form": True, "requires_login": False}
        res = detect_anonymous_submission_preflight(
            page_evidence=page_evidence,
            project_row={"项目ID": "quick-iching", "状态": "处理中"},
            project_name=self.project_name,
            canonical_url=self.canonical_url,
        )
        self.assertEqual(res["verdict"], "SAFE")

    def test_regression_6_public_search_unknown_returns_unknown(self):
        """Regression 6: public search = UNKNOWN -> UNKNOWN (禁止当作没找到)"""
        page_evidence = {"is_anonymous_form": True, "requires_login": False}
        ambiguous_search_page = "<div>Welcome to search portal! Unstructured text.</div>"
        res = detect_anonymous_submission_preflight(
            page_evidence=page_evidence,
            project_row={"项目ID": "quick-iching", "状态": "待提交"},
            project_name=self.project_name,
            canonical_url=self.canonical_url,
            public_search_content=ambiguous_search_page,
        )
        self.assertEqual(res["verdict"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
