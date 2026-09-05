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


def sanitize_result_url(
    url: str | None,
    evidence: dict[str, Any] | None = None,
    public_access_verified: bool | None = None,
    listing_identity_verified: bool | None = None,
) -> str:
    """Validate and sanitize a public result URL.

    Invariant 3 & Positive Evidence Rule:
    - 项目外链管理.结果链接 can only be a real public page URL
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


def build_project_row_update(
    status: str,
    raw_result_url: str | None = None,
    evidence_summary: str = "",
    reason: str = "",
    target_url: str = "",
    attempt_count: int | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Build a validated project row mutation payload adhering to the contract.

    Invariant 3: Filters private/dashboard/queue URLs out of 结果链接.
    Invariant 6: Does not infer unknown facts.
    """
    if status not in SHEET_TO_INTERNAL:
        raise ValueError(f"invalid sheet status: {status!r}")

    sanitized_url = sanitize_result_url(raw_result_url)
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
