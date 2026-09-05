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


if __name__ == "__main__":
    unittest.main()
