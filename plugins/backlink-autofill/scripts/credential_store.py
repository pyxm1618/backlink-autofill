#!/usr/bin/env python3
"""Local per-site credentials for disposable backlink-platform accounts.

Passwords created here are intentionally isolated from project data, checkpoints,
recipes, Sheets, and model-visible browser action JSON.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_PASSWORD_LENGTH = 24
_SYMBOLS = "!@#$%*-_+="


class CredentialStoreError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_domain(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CredentialStoreError("INVALID_CREDENTIAL_DOMAIN", "credential domain must be non-empty")
    raw = value.strip()
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    hostname = parsed.hostname
    if not hostname:
        raise CredentialStoreError("INVALID_CREDENTIAL_DOMAIN", "could not resolve credential domain")
    try:
        hostname = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise CredentialStoreError("INVALID_CREDENTIAL_DOMAIN", "invalid credential domain") from exc
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if not hostname or "/" in hostname or "\\" in hostname:
        raise CredentialStoreError("INVALID_CREDENTIAL_DOMAIN", "invalid credential domain")
    return hostname


def _ensure_root(root: Path) -> Path:
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError as exc:
        raise CredentialStoreError("CREDENTIAL_PERMISSIONS_FAILED", "could not secure credential directory") from exc
    return root


def _credential_path(root: Path, domain: str) -> Path:
    return _ensure_root(root) / f"{canonical_domain(domain)}.json"


def _generate_password(length: int = _PASSWORD_LENGTH) -> str:
    if length < 20:
        raise ValueError("generated site passwords must be at least 20 characters")
    chars = [
        secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ"),
        secrets.choice("abcdefghijkmnopqrstuvwxyz"),
        secrets.choice("23456789"),
        secrets.choice(_SYMBOLS),
    ]
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789" + _SYMBOLS
    chars.extend(secrets.choice(alphabet) for _ in range(length - len(chars)))
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
        path.chmod(0o600)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _load(path: Path, expected_domain: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CredentialStoreError("CREDENTIAL_READ_FAILED", "stored site credential is unreadable") from exc
    if payload.get("schema_version") != 1:
        raise CredentialStoreError("CREDENTIAL_SCHEMA_INVALID", "stored site credential schema is invalid")
    if canonical_domain(payload.get("domain", "")) != expected_domain:
        raise CredentialStoreError("CREDENTIAL_DOMAIN_MISMATCH", "stored credential domain mismatch")
    password = payload.get("password")
    if not isinstance(password, str) or len(password) < 20:
        raise CredentialStoreError("CREDENTIAL_PASSWORD_INVALID", "stored site password is invalid")
    try:
        path.chmod(0o600)
    except OSError as exc:
        raise CredentialStoreError("CREDENTIAL_PERMISSIONS_FAILED", "could not secure credential file") from exc
    return payload


def get_site_password(
    root: Path,
    domain: str,
    *,
    account: str | None = None,
    mode: str = "existing_only",
) -> str:
    """Return a site password without logging or serializing it to caller-visible output.

    `create_or_reuse` is for a confirmed new-account registration flow.
    `existing_only` is for login and must never invent a credential.
    """

    if mode not in {"create_or_reuse", "existing_only"}:
        raise CredentialStoreError("INVALID_CREDENTIAL_MODE", "unsupported site credential mode")
    if account is not None and (not isinstance(account, str) or not account.strip()):
        raise CredentialStoreError("INVALID_CREDENTIAL_ACCOUNT", "credential account must be a non-empty string")
    account = account.strip() if isinstance(account, str) else None

    normalized = canonical_domain(domain)
    path = _credential_path(root, normalized)
    if path.exists():
        payload = _load(path, normalized)
        stored_account = payload.get("account")
        if account and stored_account and account != stored_account:
            raise CredentialStoreError("CREDENTIAL_ACCOUNT_MISMATCH", "stored account does not match requested account")
        return payload["password"]

    if mode == "existing_only":
        raise CredentialStoreError("CREDENTIAL_NOT_FOUND", "no stored site credential exists for this domain")

    password = _generate_password()
    _atomic_write(
        path,
        {
            "schema_version": 1,
            "domain": normalized,
            "account": account,
            "password": password,
        },
    )
    return password
