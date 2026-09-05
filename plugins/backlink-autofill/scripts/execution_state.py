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
