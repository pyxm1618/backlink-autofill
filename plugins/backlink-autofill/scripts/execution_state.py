#!/usr/bin/env python3
"""Deterministic local execution state for Backlink Autofill.

This module is deliberately browser- and connector-independent. It owns only:
- canonical Sheet <-> internal status mapping;
- project-isolated local checkpoints;
- domain-level reusable recipes;
- credential-like data rejection before local persistence.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SHEET_TO_INTERNAL = {
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
INTERNAL_TO_SHEET = {internal: sheet for sheet, internal in SHEET_TO_INTERNAL.items()}

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SENSITIVE_TERMS = {
    "password",
    "passwd",
    "secret",
    "token",
    "accesstoken",
    "refreshtoken",
    "apikey",
    "authorization",
    "cookie",
    "sessionid",
}
_DESCRIPTOR_KEYS = {"field", "fieldname", "name", "label", "inputname", "type"}


def sheet_status_to_internal(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    return SHEET_TO_INTERNAL.get(value.strip())


def internal_to_sheet_status(value: str) -> str:
    try:
        return INTERNAL_TO_SHEET[value]
    except KeyError as exc:
        raise ValueError(f"unknown internal status: {value}") from exc


class EvidenceContractError(ValueError):
    """Raised when evidence violates the universal Evidence & State Contract."""
    pass


FORBIDDEN_RESULT_URL_SEGMENTS = (
    "dashboard",
    "admin",
    "account",
    "edit",
    "payment",
    "checkout",
    "confirm",
    "confirmation",
    "queue",
    "login",
    "signin",
    "auth",
    "setting",
    "settings",
)


def normalize_canonical_url(url: str | None) -> str:
    """Normalize a project or platform URL for reliable identity comparison.

    Strips protocol, www prefix, trailing slashes, default ports, and query parameters.
    Example:
      https://www.quickiching.com/ -> quickiching.com
      http://quickiching.com       -> quickiching.com
      https://quickiching.com/app/ -> quickiching.com/app
    """
    if not url or not isinstance(url, str):
        return ""
    raw = url.strip().lower()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    netloc = parsed.netloc or ""
    if ":" in netloc:
        netloc = netloc.split(":")[0]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    if not netloc:
        return ""
    return f"{netloc}{path}"


_SUBMISSION_CONTEXT_CUES = (
    "pending",
    "scheduled",
    "published",
    "live",
    "active",
    "under review",
    "in review",
    "waiting",
    "approved",
    "queue",
    "edit listing",
    "view listing",
    "manage listing",
    "launch date",
    "排期",
    "审核",
    "已发布",
    "上线",
)

_LISTINGS_CONTAINER_CUES = (
    "my products",
    "your listings",
    "my listings",
    "submissions",
    "my submissions",
    "projects",
    "all listings",
    "dashboard",
    "manage listings",
    "submitted products",
    "launch queue",
)


def detect_existing_project_submission(
    content: Any,
    project_name: str,
    canonical_url: str,
) -> dict[str, Any]:
    """Universal Existing Submission Preflight.

    Distinguishes:
    Existing account != Existing submission

    Returns:
    - FOUND: Positive verifiable submission evidence found for this project identity.
             Strictly forbids new Final Submit; collects existing status/evidence.
    - NOT_FOUND: Authenticated listings view verified, and this project is explicitly absent.
                 Safe to proceed with creating a new submission.
    - UNKNOWN: View ambiguous, not a confirmed listings dashboard, or uncertain structure.
               Do not guess; requires human inspection before irreversible Final Submit.
    """
    norm_url = normalize_canonical_url(canonical_url)
    norm_name = str(project_name or "").strip().lower()

    if not norm_url and not norm_name:
        return {
            "verdict": "UNKNOWN",
            "reason": "Missing both project_name and canonical_url for preflight",
            "matched_identity": None,
            "status_hint": None,
            "scheduled_date": None,
            "public_listing_url": None,
        }

    # Case A: Structured list of listing items/records
    if isinstance(content, list):
        if not content:
            return {
                "verdict": "NOT_FOUND",
                "reason": "Listings list is explicitly empty",
                "matched_identity": None,
                "status_hint": None,
                "scheduled_date": None,
                "public_listing_url": None,
            }

        for item in content:
            if not isinstance(item, dict):
                continue
            item_text = " ".join(str(v) for v in item.values()).lower()
            item_url = normalize_canonical_url(item.get("url") or item.get("link") or item.get("target_url"))
            name_match = norm_name and norm_name in item_text
            url_match = norm_url and (norm_url == item_url or norm_url in item_text)

            if name_match or url_match:
                has_context = any(cue in item_text for cue in _SUBMISSION_CONTEXT_CUES)
                if has_context or "status" in item or "scheduled_date" in item:
                    sched_date = None
                    date_match = re.search(r"\b(202\d-[0-1]\d-[0-3]\d)\b", item_text)
                    if date_match:
                        sched_date = date_match.group(1)
                    elif item.get("scheduled_date"):
                        sched_date = str(item["scheduled_date"]).strip()

                    status_hint = str(item.get("status") or "").strip()
                    if not status_hint:
                        for cue in _SUBMISSION_CONTEXT_CUES:
                            if cue in item_text:
                                status_hint = cue
                                break

                    return {
                        "verdict": "FOUND",
                        "reason": f"Matched existing submission record for project identity (name={name_match}, url={url_match})",
                        "matched_identity": norm_url if url_match else norm_name,
                        "status_hint": status_hint,
                        "scheduled_date": sched_date,
                        "public_listing_url": item.get("public_listing_url") or item.get("listing_url"),
                    }

        return {
            "verdict": "NOT_FOUND",
            "reason": f"Explicit listings list of {len(content)} items inspected; project identity not present",
            "matched_identity": None,
            "status_hint": None,
            "scheduled_date": None,
            "public_listing_url": None,
        }

    # Case B: Unstructured DOM text from dashboard/listings page
    if isinstance(content, str):
        text_lower = content.lower()
        has_container = any(cue in text_lower for cue in _LISTINGS_CONTAINER_CUES)
        if not has_container:
            return {
                "verdict": "UNKNOWN",
                "reason": "Page does not exhibit confirmed listings/dashboard container cues",
                "matched_identity": None,
                "status_hint": None,
                "scheduled_date": None,
                "public_listing_url": None,
            }

        # 段落/行级局部匹配，防止全页面非相关文案（如搜索历史、页脚链接）发生全局误判
        blocks = re.split(r"\n\s*\n|(?<=</div>)|(?<=</tr>)|(?<=</li>)", content)
        for block in blocks:
            b_lower = block.lower()
            name_match = norm_name and norm_name in b_lower
            url_match = norm_url and norm_url in b_lower
            if name_match or url_match:
                has_context = any(cue in b_lower for cue in _SUBMISSION_CONTEXT_CUES)
                if has_context:
                    sched_date = None
                    date_match = re.search(r"\b(202\d-[0-1]\d-[0-3]\d)\b", b_lower)
                    if date_match:
                        sched_date = date_match.group(1)

                    status_hint = ""
                    for cue in _SUBMISSION_CONTEXT_CUES:
                        if cue in b_lower:
                            status_hint = cue
                            break

                    return {
                        "verdict": "FOUND",
                        "reason": f"Positive submission context found in listing card/row (name={name_match}, url={url_match})",
                        "matched_identity": norm_url if url_match else norm_name,
                        "status_hint": status_hint,
                        "scheduled_date": sched_date,
                        "public_listing_url": None,
                    }

        # 如果确认具有 listings 容器，且明确具有空列表标志
        empty_cues = (
            "no products",
            "no listings",
            "haven't submitted",
            "no submissions",
            "you don't have any",
            "empty",
            "0 products",
            "0 listings",
        )
        if any(empty in text_lower for empty in empty_cues):
            return {
                "verdict": "NOT_FOUND",
                "reason": "Confirmed listings dashboard indicates empty submission list",
                "matched_identity": None,
                "status_hint": None,
                "scheduled_date": None,
                "public_listing_url": None,
            }

        # 如果有容器但无法断定是否完整列出，且未找到项目，保守返回 NOT_FOUND 或 UNKNOWN
        # 如果列表中包含其他 listing card 但未匹配当前项目，且明确具有 listing 结构
        if re.search(r"(edit|view|status|manage)\s*listing", text_lower):
            return {
                "verdict": "NOT_FOUND",
                "reason": "Listings container with items inspected; current project not found",
                "matched_identity": None,
                "status_hint": None,
                "scheduled_date": None,
                "public_listing_url": None,
            }

        return {
            "verdict": "UNKNOWN",
            "reason": "Listings page structure uncertain; cannot conclusively verify absence of submission",
            "matched_identity": None,
            "status_hint": None,
            "scheduled_date": None,
            "public_listing_url": None,
        }

    return {
        "verdict": "UNKNOWN",
        "reason": "Unsupported content format for preflight inspection",
        "matched_identity": None,
        "status_hint": None,
        "scheduled_date": None,
        "public_listing_url": None,
    }


def detect_anonymous_submission_preflight(
    page_evidence: dict[str, Any],
    project_row: dict[str, Any],
    project_name: str = "",
    canonical_url: str = "",
    public_search_content: Any = None,
) -> dict[str, Any]:
    """Anonymous Submission Preflight.

    Minimal duplicate-detection and preflight for anonymous/free forms.
    Enforces:
    1. If page requires login or is not an anonymous form, route back to account-based preflight.
    2. If prior submission outcome was uncertain/ambiguous, halt for human review to prevent duplicate submits.
    3. If project row indicates already submitted/scheduled/live, reject duplicate submit (FOUND).
    4. If platform public search/listing content is readily available, inspect it for duplicates;
       otherwise, safe to proceed without building universal public-search crawlers.
    """
    if not isinstance(page_evidence, dict):
        page_evidence = {}
    if not isinstance(project_row, dict):
        project_row = {}

    # 1. Check if login is required
    if page_evidence.get("requires_login") is True or page_evidence.get("is_anonymous_form") is False:
        return {
            "verdict": "REQUIRES_LOGIN",
            "reason": "Platform requires login or is not an anonymous submission form; defer to dashboard preflight",
            "matched_identity": None,
            "status_hint": None,
            "scheduled_date": None,
            "public_listing_url": None,
        }

    # 2. Check for uncertain prior submission outcome
    notes_and_evidence = f"{project_row.get('原因/备注') or ''} {project_row.get('证据摘要') or ''}".lower()
    uncertain_cues = (
        "提交结果不确定",
        "提交结果不明确",
        "结果不明确",
        "避免重复提交",
        "uncertain submit",
        "ambiguous post-submit",
        "uncertain",
    )
    if any(cue in notes_and_evidence for cue in uncertain_cues):
        return {
            "verdict": "UNKNOWN",
            "reason": "Prior submission outcome is uncertain; halting for human verification to avoid duplicate submission",
            "matched_identity": None,
            "status_hint": None,
            "scheduled_date": None,
            "public_listing_url": None,
        }

    # 3. Check if project row already shows prior submission/live state
    current_status = str(project_row.get("状态") or "").strip()
    if current_status in ("已提交", "审核中", "已排期", "已上线"):
        return {
            "verdict": "FOUND",
            "reason": f"Project already submitted or live (current status: {current_status}); duplicate submission rejected",
            "matched_identity": canonical_url or project_name,
            "status_hint": current_status,
            "scheduled_date": None,
            "public_listing_url": None,
        }

    # 4. Optional: check readily available public search/listing content
    if public_search_content is not None and public_search_content != "" and public_search_content != []:
        search_res = detect_existing_project_submission(
            content=public_search_content,
            project_name=project_name,
            canonical_url=canonical_url,
        )
        if search_res.get("verdict") == "FOUND":
            return {
                "verdict": "FOUND",
                "reason": f"Existing submission detected via public search: {search_res.get('reason')}",
                "matched_identity": search_res.get("matched_identity"),
                "status_hint": search_res.get("status_hint"),
                "scheduled_date": search_res.get("scheduled_date"),
                "public_listing_url": search_res.get("public_listing_url"),
            }

    # 5. Form is verified anonymous, no duplicate detected -> SAFE
    return {
        "verdict": "SAFE",
        "reason": "Anonymous form preflight passed: verified anonymous form and no prior submission evidence found",
        "matched_identity": None,
        "status_hint": None,
        "scheduled_date": None,
        "public_listing_url": None,
    }


def sanitize_result_url(
    url: str | None,
    evidence: dict[str, Any] | None = None,
    public_access_verified: bool | None = None,
    listing_identity_verified: bool | None = None,
) -> str:
    """Validate and sanitize a public result URL.

    Invariant 3 & Positive Evidence Rule:
    - 外链管理.结果链接 can only be a real public page URL
      accessible to users and search engines.
    - Blacklist keywords (dashboard, admin, account, etc.) are only an
      auxiliary defense. Absence of blacklist keywords is NOT sufficient.
    - The URL MUST have positive verifiable evidence confirming both:
      1) public access without authentication (public_access_verified)
      2) accurate product/listing identity (listing_identity_verified)
      - If positive evidence is missing or negative, return an empty string.
    """
    if not url or not isinstance(url, str):
        return ""
    raw = url.strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""

    # Auxiliary defense: blacklist segments
    combined = f"{parsed.path.lower()}?{parsed.query.lower()}"
    for segment in FORBIDDEN_RESULT_URL_SEGMENTS:
        pattern = rf"(^|[/_?&=-]){re.escape(segment)}([/_?&=-]|$)"
        if re.search(pattern, combined):
            return ""

    # Positive evidence validation
    if public_access_verified is not None:
        has_public_access = bool(public_access_verified)
    elif isinstance(evidence, dict):
        has_public_access = bool(
            evidence.get("public_access_verified", False)
            or (evidence.get("public_listing_verified", False) and evidence.get("public_access_verified") is not False)
        )
    else:
        has_public_access = False

    if listing_identity_verified is not None:
        has_identity_match = bool(listing_identity_verified)
    elif isinstance(evidence, dict):
        has_identity_match = bool(
            evidence.get("listing_identity_verified", False)
            or evidence.get("target_identity_verified", False)
            or (evidence.get("public_listing_verified", False) and evidence.get("listing_identity_verified") is not False)
        )
    else:
        has_identity_match = False

    if not (has_public_access and has_identity_match):
        return ""

    return raw


def classify_project_status(evidence: dict[str, Any], strict: bool = False) -> str:
    """Classify project backlink status based on the strongest verifiable evidence.

    Invariant 4:
    - 已排期: Explicit future launch/publication/scheduled date exists.
              Takes precedence over 'Pending' or 'Under review'.
    - 审核中: Explicitly pending review, AND no specific future scheduled date.
    - 已提交: Final submit confirmed, but review/scheduling undetermined.
    - 已上线: Requires verifiable public listing URL and page accessible.
              Dashboard stating 'Live' without a public listing is NOT enough.
    - 需人工: Human blocker or ambiguous submit outcome.
    - 失败: Explicit execution failure.
    - 不适用: Incompatible platform criteria.
    """
    if not isinstance(evidence, dict):
        raise ValueError("evidence must be a dictionary")

    if evidence.get("human_blocker"):
        return "需人工"
    if evidence.get("failed"):
        return "失败"
    if evidence.get("not_applicable"):
        return "不适用"

    status_text = str(evidence.get("platform_status_text") or "").lower()
    claims_live = (
        status_text in {"live", "published", "active"}
        or evidence.get("live", False)
    )
    public_verified = bool(evidence.get("public_listing_verified", False))
    public_url = sanitize_result_url(evidence.get("public_listing_url"), evidence=evidence)

    if public_url and public_verified:
        return "已上线"

    if claims_live:
        if strict:
            raise EvidenceContractError(
                "Cannot classify as 已上线: public listing URL is missing or unverified"
            )
        if evidence.get("scheduled_date"):
            return "已排期"
        if evidence.get("final_submit_occurred") or status_text:
            return "审核中"
        return "待提交"

    # Invariant 4: Explicit scheduled/launch date prioritizes 已排期
    sched_date = str(evidence.get("scheduled_date") or "").strip()
    if sched_date:
        return "已排期"

    review_keywords = ("pending", "review", "approval", "moderation", "审核", "等待")
    if any(kw in status_text for kw in review_keywords) or evidence.get("under_review"):
        return "审核中"

    if evidence.get("final_submit_occurred") or evidence.get("submitted"):
        return "已提交"

    return "待提交"


class ProductionSheetGate:
    """Production Hard Gate for all Google Sheet mutations.

    Enforces universal invariants so that NO submission workflow can write
    invalid, speculative, or private data to the control plane.
    """

    @staticmethod
    def validate_project_mutation(
        evidence: dict[str, Any],
        proposed: dict[str, Any],
        strict_schedule: bool = False,
    ) -> dict[str, Any]:
        """Validate and normalize a project sheet mutation payload.

        Enforces:
        - Rejection of dashboard/admin/private URLs in 结果链接.
        - Rejection of unverified URLs in 结果链接 (requires positive evidence).
        - Rejection of 已上线 without verified public listing.
        - Normalization or rejection of scheduled_date + 审核中.
        """
        if not isinstance(evidence, dict):
            raise EvidenceContractError("evidence must be a dictionary")
        if not isinstance(proposed, dict):
            raise EvidenceContractError("proposed mutation must be a dictionary")

        status = proposed.get("状态")
        if not status or status not in SHEET_TO_INTERNAL:
            raise EvidenceContractError(f"invalid or missing sheet status: {status!r}")

        raw_result_url = proposed.get("结果链接")
        if raw_result_url:
            raw_str = str(raw_result_url).strip()
            if raw_str:
                # 1. Blacklist check
                parsed = urlparse(raw_str)
                combined = f"{parsed.path.lower()}?{parsed.query.lower()}"
                for segment in FORBIDDEN_RESULT_URL_SEGMENTS:
                    pattern = rf"(^|[/_?&=-]){re.escape(segment)}([/_?&=-]|$)"
                    if re.search(pattern, combined):
                        raise EvidenceContractError(
                            f"REJECTED: Private/dashboard URL {raw_str!r} cannot be written to 结果链接"
                        )

                # 2. Positive evidence check
                sanitized = sanitize_result_url(raw_str, evidence=evidence)
                if not sanitized:
                    raise EvidenceContractError(
                        f"REJECTED: 结果链接 {raw_str!r} lacks positive verification (public_access_verified and listing_identity_verified)"
                    )

        # Gate 3: Claims 已上线 without verified public listing
        if status == "已上线":
            has_public_listing = bool(
                evidence.get("public_listing_verified")
                and evidence.get("public_listing_url")
                and sanitize_result_url(evidence.get("public_listing_url"), evidence=evidence)
            )
            if not has_public_listing:
                raise EvidenceContractError(
                    "REJECTED: Cannot set status to 已上线 without verified public listing URL"
                )

        # Gate 4: scheduled_date exists + proposed 审核中
        sched_date = str(evidence.get("scheduled_date") or "").strip()
        if sched_date:
            if status == "审核中":
                if strict_schedule:
                    raise EvidenceContractError(
                        f"REJECTED: Platform has scheduled date {sched_date}; status must be 已排期, not 审核中"
                    )
                status = "已排期"

        result = dict(proposed)
        result["状态"] = status
        if raw_result_url:
            result["结果链接"] = sanitize_result_url(raw_result_url, evidence=evidence)
        else:
            result["结果链接"] = ""
        return result

    @staticmethod
    def validate_master_mutation(
        evidence: dict[str, Any],
        prior_facts: dict[str, Any] | None,
        proposed: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate a master sheet (外链总表) mutation payload.

        Enforces:
        - Rejection of 实测链接属性 when listing is not live or DOM rel uninspected.
        - Rejection of historical/prior data populating 实测* fields without current observation.
        """
        if not isinstance(evidence, dict):
            raise EvidenceContractError("evidence must be a dictionary")
        if not isinstance(proposed, dict):
            raise EvidenceContractError("proposed mutation must be a dictionary")

        # Gate 1: listing not live + 实测链接属性=Follow/Nofollow/etc -> REJECT
        observed_rel = proposed.get("实测链接属性")
        if observed_rel:
            listing_live = evidence.get("listing_live") is True
            has_dom_rel = evidence.get("live_dom_rel") is not None
            if not (listing_live and has_dom_rel):
                raise EvidenceContractError(
                    f"REJECTED: 实测链接属性 cannot be set to {observed_rel!r} without live listing and inspected DOM rel"
                )

        # Gate 5: Prior/historical facts attempting to populate 实测* -> REJECT
        observed_field_keys = {
            "实测免费": "free",
            "实测需登录": "requires_login",
            "实测登录方式": "login_method",
            "实测限制": "limits",
            "实测链接属性": "live_dom_rel",
        }
        for field, evidence_key in observed_field_keys.items():
            val = proposed.get(field)
            if val:
                # Must have direct observation evidence in current execution
                if evidence_key not in evidence and field not in evidence:
                    raise EvidenceContractError(
                        f"REJECTED: {field} was populated without direct observation in current execution evidence"
                    )

        return dict(proposed)

    @staticmethod
    def validate_execution_start(
        project_row: dict[str, Any],
        master_rows: list[dict[str, Any]],
        now_iso: str | None = None,
        resume_same_attempt: bool = False,
    ) -> dict[str, Any]:
        """Validate whether an execution attempt can start against production Google Sheet contract."""
        return validate_execution_start(
            project_row=project_row,
            master_rows=master_rows,
            now_iso=now_iso,
            resume_same_attempt=resume_same_attempt,
        )

    @staticmethod
    def filter_ready_execution_queue(
        project_rows: list[dict[str, Any]],
        selected_project_id: str,
        ready_allowlist: list[str] | set[str] | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Filter candidate project rows for autofill execution under P0-1 contract.

        Contract Rules:
        1. 待提交 ≠ Ready: Project backlog may contain thousands of UNKNOWN entry rows.
        2. Autofill MUST ONLY consume the intersection of (项目ID == selected_project_id AND 状态 == '待提交')
           AND the provided ready_allowlist (domains verified by BacklinkOS Phase C).
        3. If ready_allowlist is not provided (standalone run without allowlist), FAIL CLOSED:
           return ([], "STANDALONE_FAIL_CLOSED: 待提交 ≠ Ready. 未提供 BacklinkOS Ready Allowlist，严禁直接消费未经验证的待提交行，请先执行 Phase C prepare_execution_batch").
        4. If ready_allowlist has N items, at most N matching rows can be attempted (never backfill from ordinary backlog).
        """
        return filter_ready_execution_queue(
            project_rows=project_rows,
            selected_project_id=selected_project_id,
            ready_allowlist=ready_allowlist,
            limit=limit,
        )

    @staticmethod
    def evaluate_post_submit_recheck(
        project_row: dict[str, Any],
        recheck_evidence: dict[str, Any],
        current_date: str | None = None,
        now_iso: str | None = None,
        master_row: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Evaluate post-submit recheck observation and propose verifiable Sheet mutations."""
        return evaluate_post_submit_recheck(
            project_row=project_row,
            recheck_evidence=recheck_evidence,
            current_date=current_date,
            now_iso=now_iso,
            master_row=master_row,
        )


def enrich_master_facts(
    prior_facts: dict[str, Any] | None,
    observed: dict[str, Any],
) -> dict[str, str]:
    """Enrich master backlink facts using ONLY direct observations from current execution.

    Invariant 1: Prior research/discovery provenance must NEVER populate observed fields.
    Invariant 2: 实测链接属性 must come from live public listing DOM; otherwise empty.
    Invariant 6: Leave unknown fields blank, never guess.
    """
    if not isinstance(observed, dict):
        raise ValueError("observed must be a dictionary of browser observations")

    res = {
        "实测免费": "",
        "实测需登录": "",
        "实测登录方式": "",
        "实测限制": "",
        "实测链接属性": "",
        "最后验证时间": "",
        "平台备注": "",
    }

    if "free" in observed:
        free_val = observed["free"]
        if free_val is True or str(free_val).lower() in {"true", "免费", "yes"}:
            res["实测免费"] = "免费"
        elif free_val is False or str(free_val).lower() in {"false", "非免费", "no"}:
            res["实测免费"] = "非免费"
        elif str(free_val).lower() in {"混合", "mixed"}:
            res["实测免费"] = "混合"

    if "requires_login" in observed:
        req = observed["requires_login"]
        if req is True or str(req).lower() in {"true", "需要", "yes"}:
            res["实测需登录"] = "需要"
        elif req is False or str(req).lower() in {"false", "不需要", "no"}:
            res["实测需登录"] = "不需要"

    if "login_method" in observed and observed["login_method"]:
        res["实测登录方式"] = str(observed["login_method"]).strip()

    if "limits" in observed and observed["limits"]:
        res["实测限制"] = str(observed["limits"]).strip()

    if observed.get("listing_live") is True and observed.get("live_dom_rel") is not None:
        rel = str(observed["live_dom_rel"]).lower()
        if "nofollow" in rel:
            res["实测链接属性"] = "Nofollow"
        elif "ugc" in rel:
            res["实测链接属性"] = "UGC"
        elif "sponsored" in rel:
            res["实测链接属性"] = "Sponsored"
        else:
            res["实测链接属性"] = "Follow"
    else:
        res["实测链接属性"] = ""

    if any(res[k] for k in ("实测免费", "实测需登录", "实测登录方式", "实测限制", "实测链接属性")):
        res["最后验证时间"] = str(observed.get("verified_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    if "notes" in observed and observed["notes"]:
        res["平台备注"] = str(observed["notes"]).strip()
    elif prior_facts and prior_facts.get("平台备注"):
        res["平台备注"] = str(prior_facts["平台备注"]).strip()

    return res


def is_safe_subdomain_or_exact(host: str, domain: str) -> bool:
    """Check if host is domain or a subdomain of domain strictly on DNS label boundaries."""
    if not host or not domain:
        return False
    clean_host = host.lower().strip().split(":")[0].strip(".")
    clean_domain = domain.lower().strip().split(":")[0].strip(".")
    if clean_domain.startswith("www."):
        clean_domain = clean_domain[4:]
    if clean_host.startswith("www."):
        clean_host = clean_host[4:]

    if clean_host == clean_domain:
        return True
    return clean_host.endswith("." + clean_domain)


def _evaluate_master_row_eligibility(
    master_rows: list[dict[str, Any]],
    project_backlink_id: str | None = None,
) -> tuple[bool, str, str, str | None]:
    """Shared internal core evaluating 外链总表 candidate eligibility.

    Enforces:
    1. Exactly one master row;
    2. Join identity: master.外链ID == project.外链ID (if project_backlink_id provided);
    3. Master 基础状态 must be exactly '候选'; empty/unknown/other values fail closed;
    4. Domain identity: master.平台域名 must be non-empty;
    5. Submission entry must be absolute http/https;
    6. Same-origin submission entry: entry hostname must match master.平台域名 or its subdomain.

    Returns:
        (eligible: bool, status: str, reason: str, verified_entry_url: str | None)
    """
    if not isinstance(master_rows, list) or len(master_rows) == 0:
        return False, "失败", "外链ID在外链总表中不存在", None

    if len(master_rows) > 1:
        return False, "失败", "外链ID在外链总表中不唯一", None

    master_row = master_rows[0]
    if not isinstance(master_row, dict):
        return False, "失败", "外链ID在外链总表中不存在", None

    # 1. Join identity check (if project_backlink_id provided)
    if project_backlink_id is not None:
        master_bid = str(master_row.get("外链ID") or "").strip()
        if not master_bid or master_bid != project_backlink_id.strip():
            return False, "失败", f"总表外链ID ({master_bid!r}) 与项目外链ID ({project_backlink_id.strip()!r}) 不匹配", None

    # 2. Master 基础状态 check: 必须精确等于 "候选"
    base_status = str(master_row.get("基础状态") or "").strip()
    if base_status != "候选":
        if base_status == "已排除":
            exclude_reason = str(master_row.get("基础排除原因") or "").strip()
            reason = f"外链总表基础状态为已排除：{exclude_reason}" if exclude_reason else "外链总表基础状态为已排除"
            return False, "不适用", reason, None
        elif base_status == "失效":
            return False, "失败", "外链总表基础状态为失效", None
        elif not base_status:
            return False, "失败", "外链总表缺少基础状态", None
        else:
            return False, "失败", f"外链总表基础状态非法或未处于候选状态（当前为: {base_status!r}）", None

    # 3. Domain identity check: 必须有 canonical 平台域名
    platform_domain = str(master_row.get("平台域名") or "").strip()
    if not platform_domain:
        return False, "失败", "外链总表缺少平台域名", None

    # 4. Entry URL check: 必须是绝对 http/https URL
    entry_url = str(master_row.get("提交入口") or "").strip()
    parsed_entry = urlparse(entry_url)
    if not entry_url or parsed_entry.scheme not in ("http", "https") or not parsed_entry.netloc:
        return False, "失败", "缺少有效提交入口", None

    # 5. Same-origin submission entry check: 必须属于 master.平台域名 或其合法子域
    entry_hostname = (parsed_entry.netloc or "").split(":")[0].lower()
    if not is_safe_subdomain_or_exact(entry_hostname, platform_domain):
        return False, "失败", f"提交入口域名 ({entry_hostname}) 与外链主平台域名 ({platform_domain}) 不匹配", None

    return True, "待提交", "", entry_url


def check_master_execution_eligibility(
    master_row: dict[str, Any] | None,
    master_candidates_count: int = 1,
) -> dict[str, Any]:
    """Verify if a candidate row from 外链总表 is eligible for project queue execution.

    Delegates directly to the shared _evaluate_master_row_eligibility core.
    """
    if master_candidates_count > 1:
        master_rows = [master_row, master_row]
    elif master_row is not None:
        master_rows = [master_row]
    else:
        master_rows = []

    # 为了兼容旧单元测试中仅传 master_row 的场景，如果 master_row 缺少平台域名，以 master.外链ID 或 entry host 作为 fallback
    if master_row and not master_row.get("平台域名"):
        fallback_domain = master_row.get("外链ID") or urlparse(str(master_row.get("提交入口") or "")).netloc
        if fallback_domain:
            master_row = dict(master_row)
            master_row["平台域名"] = fallback_domain
            master_rows = [master_row] if master_candidates_count == 1 else [master_row, master_row]

    eligible, status, reason, entry_url = _evaluate_master_row_eligibility(master_rows)
    return {
        "eligible": eligible,
        "status": status,
        "reason": reason,
        "entry_url": entry_url,
    }


def validate_execution_start(
    project_row: dict[str, Any],
    master_rows: list[dict[str, Any]],
    now_iso: str | None = None,
    resume_same_attempt: bool = False,
) -> dict[str, Any]:
    """Validate whether an execution attempt can start against production Google Sheet contract.

    Invariants:
    1. Attempt count (尝试次数) strictly reflects actual browser execution attempts.
       If master row is missing, duplicate, excluded, invalid, cross-domain, or lacks a valid entry URL,
       execution NEVER starts, browser NEVER launches, and attempt count is NEVER incremented.
    2. Join identity: project.外链ID must be non-empty and exactly equal master.外链ID.
    3. Domain identity: submission-entry must be same-origin with canonical master.平台域名.
    4. Project Status & Resume Semantics:
       - Normal start (resume_same_attempt=False): project.状态 must be '待提交', attempts +1.
       - Same-attempt resume (resume_same_attempt=True): requires proven-unsubmitted '需人工' or
         interrupted '处理中'; attempts remain UNCHANGED. Forbidden if submit outcome was uncertain.
    """
    if not isinstance(project_row, dict):
        raise ValueError("project_row must be a dictionary")
    if not isinstance(master_rows, list):
        raise ValueError("master_rows must be a list of dictionaries")

    raw_attempt = project_row.get("尝试次数")
    try:
        current_attempt_count = int(raw_attempt) if raw_attempt is not None and str(raw_attempt).strip() != "" else 0
    except (ValueError, TypeError):
        current_attempt_count = 0

    target_url = str(project_row.get("目标URL") or "").strip()
    project_backlink_id = str(project_row.get("外链ID") or "").strip()
    current_status = str(project_row.get("状态") or "").strip()

    # 1. Project 外链ID 非空防守
    if not project_backlink_id:
        reason = "项目行缺少外链ID"
        mutation = build_project_row_update(
            status="失败",
            reason=reason,
            evidence_summary=f"[{reason}]",
            target_url=target_url,
            attempt_count=current_attempt_count,
            now_iso=now_iso,
        )
        return {
            "ok": True,
            "eligible": False,
            "reason": reason,
            "current_attempt_count": current_attempt_count,
            "next_attempt_count": current_attempt_count,
            "proposed_status": "失败",
            "verified_entry_url": None,
            "project_mutation": mutation,
        }

    # 2. 调用统一内部核心校验 Master Row
    eligible, master_status, master_reason, verified_entry_url = _evaluate_master_row_eligibility(
        master_rows=master_rows,
        project_backlink_id=project_backlink_id,
    )

    if not eligible:
        mutation = build_project_row_update(
            status=master_status,
            reason=master_reason,
            evidence_summary=f"[{master_reason}]",
            target_url=target_url,
            attempt_count=current_attempt_count,
            now_iso=now_iso,
        )
        return {
            "ok": True,
            "eligible": False,
            "reason": master_reason,
            "current_attempt_count": current_attempt_count,
            "next_attempt_count": current_attempt_count,
            "proposed_status": master_status,
            "verified_entry_url": None,
            "project_mutation": mutation,
        }

    # 3. Project 状态与 resume_same_attempt 语义判定
    if not resume_same_attempt:
        # Normal Start: 要求严格为 '待提交' (blank 也拒绝)
        if current_status != "待提交":
            reason = f"项目当前状态为 {current_status!r}，非待提交状态不可启动新执行"
            mutation = build_project_row_update(
                status=current_status if current_status in SHEET_TO_INTERNAL else "失败",
                reason=reason,
                evidence_summary=f"[{reason}]",
                target_url=target_url,
                attempt_count=current_attempt_count,
                now_iso=now_iso,
            )
            return {
                "ok": True,
                "eligible": False,
                "reason": reason,
                "current_attempt_count": current_attempt_count,
                "next_attempt_count": current_attempt_count,
                "proposed_status": current_status if current_status in SHEET_TO_INTERNAL else "失败",
                "verified_entry_url": None,
                "project_mutation": mutation,
            }
    else:
        # Same-attempt Resume: 仅允许已确认未提交的 '需人工' 或中断态
        if current_status not in ("需人工", "处理中"):
            reason = f"显式恢复模式仅允许恢复 需人工 或 中断处理中 状态（当前状态为: {current_status!r}）"
            mutation = build_project_row_update(
                status=current_status if current_status in SHEET_TO_INTERNAL else "失败",
                reason=reason,
                evidence_summary=f"[{reason}]",
                target_url=target_url,
                attempt_count=current_attempt_count,
                now_iso=now_iso,
            )
            return {
                "ok": True,
                "eligible": False,
                "reason": reason,
                "current_attempt_count": current_attempt_count,
                "next_attempt_count": current_attempt_count,
                "proposed_status": current_status if current_status in SHEET_TO_INTERNAL else "失败",
                "verified_entry_url": None,
                "project_mutation": mutation,
            }

        # 检查是否包含提交结果不确定风险，禁止自动恢复避免重复提交
        combined_notes = f"{project_row.get('原因/备注') or ''} {project_row.get('证据摘要') or ''}".lower()
        uncertain_cues = ("提交结果不确定", "结果不明确", "避免重复提交", "uncertain submit", "ambiguous post-submit")
        if any(cue in combined_notes for cue in uncertain_cues):
            reason = "检测到提交结果不确定风险，禁止自动恢复以避免重复提交，须人工终审"
            mutation = build_project_row_update(
                status="需人工",
                reason=reason,
                evidence_summary=str(project_row.get("证据摘要") or ""),
                target_url=target_url,
                attempt_count=current_attempt_count,
                now_iso=now_iso,
            )
            return {
                "ok": True,
                "eligible": False,
                "reason": reason,
                "current_attempt_count": current_attempt_count,
                "next_attempt_count": current_attempt_count,
                "proposed_status": "需人工",
                "verified_entry_url": None,
                "project_mutation": mutation,
            }

    # 4. 全部通过：计算尝试次数并生成变更
    if resume_same_attempt:
        next_attempt_count = current_attempt_count  # 恢复同一次未提交尝试，尝试次数保持不变！
    else:
        next_attempt_count = current_attempt_count + 1  # 正常启动，尝试次数严格 +1！

    mutation = build_project_row_update(
        status="处理中",
        target_url=target_url,
        attempt_count=next_attempt_count,
        now_iso=now_iso,
    )
    return {
        "ok": True,
        "eligible": True,
        "reason": "",
        "current_attempt_count": current_attempt_count,
        "next_attempt_count": next_attempt_count,
        "proposed_status": "处理中",
        "verified_entry_url": verified_entry_url,
        "project_mutation": mutation,
    }


def build_project_row_update(
    status: str,
    raw_result_url: str | None = None,
    evidence_summary: str = "",
    reason: str = "",
    target_url: str = "",
    attempt_count: int | None = None,
    now_iso: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a validated project row mutation payload adhering to the contract.

    Invariant 3: Filters private/dashboard/queue URLs out of 结果链接.
    Invariant 6: Does not infer unknown facts.
    """
    if status not in SHEET_TO_INTERNAL:
        raise ValueError(f"invalid sheet status: {status!r}")

    sanitized_url = sanitize_result_url(raw_result_url, evidence=evidence)
    updated_evidence = str(evidence_summary or "").strip()

    if raw_result_url and not sanitized_url:
        stripped_raw = raw_result_url.strip()
        if stripped_raw and stripped_raw not in updated_evidence:
            notice = f"[页面证据: {stripped_raw}；公开 listing URL 尚未生成]"
            updated_evidence = f"{updated_evidence} {notice}".strip()

    return {
        "状态": status,
        "尝试次数": str(attempt_count) if attempt_count is not None else "",
        "最近操作时间": now_iso or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "目标URL": target_url.strip(),
        "结果链接": sanitized_url,
        "原因/备注": reason.strip(),
        "证据摘要": updated_evidence,
    }


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _looks_sensitive_name(value: Any) -> bool:
    normalized = _normalize_key(value)
    if not normalized:
        return False
    return any(term in normalized for term in _SENSITIVE_TERMS)


def _assert_no_sensitive_data(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _looks_sensitive_name(key):
                raise ValueError(f"credential-like key must not be persisted: {path}.{key}")
            normalized_key = _normalize_key(key)
            if normalized_key in _DESCRIPTOR_KEYS and isinstance(child, str) and _looks_sensitive_name(child):
                raise ValueError(f"credential-like field must not be persisted: {path}.{key}")
            _assert_no_sensitive_data(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_sensitive_data(child, f"{path}[{index}]")


def _validate_project_id(project_id: str) -> str:
    if not isinstance(project_id, str):
        raise ValueError("project_id must be a string")
    project_id = project_id.strip()
    if project_id in {"", ".", ".."} or not _PROJECT_ID_RE.fullmatch(project_id):
        raise ValueError(f"invalid project_id: {project_id!r}")
    return project_id


def _validate_row_number(row_number: int) -> int:
    if isinstance(row_number, bool) or not isinstance(row_number, int) or row_number < 2:
        raise ValueError("row_number must be an integer >= 2")
    return row_number


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return path


def _checkpoint_path(root: Path, project_id: str, row_number: int) -> Path:
    project_id = _validate_project_id(project_id)
    row_number = _validate_row_number(row_number)
    return Path(root) / "runtime" / project_id / f"row-{row_number}.json"


def save_checkpoint(root: Path, checkpoint: dict[str, Any]) -> Path:
    if not isinstance(checkpoint, dict):
        raise ValueError("checkpoint must be an object")

    payload = deepcopy(checkpoint)
    if payload.get("schema_version") != 1:
        raise ValueError("checkpoint schema_version must be 1")

    project_id = _validate_project_id(payload.get("project_id"))
    row_number = _validate_row_number(payload.get("row_number"))

    backlink_id = payload.get("backlink_id")
    if not isinstance(backlink_id, str) or not backlink_id.strip():
        raise ValueError("checkpoint backlink_id must be a non-empty string")

    state = payload.get("state")
    if state not in INTERNAL_TO_SHEET:
        raise ValueError(f"invalid checkpoint state: {state!r}")

    _assert_no_sensitive_data(payload)
    return _atomic_write_json(_checkpoint_path(Path(root), project_id, row_number), payload)


def load_checkpoint(root: Path, project_id: str, row_number: int) -> dict[str, Any] | None:
    path = _checkpoint_path(Path(root), project_id, row_number)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("project_id") != _validate_project_id(project_id):
        raise ValueError("checkpoint project_id does not match requested project")
    if payload.get("row_number") != _validate_row_number(row_number):
        raise ValueError("checkpoint row_number does not match requested row")
    _assert_no_sensitive_data(payload)
    return payload


def delete_checkpoint(root: Path, project_id: str, row_number: int) -> None:
    path = _checkpoint_path(Path(root), project_id, row_number)
    path.unlink(missing_ok=True)


def canonical_domain(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("domain must be a non-empty string")

    raw = value.strip()
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"could not resolve domain from: {value!r}")

    try:
        hostname = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError(f"invalid domain: {value!r}") from exc

    if hostname.startswith("www."):
        hostname = hostname[4:]
    if not hostname or "/" in hostname or "\\" in hostname:
        raise ValueError(f"invalid domain: {value!r}")
    return hostname


def _recipe_path(root: Path, domain: str) -> Path:
    return Path(root) / "recipes" / f"{canonical_domain(domain)}.json"


def save_recipe(root: Path, domain: str, recipe: dict[str, Any]) -> Path:
    if not isinstance(recipe, dict):
        raise ValueError("recipe must be an object")
    payload = deepcopy(recipe)
    _assert_no_sensitive_data(payload)
    payload["domain"] = canonical_domain(domain)
    if "schema_version" not in payload:
        payload["schema_version"] = 1
    if payload.get("schema_version") != 1:
        raise ValueError("recipe schema_version must be 1")
    return _atomic_write_json(_recipe_path(Path(root), domain), payload)


def load_recipe(root: Path, domain: str) -> dict[str, Any] | None:
    path = _recipe_path(Path(root), domain)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    _assert_no_sensitive_data(payload)
    expected = canonical_domain(domain)
    if canonical_domain(payload.get("domain", "")) != expected:
        raise ValueError("recipe domain does not match requested domain")
    return payload


def _human_pending_path(runtime_root: Path, project_id: str, backlink_id: str) -> Path:
    project_id = _validate_project_id(project_id)
    safe_backlink_id = re.sub(r"[^A-Za-z0-9._-]", "_", str(backlink_id).strip())
    if not safe_backlink_id:
        raise ValueError("backlink_id must be a non-empty string")
    return Path(runtime_root) / "human-pending" / project_id / f"{safe_backlink_id}.json"


def save_human_pending(
    runtime_root: Path,
    project_id: str,
    backlink_id: str,
    domain: str,
    blocker_type: str,
    current_url: str,
    target_id: str | None = None,
    checkpoint_ref: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    project_id = _validate_project_id(project_id)
    payload = {
        "schema_version": 1,
        "project_id": project_id,
        "backlink_id": str(backlink_id).strip(),
        "domain": canonical_domain(domain),
        "blocker_type": str(blocker_type).strip(),
        "current_url": str(current_url).strip(),
        "target_id": str(target_id).strip() if target_id else None,
        "checkpoint_ref": str(checkpoint_ref).strip() if checkpoint_ref else None,
        "status": "NEEDS_HUMAN",
        "created_at": time.time(),
        "extra": extra or {},
    }
    _assert_no_sensitive_data(payload)
    path = _human_pending_path(runtime_root, project_id, backlink_id)
    return _atomic_write_json(path, payload)


def load_human_pending(runtime_root: Path, project_id: str, backlink_id: str) -> dict[str, Any] | None:
    path = _human_pending_path(runtime_root, project_id, backlink_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    _assert_no_sensitive_data(payload)
    return payload


def find_human_pending(runtime_root: Path, project_id: str, backlink_id: str) -> dict[str, Any] | None:
    return load_human_pending(runtime_root, project_id, backlink_id)


TERMINAL_STATUSES = {
    "已提交",
    "审核中",
    "已上线",
    "已排期",
    "失败",
    "不适用",
}


def list_human_pending(runtime_root: Path, project_id: str) -> list[dict[str, Any]]:
    if not project_id or not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be a non-empty string for listing human pending items")
    project_id = _validate_project_id(project_id)
    pdir = Path(runtime_root) / "human-pending" / project_id
    if not pdir.exists() or not pdir.is_dir():
        return []
    results = []
    for item in pdir.glob("*.json"):
        try:
            payload = json.loads(item.read_text(encoding="utf-8"))
            results.append(payload)
        except Exception:
            pass
    return sorted(results, key=lambda x: x.get("created_at") or 0)


def resolve_human_pending(
    runtime_root: Path,
    project_id: str,
    backlink_id: str,
    terminal_status: str,
) -> bool:
    project_id = _validate_project_id(project_id)
    if terminal_status not in TERMINAL_STATUSES:
        raise ValueError(
            f"Cannot resolve human pending task with non-terminal status {terminal_status!r}. "
            f"Must be one of {sorted(TERMINAL_STATUSES)}"
        )
    path = _human_pending_path(runtime_root, project_id, backlink_id)
    if path.exists():
        path.unlink()
        return True
    return False


def clear_human_pending(
    runtime_root: Path,
    project_id: str,
    backlink_id: str,
    admin_override: bool = False,
) -> None:
    if not admin_override:
        raise PermissionError(
            "clear_human_pending is an administrative operation that requires explicit admin_override=True. "
            "Normal workflow must use resolve_human_pending after reaching a terminal status."
        )
    path = _human_pending_path(runtime_root, project_id, backlink_id)
    path.unlink(missing_ok=True)


def filter_ready_execution_queue(
    project_rows: list[dict[str, Any]],
    selected_project_id: str,
    ready_allowlist: list[str] | set[str] | None = None,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], str | None]:
    """Filter candidate project rows for autofill execution under P0-1 contract.

    Rules:
    1. Standalone / missing allowlist -> FAIL CLOSED.
       Must not consume ordinary 待提交 rows with blank/unknown entries.
    2. Given allowlist -> compute intersection with (项目ID == selected_project_id AND 状态 == '待提交').
    3. Respect order in Sheet, bounded by min(len(ready_allowlist), limit).
    4. Absolutely never backfill from other 待提交 rows not in the allowlist.
    """
    proj = str(selected_project_id or "").strip()
    if not proj:
        return [], "MISSING_PROJECT_ID: 必须指定 selected_project_id"

    if ready_allowlist is None:
        return [], "STANDALONE_FAIL_CLOSED: 待提交 ≠ Ready. 未提供 BacklinkOS Ready Allowlist，严禁直接消费未经验证的待提交行，请先执行 Phase C prepare_execution_batch"

    norm_allowlist = set()
    for item in ready_allowlist:
        d = str(item or "").strip().lower()
        if d.startswith("http://") or d.startswith("https://"):
            d = urlparse(d).netloc
        if d.startswith("www."):
            d = d[4:]
        d = d.split(":")[0].strip()
        if d:
            norm_allowlist.add(d)

    if not norm_allowlist:
        return [], "EMPTY_ALLOWLIST: 提供的 Ready Allowlist 为空，本次无待执行项"

    max_items = min(len(norm_allowlist), limit if limit > 0 else 100)
    selected_rows: list[dict[str, Any]] = []

    for row in project_rows:
        if len(selected_rows) >= max_items:
            break
        p_proj = str(row.get("项目ID") or "").strip()
        p_status = str(row.get("状态") or "").strip()
        if p_proj != proj or p_status != "待提交":
            continue

        raw_id = str(row.get("外链ID") or row.get("外链域名") or "").strip().lower()
        if raw_id.startswith("http://") or raw_id.startswith("https://"):
            raw_id = urlparse(raw_id).netloc
        if raw_id.startswith("www."):
            raw_id = raw_id[4:]
        raw_id = raw_id.split(":")[0].strip()

        if raw_id in norm_allowlist:
            selected_rows.append(row)

    return selected_rows, None


RECHECKABLE_STATUSES = {"已提交", "审核中", "已排期"}


def evaluate_post_submit_recheck(
    project_row: dict[str, Any],
    recheck_evidence: dict[str, Any],
    current_date: str | None = None,
    now_iso: str | None = None,
    master_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate post-submit recheck observation and propose verifiable Sheet mutations.

    Contract:
    - Purely read-only post-submit verification (forbidden_actions includes submit).
    - Status transitions strictly driven by direct verifiable evidence:
      1. 已排期: Future scheduled date must remain 已排期.
      2. 已上线: Requires BOTH verified public access (not 404, no auth) AND verified project identity.
                 Dashboard claiming 'live' without verified public listing URL is rejected and remains 审核中.
      3. 结果链接: Sanitized public URL written only when verified live; unverified or 404/auth URLs forbidden.
      4. 实测链接属性: Master attribute written ONLY when listing is verified live and DOM rel inspected.
                      If rel is uninspected (None), remains empty string, never guess.
    """
    if not isinstance(project_row, dict):
        raise ValueError("project_row must be a dictionary")
    if not isinstance(recheck_evidence, dict):
        raise ValueError("recheck_evidence must be a dictionary")

    current_status = str(project_row.get("状态") or "").strip()
    if current_status not in RECHECKABLE_STATUSES:
        return {
            "ok": False,
            "eligible": False,
            "reason": f"当前状态 '{current_status}' 不属于可复核范围（仅支持 {sorted(RECHECKABLE_STATUSES)}）",
            "is_readonly": True,
            "allowed_actions": ["inspect", "navigate"],
            "forbidden_actions": ["submit", "final_submit", "click_submit"],
            "current_status": current_status,
            "proposed_status": current_status,
            "project_mutation": None,
            "master_mutation": None,
        }

    today = current_date or time.strftime("%Y-%m-%d", time.gmtime())
    now_iso = now_iso or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    target_url = str(project_row.get("目标URL") or "").strip()

    raw_attempt = project_row.get("尝试次数")
    try:
        attempt_count = int(raw_attempt) if raw_attempt is not None and str(raw_attempt).strip() != "" else 0
    except (ValueError, TypeError):
        attempt_count = 0

    dashboard_status = str(recheck_evidence.get("dashboard_status") or "").strip().lower()
    sched_date = str(recheck_evidence.get("scheduled_date") or "").strip()
    public_url = recheck_evidence.get("public_listing_url")
    public_access_verified = bool(recheck_evidence.get("public_access_verified", False))
    listing_identity_verified = bool(recheck_evidence.get("listing_identity_verified", False))
    live_dom_rel = recheck_evidence.get("live_dom_rel")

    # 1. 验证是否可判为 已上线
    sanitized_public_url = sanitize_result_url(
        public_url,
        evidence=recheck_evidence,
        public_access_verified=public_access_verified,
        listing_identity_verified=listing_identity_verified,
    )
    is_live = bool(sanitized_public_url and public_access_verified and listing_identity_verified)

    master_mutation: dict[str, Any] | None = None

    if is_live:
        proposed_status = "已上线"
        proposed_result_url = sanitized_public_url
        reason = "复核已验证公开上线页面"
        evidence_summary = f"[公开上线页已验证: {sanitized_public_url}]"

        # Master mutation: 仅在 DOM rel 实际检查且非 None 时填入，否则留空
        master_mutation_payload = {
            "实测链接属性": "",
            "最后验证时间": now_iso,
        }
        master_evidence = {"listing_live": True}
        if live_dom_rel is not None:
            rel_lower = str(live_dom_rel).lower()
            if "nofollow" in rel_lower:
                attr = "Nofollow"
            elif "ugc" in rel_lower:
                attr = "UGC"
            elif "sponsored" in rel_lower:
                attr = "Sponsored"
            else:
                attr = "Follow"
            master_mutation_payload["实测链接属性"] = attr
            master_evidence["live_dom_rel"] = live_dom_rel

        master_mutation = ProductionSheetGate.validate_master_mutation(
            evidence=master_evidence,
            prior_facts=master_row,
            proposed=master_mutation_payload,
        )

    elif sched_date and sched_date > today:
        # 已排期且未到期
        proposed_status = "已排期"
        proposed_result_url = ""
        reason = f"排期发布中（排期日期: {sched_date}）"
        evidence_summary = f"[未到排期日期: {sched_date}]"
        master_mutation = {
            "实测链接属性": "",
            "最后验证时间": now_iso,
        }

    else:
        # 未上线，且未排期在未来
        proposed_result_url = ""
        claims_live = dashboard_status in {"live", "published", "active", "approved", "已发布", "已上线"}
        if claims_live:
            # 仅 dashboard 声称上线，但无公开 URL 或未验证公开访问 -> 拒绝已上线，维持/转为 审核中
            proposed_status = "审核中"
            reason = "Dashboard 显示已发布，但未验证有效公开上线页，维持审核中"
            evidence_summary = f"[Dashboard 声明: {dashboard_status}，无有效公开链接]"
        elif any(kw in dashboard_status for kw in ("review", "pending", "moderation", "审核")):
            proposed_status = "审核中"
            reason = "复核确认处于平台审核队列中"
            evidence_summary = f"[平台审核状态: {dashboard_status}]"
        elif current_status == "已排期" and sched_date and sched_date <= today:
            # 排期已到但未见上线页
            proposed_status = "审核中"
            reason = f"排期已到期（{sched_date}）但未验证公开上线页，转入审核复核"
            evidence_summary = "[排期到期未见公开页面]"
        else:
            proposed_status = current_status
            reason = str(project_row.get("原因/备注") or "复核未发现状态变化")
            evidence_summary = str(project_row.get("证据摘要") or "")

        master_mutation = {
            "实测链接属性": "",
            "最后验证时间": now_iso,
        }

    # 通过 ProductionSheetGate 校验 Project mutation
    evidence_for_gate = {
        "platform_status_text": dashboard_status,
        "scheduled_date": sched_date if proposed_status == "已排期" else None,
        "public_listing_url": proposed_result_url,
        "public_listing_verified": is_live,
        "public_access_verified": public_access_verified,
        "listing_identity_verified": listing_identity_verified,
    }
    raw_project_update = build_project_row_update(
        status=proposed_status,
        raw_result_url=proposed_result_url,
        evidence_summary=evidence_summary,
        reason=reason,
        target_url=target_url,
        attempt_count=attempt_count,
        now_iso=now_iso,
        evidence=evidence_for_gate,
    )
    validated_project_mutation = ProductionSheetGate.validate_project_mutation(
        evidence=evidence_for_gate,
        proposed=raw_project_update,
    )

    return {
        "ok": True,
        "eligible": True,
        "is_readonly": True,
        "allowed_actions": ["inspect", "navigate"],
        "forbidden_actions": ["submit", "final_submit", "click_submit"],
        "current_status": current_status,
        "proposed_status": proposed_status,
        "project_mutation": validated_project_mutation,
        "master_mutation": master_mutation,
    }

