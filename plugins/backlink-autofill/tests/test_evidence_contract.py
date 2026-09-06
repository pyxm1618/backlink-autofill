#!/usr/bin/env python3
"""Regression tests enforcing the universal Evidence & State Contract."""

import unittest
from pathlib import Path
import sys

scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from execution_state import (
    classify_project_status,
    sanitize_result_url,
    enrich_master_facts,
    build_project_row_update,
    EvidenceContractError,
    ProductionSheetGate,
)
from browser_runtime import BrowserRuntime, BrowserRuntimeError


class TestEvidenceContract(unittest.TestCase):
    def test_red_a_history_follow_cannot_pollute_observed_follow(self):
        """Invariant 1 & 2: Prior research/discovery stating Follow must never pollute observed link attribute."""
        prior_facts = {
            "外链ID": "example.com",
            "平台域名": "example.com",
            "发现来源": "BacklinkOS/已确认免费Follow",
            "实测链接属性": "",
            "平台备注": "History suggests Follow",
        }
        observed = {
            "free": True,
            "requires_login": True,
            "login_method": "Google OAuth",
            "listing_live": False,
            "live_dom_rel": None,
        }
        enriched = enrich_master_facts(prior_facts=prior_facts, observed=observed)
        self.assertEqual(enriched["实测链接属性"], "")

    def test_red_b_dashboard_url_cannot_be_result_url(self):
        """Invariant 3: Dashboard/admin/payment/queue URLs can never be written to 结果链接."""
        dashboard_url = "https://example.com/dashboard"
        sanitized = sanitize_result_url(dashboard_url)
        self.assertEqual(sanitized, "")

        queue_url = "https://example.com/payment/Tw3PaO2ZYPQoodHTCNdenU"
        self.assertEqual(sanitize_result_url(queue_url), "")

        row_update = build_project_row_update(
            status="审核中",
            raw_result_url=queue_url,
            evidence_summary="Status: Pending on queue page",
        )
        self.assertEqual(row_update["结果链接"], "")
        self.assertIn("Tw3PaO2ZYPQoodHTCNdenU", row_update["证据摘要"])

    def test_red_c_scheduled_date_prioritizes_scheduled_status(self):
        """Invariant 4: Explicit scheduled/launch date prioritizes 已排期 over 审核中."""
        evidence = {
            "final_submit_occurred": True,
            "platform_status_text": "Pending review",
            "scheduled_date": "2027-03-25",
            "public_listing_url": None,
        }
        status = classify_project_status(evidence)
        self.assertEqual(status, "已排期")

    def test_red_d_cannot_claim_live_without_verified_public_page(self):
        """Invariant 4: Dashboard claiming Live without a verified public page must not be classified as 已上线."""
        evidence = {
            "final_submit_occurred": True,
            "platform_status_text": "Live",
            "public_listing_url": None,
            "public_listing_verified": False,
        }
        with self.assertRaises(EvidenceContractError):
            classify_project_status(evidence, strict=True)

        status = classify_project_status(evidence, strict=False)
        self.assertNotEqual(status, "已上线")

    def test_red_e_observed_master_facts_require_current_execution_evidence(self):
        """Invariant 1 & 6: Master observed facts require direct browser evidence from current run."""
        prior_facts = {
            "实测免费": "",
            "实测需登录": "",
            "实测登录方式": "",
            "实测链接属性": "",
            "历史研究": {
                "free": True,
                "login": "Google",
                "follow": True,
            },
        }
        observed = {
            "free": True,
            "requires_login": True,
            "login_method": "Google OAuth",
        }
        enriched = enrich_master_facts(prior_facts=prior_facts, observed=observed)
        self.assertEqual(enriched["实测免费"], "免费")
        self.assertEqual(enriched["实测需登录"], "需要")
        self.assertEqual(enriched["实测登录方式"], "Google OAuth")
        self.assertEqual(enriched["实测链接属性"], "")

    def test_red_f_browser_runtime_rejects_control_plane_mutation(self):
        """Invariant 5: Browser Runtime must never navigate to or mutate Google Sheets/Drive control plane."""
        runtime = BrowserRuntime(profile_dir=Path("/tmp/test-profile"), headless=True)
        sheet_url = "https://docs.google.com/spreadsheets/d/1uUmlPGzjxNe-XkvWfjuC3c5exiOxZuFJWvHqPTwjaTA/edit"
        with self.assertRaises(BrowserRuntimeError) as ctx:
            runtime.navigate(sheet_url)
        self.assertEqual(ctx.exception.code, "CONTROL_PLANE_URL_FORBIDDEN")


class TestProductionMutationGate(unittest.TestCase):
    """Production hard-gate regression tests: no Sheet mutation can bypass Evidence Contract."""

    def test_prod_gate_rejects_follow_when_listing_not_live(self):
        """Production Gate 1: listing not live + 实测链接属性=Follow -> MUST BE REJECTED."""
        evidence = {
            "listing_live": False,
            "live_dom_rel": None,
        }
        proposed = {
            "实测链接属性": "Follow",
        }
        with self.assertRaises(EvidenceContractError) as ctx:
            ProductionSheetGate.validate_master_mutation(
                evidence=evidence,
                prior_facts=None,
                proposed=proposed,
            )
        self.assertIn("实测链接属性", str(ctx.exception))

    def test_prod_gate_rejects_dashboard_as_result_url(self):
        """Production Gate 2: dashboard URL written to 结果链接 -> MUST BE REJECTED."""
        evidence = {
            "final_submit_occurred": True,
        }
        proposed = {
            "状态": "审核中",
            "结果链接": "https://example.com/dashboard",
        }
        with self.assertRaises(EvidenceContractError) as ctx:
            ProductionSheetGate.validate_project_mutation(
                evidence=evidence,
                proposed=proposed,
            )
        self.assertIn("结果链接", str(ctx.exception))

    def test_prod_gate_rejects_live_without_verified_public_listing(self):
        """Production Gate 3: claims 已上线 without verified public listing -> MUST BE REJECTED."""
        evidence = {
            "final_submit_occurred": True,
            "public_listing_url": None,
            "public_listing_verified": False,
        }
        proposed = {
            "状态": "已上线",
            "结果链接": "",
        }
        with self.assertRaises(EvidenceContractError) as ctx:
            ProductionSheetGate.validate_project_mutation(
                evidence=evidence,
                proposed=proposed,
            )
        self.assertIn("已上线", str(ctx.exception))

    def test_prod_gate_normalizes_or_rejects_scheduled_date_under_review(self):
        """Production Gate 4: scheduled_date exists + proposed 审核中 -> normalize to 已排期 or reject."""
        evidence = {
            "final_submit_occurred": True,
            "scheduled_date": "2027-03-25",
        }
        proposed = {
            "状态": "审核中",
            "原因/备注": "Waiting in queue",
        }
        # In standard mode, it normalizes to 已排期
        normalized = ProductionSheetGate.validate_project_mutation(
            evidence=evidence,
            proposed=proposed,
            strict_schedule=False,
        )
        self.assertEqual(normalized["状态"], "已排期")

        # In strict mode, it rejects the mismatch
        with self.assertRaises(EvidenceContractError) as ctx:
            ProductionSheetGate.validate_project_mutation(
                evidence=evidence,
                proposed=proposed,
                strict_schedule=True,
            )
        self.assertIn("已排期", str(ctx.exception))

    def test_prod_gate_rejects_prior_history_polluting_master_observed(self):
        """Production Gate 5: prior/history evidence attempting to populate 实测* -> MUST BE REJECTED."""
        prior_facts = {
            "发现来源": "BacklinkOS/已确认免费Follow",
            "历史研究": {"free": True, "login": "Google"},
            "平台备注": "History suggests free with login",
        }
        evidence = {}  # Current run observed nothing directly
        proposed = {
            "实测免费": "免费",
            "实测需登录": "需要",
        }
        with self.assertRaises(EvidenceContractError) as ctx:
            ProductionSheetGate.validate_master_mutation(
                evidence=evidence,
                prior_facts=prior_facts,
                proposed=proposed,
            )
        self.assertIn("实测", str(ctx.exception))

    def test_sanitize_result_url_requires_positive_evidence(self):
        """Audit sanitize_result_url: absence of blacklist words is NOT sufficient; requires positive evidence."""
        clean_url = "https://example.com/company/quickiching"

        # 1. No evidence -> must be empty
        self.assertEqual(sanitize_result_url(clean_url), "")

        # 2. Evidence missing identity verification -> must be empty
        unverified_evidence = {
            "public_access_verified": True,
            "listing_identity_verified": False,
        }
        self.assertEqual(sanitize_result_url(clean_url, evidence=unverified_evidence), "")

        # 3. Evidence missing public access verification -> must be empty
        unverified_access = {
            "public_access_verified": False,
            "listing_identity_verified": True,
        }
        self.assertEqual(sanitize_result_url(clean_url, evidence=unverified_access), "")

        # 4. Positive evidence complete -> allowed
        verified_evidence = {
            "public_access_verified": True,
            "listing_identity_verified": True,
        }
        self.assertEqual(sanitize_result_url(clean_url, evidence=verified_evidence), clean_url)

        # 5. Blacklist word present -> rejected even if positive evidence claimed
        dashboard_url = "https://example.com/company/quickiching/dashboard"
        self.assertEqual(sanitize_result_url(dashboard_url, evidence=verified_evidence), "")

    def test_cli_production_gate_entrypoint(self):
        """Production Entrypoint CLI test: browser_cli.py enforces Evidence Contract via process exit codes."""
        import subprocess
        import json

        cli_path = scripts_dir / "browser_cli.py"

        # 1. CLI rejects dashboard URL in 结果链接
        res = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "validate-project-mutation",
                "--evidence-json",
                json.dumps({"final_submit_occurred": True}),
                "--proposed-json",
                json.dumps({"状态": "审核中", "结果链接": "https://example.com/dashboard"}),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 2)
        err = json.loads(res.stderr)
        self.assertEqual(err["error_code"], "EVIDENCE_CONTRACT_VIOLATION")
        self.assertIn("结果链接", err["message"])

        # 2. CLI rejects Follow when listing not live
        res_master = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "validate-master-mutation",
                "--evidence-json",
                json.dumps({"listing_live": False, "live_dom_rel": None}),
                "--proposed-json",
                json.dumps({"实测链接属性": "Follow"}),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res_master.returncode, 2)
        err_master = json.loads(res_master.stderr)
        self.assertEqual(err_master["error_code"], "EVIDENCE_CONTRACT_VIOLATION")
        self.assertIn("实测链接属性", err_master["message"])

        # 3. CLI accepts valid positive evidence mutation
        valid_res = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "validate-project-mutation",
                "--evidence-json",
                json.dumps({
                    "final_submit_occurred": True,
                    "public_listing_url": "https://example.com/listings/quickiching",
                    "public_access_verified": True,
                    "listing_identity_verified": True,
                    "public_listing_verified": True,
                }),
                "--proposed-json",
                json.dumps({
                    "状态": "已上线",
                    "结果链接": "https://example.com/listings/quickiching",
                    "原因/备注": "Listing live",
                }),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(valid_res.returncode, 0)
        output = json.loads(valid_res.stdout)
        self.assertTrue(output["ok"])
        self.assertEqual(output["validated"]["状态"], "已上线")
        self.assertEqual(output["validated"]["结果链接"], "https://example.com/listings/quickiching")


class TestSheetSchemaAndStatusContract(unittest.TestCase):
    """Universal Sheet Schema and 9-Status Roundtrip Regression Tests."""

    def test_nine_statuses_roundtrip(self):
        from execution_state import SHEET_TO_INTERNAL, INTERNAL_TO_SHEET, sheet_status_to_internal, internal_to_sheet_status

        expected_statuses = [
            "待提交",
            "处理中",
            "已提交",
            "审核中",
            "已排期",
            "已上线",
            "需人工",
            "失败",
            "不适用",
        ]
        self.assertEqual(len(expected_statuses), 9)
        self.assertEqual(sorted(SHEET_TO_INTERNAL.keys()), sorted(expected_statuses))

        for status in expected_statuses:
            internal = sheet_status_to_internal(status)
            self.assertIsNotNone(internal)
            roundtripped = internal_to_sheet_status(internal)
            self.assertEqual(roundtripped, status)

    def test_sheet_contract_document_alignment(self):
        contract_path = Path(__file__).resolve().parents[1] / "references" / "project-sheet-contract.md"
        content = contract_path.read_text(encoding="utf-8")

        # 验证新 Tab 名与字段
        self.assertIn("`外链管理`", content)
        self.assertIn("外链ID | 平台域名 | 提交入口", content)
        self.assertIn("项目ID | 外链ID | 外链域名 | 状态 | 尝试次数 | 最近操作时间 | 目标URL | 结果链接 | 原因/备注 | 证据摘要", content)
        # 隐藏列说明
        self.assertIn("外链ID` (Col B, UI 隐藏列)", content)
        self.assertIn("尝试次数` (Col E, UI 隐藏列)", content)
        self.assertIn("目标URL` (Col G, UI 隐藏列)", content)
        # UI 冻结说明
        self.assertIn("Freeze physical columns A:C", content)
        # 旧 Tab 必须已更名
        self.assertNotIn("Tab `项目外链管理`", content)


class TestMasterGateProtection(unittest.TestCase):
    """Enforce Master Execution Gate rules before browser action launch."""

    def test_eligible_candidate_master(self):
        from execution_state import check_master_execution_eligibility

        master_row = {
            "外链ID": "example.com",
            "平台域名": "example.com",
            "提交入口": "https://example.com/submit",
            "基础状态": "候选",
        }
        res = check_master_execution_eligibility(master_row)
        self.assertTrue(res["eligible"])
        self.assertEqual(res["status"], "待提交")
        self.assertEqual(res["entry_url"], "https://example.com/submit")

    def test_master_excluded_maps_to_not_applicable(self):
        from execution_state import check_master_execution_eligibility

        master_row = {
            "外链ID": "spam.com",
            "基础状态": "已排除",
            "基础排除原因": "Domain parked / scam site",
            "提交入口": "https://spam.com/submit",
        }
        res = check_master_execution_eligibility(master_row)
        self.assertFalse(res["eligible"])
        self.assertEqual(res["status"], "不适用")
        self.assertIn("外链总表基础状态为已排除：Domain parked / scam site", res["reason"])

    def test_master_invalid_maps_to_failed(self):
        from execution_state import check_master_execution_eligibility

        master_row = {
            "外链ID": "dead.com",
            "基础状态": "失效",
            "提交入口": "https://dead.com/submit",
        }
        res = check_master_execution_eligibility(master_row)
        self.assertFalse(res["eligible"])
        self.assertEqual(res["status"], "失败")
        self.assertEqual(res["reason"], "外链总表基础状态为失效")

    def test_missing_master_row(self):
        from execution_state import check_master_execution_eligibility

        res = check_master_execution_eligibility(None)
        self.assertFalse(res["eligible"])
        self.assertEqual(res["status"], "失败")
        self.assertEqual(res["reason"], "外链ID在外链总表中不存在")

    def test_duplicate_master_rows(self):
        from execution_state import check_master_execution_eligibility

        master_row = {"外链ID": "dupe.com", "提交入口": "https://dupe.com/submit"}
        res = check_master_execution_eligibility(master_row, master_candidates_count=2)
        self.assertFalse(res["eligible"])
        self.assertEqual(res["status"], "失败")
        self.assertEqual(res["reason"], "外链ID在外链总表中不唯一")

    def test_missing_entry_url_integrity_failure(self):
        from execution_state import check_master_execution_eligibility

        master_row = {
            "外链ID": "noentry.com",
            "基础状态": "候选",
            "提交入口": "",
        }
        res = check_master_execution_eligibility(master_row)
        self.assertFalse(res["eligible"])
        self.assertEqual(res["status"], "失败")
        self.assertEqual(res["reason"], "缺少有效提交入口")

    def test_validate_execution_start_ineligible_preserves_attempt_count(self):
        """P0-4 & P0-5: Master Gate 拦截时绝对不累加尝试次数，尝试次数严格只对应真实浏览器执行尝试"""
        from execution_state import validate_execution_start

        project_row_0 = {
            "项目ID": "quick-iching",
            "外链ID": "test.com",
            "状态": "待提交",
            "尝试次数": "0",
            "目标URL": "https://quickiching.com",
        }
        project_row_1 = {
            "项目ID": "quick-iching",
            "外链ID": "test.com",
            "状态": "待提交",
            "尝试次数": "1",
            "目标URL": "https://quickiching.com",
        }

        # 1. Master 缺失 -> 失败，尝试次数保持 0，绝不增加
        res_missing = validate_execution_start(project_row_0, master_rows=[])
        self.assertFalse(res_missing["eligible"])
        self.assertEqual(res_missing["proposed_status"], "失败")
        self.assertEqual(res_missing["current_attempt_count"], 0)
        self.assertEqual(res_missing["next_attempt_count"], 0)
        self.assertEqual(res_missing["project_mutation"]["尝试次数"], "0")
        self.assertEqual(res_missing["project_mutation"]["状态"], "失败")
        self.assertIsNone(res_missing["verified_entry_url"])

        # 2. Master 重复 -> 失败，尝试次数保持 1
        dupe_masters = [
            {"外链ID": "test.com", "提交入口": "https://test.com/submit1"},
            {"外链ID": "test.com", "提交入口": "https://test.com/submit2"},
        ]
        res_dupe = validate_execution_start(project_row_1, master_rows=dupe_masters)
        self.assertFalse(res_dupe["eligible"])
        self.assertEqual(res_dupe["proposed_status"], "失败")
        self.assertEqual(res_dupe["current_attempt_count"], 1)
        self.assertEqual(res_dupe["next_attempt_count"], 1)
        self.assertEqual(res_dupe["project_mutation"]["尝试次数"], "1")

        # 3. Master 已排除 -> 不适用，尝试次数保持 0
        excluded_master = [{
            "外链ID": "test.com",
            "基础状态": "已排除",
            "基础排除原因": "Domain parked",
            "提交入口": "https://test.com/submit",
        }]
        res_excl = validate_execution_start(project_row_0, master_rows=excluded_master)
        self.assertFalse(res_excl["eligible"])
        self.assertEqual(res_excl["proposed_status"], "不适用")
        self.assertEqual(res_excl["next_attempt_count"], 0)
        self.assertEqual(res_excl["project_mutation"]["尝试次数"], "0")
        self.assertEqual(res_excl["project_mutation"]["状态"], "不适用")

        # 4. Master 失效 -> 失败，尝试次数保持 1
        dead_master = [{
            "外链ID": "test.com",
            "基础状态": "失效",
            "提交入口": "https://test.com/submit",
        }]
        res_dead = validate_execution_start(project_row_1, master_rows=dead_master)
        self.assertFalse(res_dead["eligible"])
        self.assertEqual(res_dead["proposed_status"], "失败")
        self.assertEqual(res_dead["next_attempt_count"], 1)
        self.assertEqual(res_dead["project_mutation"]["尝试次数"], "1")

        # 5. Master 无有效提交入口 -> 失败，尝试次数保持 0
        no_url_master = [{
            "外链ID": "test.com",
            "基础状态": "候选",
            "提交入口": "javascript:void(0)",
        }]
        res_nourl = validate_execution_start(project_row_0, master_rows=no_url_master)
        self.assertFalse(res_nourl["eligible"])
        self.assertEqual(res_nourl["proposed_status"], "失败")
        self.assertEqual(res_nourl["next_attempt_count"], 0)
        self.assertEqual(res_nourl["project_mutation"]["尝试次数"], "0")

    def test_validate_execution_start_eligible_increments_attempt_count(self):
        """P0-4: 只有 Master 验证合格启动执行时，尝试次数才严格 +1 并产生处理中变更"""
        from execution_state import validate_execution_start

        project_row = {
            "项目ID": "quick-iching",
            "外链ID": "valid.com",
            "状态": "待提交",
            "尝试次数": "0",
            "目标URL": "https://quickiching.com",
        }
        valid_master = [{
            "外链ID": "valid.com",
            "平台域名": "valid.com",
            "基础状态": "候选",
            "提交入口": "https://valid.com/submit",
        }]
        res = validate_execution_start(project_row, master_rows=valid_master)
        self.assertTrue(res["eligible"])
        self.assertEqual(res["proposed_status"], "处理中")
        self.assertEqual(res["current_attempt_count"], 0)
        self.assertEqual(res["next_attempt_count"], 1)
        self.assertEqual(res["verified_entry_url"], "https://valid.com/submit")
        self.assertEqual(res["project_mutation"]["状态"], "处理中")
        self.assertEqual(res["project_mutation"]["尝试次数"], "1")

    def test_cli_validate_execution_start_entrypoint(self):
        """P0-5: browser_cli.py validate-execution-start 作为独立生产门禁命令"""
        import subprocess
        import json

        cli_path = scripts_dir / "browser_cli.py"

        # 1. 不合格情形：通过 CLI 调用，返回 JSON eligible=False 且尝试次数保持 0
        res_ineligible = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "validate-execution-start",
                "--project-row-json",
                json.dumps({"项目ID": "p1", "外链ID": "bad.com", "尝试次数": "0"}),
                "--master-rows-json",
                json.dumps([{
                    "外链ID": "bad.com",
                    "基础状态": "已排除",
                    "基础排除原因": "Spam directory",
                    "提交入口": "https://bad.com/submit",
                }]),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res_ineligible.returncode, 0)
        out_ineligible = json.loads(res_ineligible.stdout)
        self.assertTrue(out_ineligible["ok"])
        self.assertFalse(out_ineligible["eligible"])
        self.assertEqual(out_ineligible["proposed_status"], "不适用")
        self.assertEqual(out_ineligible["next_attempt_count"], 0)

        # 2. 合格情形：通过 CLI 调用，返回 JSON eligible=True 且尝试次数 +1
        res_eligible = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "validate-execution-start",
                "--project-row-json",
                json.dumps({"项目ID": "p1", "外链ID": "good.com", "尝试次数": "0", "目标URL": "https://p1.com"}),
                "--master-rows-json",
                json.dumps([{
                    "外链ID": "good.com",
                    "平台域名": "good.com",
                    "基础状态": "候选",
                    "提交入口": "https://good.com/submit",
                }]),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res_eligible.returncode, 0)
        out_eligible = json.loads(res_eligible.stdout)
        self.assertTrue(out_eligible["ok"])
        self.assertTrue(out_eligible["eligible"])
        self.assertEqual(out_eligible["proposed_status"], "处理中")
        self.assertEqual(out_eligible["next_attempt_count"], 1)
        self.assertEqual(out_eligible["verified_entry_url"], "https://good.com/submit")

    def test_validate_execution_start_empty_project_backlink_id(self):
        """P0-Gate: project 外链ID 为空，直接失败，不自增尝试次数"""
        from execution_state import validate_execution_start

        project_row = {"外链ID": "   ", "状态": "待提交", "尝试次数": "1"}
        master_rows = [{"外链ID": "valid.com", "平台域名": "valid.com", "基础状态": "候选", "提交入口": "https://valid.com"}]
        res = validate_execution_start(project_row, master_rows)
        self.assertFalse(res["eligible"])
        self.assertEqual(res["proposed_status"], "失败")
        self.assertIn("缺少外链ID", res["reason"])
        self.assertEqual(res["next_attempt_count"], 1)

    def test_validate_execution_start_wrong_master_id(self):
        """P0-Gate: master.外链ID != project.外链ID，Join 身份不一致必须失败"""
        from execution_state import validate_execution_start

        project_row = {"外链ID": "alpha.com", "状态": "待提交", "尝试次数": "0"}
        master_rows = [{"外链ID": "beta.com", "平台域名": "beta.com", "基础状态": "候选", "提交入口": "https://beta.com"}]
        res = validate_execution_start(project_row, master_rows)
        self.assertFalse(res["eligible"])
        self.assertEqual(res["proposed_status"], "失败")
        self.assertIn("不匹配", res["reason"])
        self.assertEqual(res["next_attempt_count"], 0)

    def test_validate_execution_start_blank_or_unknown_master_status(self):
        """P0-Gate: master 基础状态必须精确为候选；空值或未知值 fail closed"""
        from execution_state import validate_execution_start

        project_row = {"外链ID": "valid.com", "状态": "待提交", "尝试次数": "0"}

        # 1. 基础状态为空
        res_blank = validate_execution_start(project_row, [{
            "外链ID": "valid.com", "平台域名": "valid.com", "基础状态": "", "提交入口": "https://valid.com"
        }])
        self.assertFalse(res_blank["eligible"])
        self.assertEqual(res_blank["proposed_status"], "失败")
        self.assertIn("缺少基础状态", res_blank["reason"])

        # 2. 基础状态为未知非法值
        res_unknown = validate_execution_start(project_row, [{
            "外链ID": "valid.com", "平台域名": "valid.com", "基础状态": "未知状态", "提交入口": "https://valid.com"
        }])
        self.assertFalse(res_unknown["eligible"])
        self.assertEqual(res_unknown["proposed_status"], "失败")
        self.assertIn("非法或未处于候选状态", res_unknown["reason"])

    def test_validate_execution_start_missing_canonical_platform_domain(self):
        """P0-Gate: 缺少 canonical 平台域名必须 fail closed"""
        from execution_state import validate_execution_start

        project_row = {"外链ID": "valid.com", "状态": "待提交", "尝试次数": "0"}
        res = validate_execution_start(project_row, [{
            "外链ID": "valid.com", "平台域名": "  ", "基础状态": "候选", "提交入口": "https://valid.com/submit"
        }])
        self.assertFalse(res["eligible"])
        self.assertEqual(res["proposed_status"], "失败")
        self.assertIn("缺少平台域名", res["reason"])

    def test_validate_execution_start_cross_domain_entry(self):
        """P0-Gate: 提交入口必须与 master 平台域名 same-origin (支持合法子域名，拒绝跨域/欺骗后缀)"""
        from execution_state import validate_execution_start

        project_row = {"外链ID": "example.com", "状态": "待提交", "尝试次数": "0"}

        # 跨域拦截
        res_cross = validate_execution_start(project_row, [{
            "外链ID": "example.com", "平台域名": "example.com", "基础状态": "候选", "提交入口": "https://attacker.com/submit"
        }])
        self.assertFalse(res_cross["eligible"])
        self.assertEqual(res_cross["proposed_status"], "失败")
        self.assertIn("不匹配", res_cross["reason"])

        # 后缀钓鱼拦截
        res_phish = validate_execution_start(project_row, [{
            "外链ID": "example.com", "平台域名": "example.com", "基础状态": "候选", "提交入口": "https://example.com.evil.org/submit"
        }])
        self.assertFalse(res_phish["eligible"])
        self.assertIn("不匹配", res_phish["reason"])

        # 合法子域名放行
        res_sub = validate_execution_start(project_row, [{
            "外链ID": "example.com", "平台域名": "example.com", "基础状态": "候选", "提交入口": "https://auth.example.com/submit"
        }])
        self.assertTrue(res_sub["eligible"])

    def test_validate_execution_start_terminal_project_status(self):
        """P0-Gate: 正常启动时 project.状态 必须为 待提交；terminal 状态拒绝启动"""
        from execution_state import validate_execution_start

        master = [{"外链ID": "valid.com", "平台域名": "valid.com", "基础状态": "候选", "提交入口": "https://valid.com/submit"}]

        for terminal in ("已上线", "审核中", "已提交", "已排期", "失败", "不适用"):
            project_row = {"外链ID": "valid.com", "状态": terminal, "尝试次数": "2"}
            res = validate_execution_start(project_row, master)
            self.assertFalse(res["eligible"], f"Status {terminal} should not be eligible for normal start")
            self.assertEqual(res["next_attempt_count"], 2)

    def test_validate_execution_start_resume_same_attempt_semantics(self):
        """P0-Gate: same-attempt resume 保持尝试次数不自增，且只允许需人工或中断处理中"""
        from execution_state import validate_execution_start

        master = [{"外链ID": "valid.com", "平台域名": "valid.com", "基础状态": "候选", "提交入口": "https://valid.com/submit"}]

        # 1. 正常的需人工行恢复：尝试次数保持为 1，不自增
        res_resume_human = validate_execution_start(
            {"外链ID": "valid.com", "状态": "需人工", "尝试次数": "1", "原因/备注": "等待邮箱验证码"},
            master,
            resume_same_attempt=True,
        )
        self.assertTrue(res_resume_human["eligible"])
        self.assertEqual(res_resume_human["current_attempt_count"], 1)
        self.assertEqual(res_resume_human["next_attempt_count"], 1)
        self.assertEqual(res_resume_human["project_mutation"]["尝试次数"], "1")

        # 2. 中断的处理中行恢复：尝试次数保持为 2
        res_resume_running = validate_execution_start(
            {"外链ID": "valid.com", "状态": "处理中", "尝试次数": "2"},
            master,
            resume_same_attempt=True,
        )
        self.assertTrue(res_resume_running["eligible"])
        self.assertEqual(res_resume_running["next_attempt_count"], 2)

        # 3. 传入终态失败或待提交行使用 resume 模式：拒绝启动
        res_bad_status = validate_execution_start(
            {"外链ID": "valid.com", "状态": "待提交", "尝试次数": "0"},
            master,
            resume_same_attempt=True,
        )
        self.assertFalse(res_bad_status["eligible"])

    def test_validate_execution_start_resume_forbidden_on_uncertain_submit(self):
        """P0-Gate: 提交结果不确定风险严禁自动 resume，强制维持需人工"""
        from execution_state import validate_execution_start

        master = [{"外链ID": "valid.com", "平台域名": "valid.com", "基础状态": "候选", "提交入口": "https://valid.com/submit"}]

        uncertain_notes = [
            "已执行提交但结果不确定，避免重复提交",
            "提交结果不明确，待人工核实",
            "ambiguous post-submit state detected",
            "避免重复提交，需要人工确认",
        ]

        for note in uncertain_notes:
            project_row = {
                "外链ID": "valid.com",
                "状态": "需人工",
                "尝试次数": "1",
                "原因/备注": note,
            }
            res = validate_execution_start(project_row, master, resume_same_attempt=True)
            self.assertFalse(res["eligible"], f"Should reject resume for note: {note}")
            self.assertEqual(res["proposed_status"], "需人工")
            self.assertEqual(res["next_attempt_count"], 1)
            self.assertIn("提交结果不确定风险", res["reason"])

    def test_cli_validate_execution_start_resume_flag(self):
        """P0-Gate: browser_cli validate-execution-start 支持 --resume-same-attempt"""
        import subprocess
        import json

        cli_path = scripts_dir / "browser_cli.py"
        res = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "validate-execution-start",
                "--resume-same-attempt",
                "--project-row-json",
                json.dumps({"项目ID": "p1", "外链ID": "good.com", "状态": "需人工", "尝试次数": "1", "原因/备注": "等待邮箱验证"}),
                "--master-rows-json",
                json.dumps([{
                    "外链ID": "good.com",
                    "平台域名": "good.com",
                    "基础状态": "候选",
                    "提交入口": "https://good.com/submit",
                }]),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0)
        out = json.loads(res.stdout)
        self.assertTrue(out["ok"])
        self.assertTrue(out["eligible"])
        self.assertEqual(out["current_attempt_count"], 1)
        self.assertEqual(out["next_attempt_count"], 1)
        self.assertEqual(out["project_mutation"]["尝试次数"], "1")


class TestControlPlaneConfiguration(unittest.TestCase):
    """P1: configure-control-plane.py migration safety verification."""

    def test_configure_control_plane_migrate_requires_verified_worksheets(self):
        import tempfile
        import subprocess
        import json

        repo_root = Path(__file__).resolve().parents[3]
        script_path = repo_root / "scripts" / "configure-control-plane.py"

        with tempfile.TemporaryDirectory() as tmp_home:
            config_dir = Path(tmp_home) / ".backlink-autofill"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file = config_dir / "control-plane.json"

            legacy_data = {
                "schema_version": 1,
                "spreadsheet_id": "test_sheet_123",
                "master_sheet": "外链总表",
                "project_sheet": "项目外链管理",
                "default_batch_size": 100,
            }
            config_file.write_text(json.dumps(legacy_data), encoding="utf-8")

            # 1. 缺少 --verified-worksheets 必须拒绝
            proc_no_ws = subprocess.run(
                [sys.executable, str(script_path), "--home", tmp_home, "--migrate"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(proc_no_ws.returncode, 0)
            self.assertIn("--verified-worksheets is required", proc_no_ws.stderr)

            # 2. --verified-worksheets 中不包含 '外链管理' 必须拒绝
            proc_missing_target = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--home", tmp_home,
                    "--migrate",
                    "--verified-worksheets", "外链总表,黑名单视图",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(proc_missing_target.returncode, 0)
            self.assertIn("Target worksheet '外链管理' not found", proc_missing_target.stderr)

            # 3. 提供合规且包含 '外链管理' 的工作表列表，成功安全迁移
            proc_ok = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--home", tmp_home,
                    "--migrate",
                    "--verified-worksheets", "外链总表,外链管理,黑名单视图",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_ok.returncode, 0)
            migrated_data = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual(migrated_data["project_sheet"], "外链管理")
            self.assertEqual(migrated_data["spreadsheet_id"], "test_sheet_123")


if __name__ == "__main__":
    unittest.main()

