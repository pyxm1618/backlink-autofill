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


if __name__ == "__main__":
    unittest.main()

