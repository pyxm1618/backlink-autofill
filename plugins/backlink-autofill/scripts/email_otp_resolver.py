#!/usr/bin/env python3
"""Host-agnostic EMAIL_OTP Core Resolver and Candidate Normalization.

This module is deliberately independent of Playwright and specific Gmail API/MCP SDKs.
Host Agents (Codex or Antigravity) call their respective available mail tools,
normalize the retrieved messages into EmailMessage[], and pass them here.

This module owns:
- EmailVerificationRequest structure;
- EmailMessage universal schema;
- Per-candidate Protected Authentication exclusion;
- Universal Platform Identity Scoring (compatible with third-party ESPs);
- Deterministic high-confidence OTP extraction and ambiguity rejection.
"""

from __future__ import annotations

import email.utils
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EmailVerificationRequest:
    project_id: str
    backlink_id: str
    platform_domain: str
    platform_name: str
    registration_email: str
    blocker_started_at: float
    target_id: str
    expected_code_length: int | None = 6
    expected_code_kind: str = "numeric"  # "numeric" | "alphanumeric"
    email_context_hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "backlink_id": self.backlink_id,
            "platform_domain": self.platform_domain,
            "platform_name": self.platform_name,
            "registration_email": self.registration_email,
            "blocker_started_at": self.blocker_started_at,
            "target_id": self.target_id,
            "expected_code_length": self.expected_code_length,
            "expected_code_kind": self.expected_code_kind,
            "email_context_hints": list(self.email_context_hints),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EmailVerificationRequest:
        return cls(
            project_id=str(data["project_id"]),
            backlink_id=str(data["backlink_id"]),
            platform_domain=str(data["platform_domain"]),
            platform_name=str(data.get("platform_name") or data["platform_domain"]),
            registration_email=str(data["registration_email"]),
            blocker_started_at=float(data["blocker_started_at"]),
            target_id=str(data["target_id"]),
            expected_code_length=int(data["expected_code_length"]) if data.get("expected_code_length") else None,
            expected_code_kind=str(data.get("expected_code_kind") or "numeric"),
            email_context_hints=list(data.get("email_context_hints") or []),
        )


@dataclass
class EmailMessage:
    id: str
    sender: str
    recipient: str
    subject: str
    date_timestamp: float
    body_text: str
    snippet: str = ""


@dataclass
class EmailOtpResolution:
    status: str  # "RESOLVED" | "EMAIL_OTP_NOT_FOUND" | "EMAIL_OTP_AMBIGUOUS" | "PROTECTED_AUTH_VERIFICATION"
    code: str | None = None
    reason: str = ""
    matched_message_id: str | None = None
    action_required: str = ""


_PROTECTED_IDP_DOMAINS = (
    "accounts.google.com",
    "google.com",
    "github.com",
    "apple.com",
    "appleid.apple.com",
    "microsoft.com",
    "login.microsoftonline.com",
    "facebook.com",
    "x.com",
    "twitter.com",
    "auth0.com",
    "okta.com",
)

_PROTECTED_KEYWORDS = (
    "password reset",
    "reset your password",
    "reset password",
    "重置密码",
    "payment verification",
    "bank verification",
    "wire transfer",
    "credit card verification",
    "支付验证",
    "扣款验证",
    "account recovery",
    "security alert",
    "security notice",
    "安全提醒",
    "security code for your google account",
    "google verification code",
)


def is_protected_auth_email(msg: EmailMessage, req: EmailVerificationRequest) -> bool:
    """Per-candidate Protected Auth check.
    
    Identifies if a message represents primary IdP login, password reset,
    banking/payment, or account recovery. These must never be auto-filled.
    """
    sender_lower = (msg.sender or "").lower()
    subject_lower = (msg.subject or "").lower()
    body_lower = (msg.body_text or "").lower()

    # 1. 发件人来自受保护第三方 IdP
    for idp in _PROTECTED_IDP_DOMAINS:
        if f"@{idp}" in sender_lower or f"<{idp}>" in sender_lower or f".{idp}" in sender_lower:
            return True

    # 2. 标题或正文包含密码重置、支付或账号恢复关键词
    full_text = f"{subject_lower} {body_lower}"
    for kw in _PROTECTED_KEYWORDS:
        if kw in full_text:
            return True

    return False


def _parse_timestamp(raw: Any) -> float:
    if isinstance(raw, (int, float)):
        # If timestamp is in milliseconds (> 1e11), convert to seconds
        return float(raw / 1000.0) if raw > 1e11 else float(raw)
    if isinstance(raw, str):
        raw_str = raw.strip()
        if raw_str.isdigit():
            val = float(raw_str)
            return val / 1000.0 if val > 1e11 else val
        try:
            dt = email.utils.parsedate_to_datetime(raw_str)
            return dt.timestamp()
        except Exception:
            return 0.0
    return 0.0


def normalize_codex_gmail_messages(raw_data: Any) -> list[EmailMessage]:
    """Normalize structured output from Codex Gmail connected app/plugin into EmailMessage[]."""
    items = []
    if isinstance(raw_data, dict):
        items = raw_data.get("messages") or raw_data.get("data") or [raw_data]
    elif isinstance(raw_data, list):
        items = raw_data

    normalized: list[EmailMessage] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        msg_id = str(item.get("id") or item.get("messageId") or "")
        sender = str(item.get("from") or item.get("sender") or "")
        recipient = str(item.get("to") or item.get("recipient") or "")
        subject = str(item.get("subject") or "")
        date_raw = item.get("date") or item.get("internalDate") or item.get("timestamp")
        body = str(item.get("body") or item.get("content") or item.get("snippet") or "")
        snippet = str(item.get("snippet") or "")
        normalized.append(
            EmailMessage(
                id=msg_id,
                sender=sender,
                recipient=recipient,
                subject=subject,
                date_timestamp=_parse_timestamp(date_raw),
                body_text=body,
                snippet=snippet,
            )
        )
    return normalized


def normalize_antigravity_mcp_messages(raw_data: Any) -> list[EmailMessage]:
    """Normalize structured output from Antigravity Gmail MCP into EmailMessage[]."""
    items = []
    if isinstance(raw_data, dict):
        items = raw_data.get("messages") or raw_data.get("data") or [raw_data]
    elif isinstance(raw_data, list):
        items = raw_data

    normalized: list[EmailMessage] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        msg_id = str(item.get("ID") or item.get("id") or item.get("messageId") or "")
        sender = str(item.get("From") or item.get("from") or item.get("sender") or "")
        recipient = str(item.get("To") or item.get("to") or item.get("recipient") or "")
        subject = str(item.get("Subject") or item.get("subject") or "")
        date_raw = item.get("DateTimestamp") or item.get("Date") or item.get("date") or item.get("internalDate")
        body = str(item.get("Body") or item.get("body") or item.get("Snippet") or item.get("snippet") or "")
        snippet = str(item.get("Snippet") or item.get("snippet") or "")
        normalized.append(
            EmailMessage(
                id=msg_id,
                sender=sender,
                recipient=recipient,
                subject=subject,
                date_timestamp=_parse_timestamp(date_raw),
                body_text=body,
                snippet=snippet,
            )
        )
    return normalized


def _extract_otp_code(text: str, length: int | None, kind: str) -> str | None:
    """Extract code matching length and kind constraints."""
    target_length = length or 6
    if kind == "numeric":
        # 优先匹配明确的验证码上下文 pattern，如 "code: 123456", "code is 123456"
        context_patterns = [
            rf"(?i)(?:verification\s*code|security\s*code|one-time\s*code|code\s*(?:is|:|\-)?)\s*[:\s]*\b([0-9]{{{target_length}}})\b",
            rf"\b([0-9]{{{target_length}}})\b",
        ]
        for pat in context_patterns:
            matches = re.findall(pat, text)
            if matches:
                return matches[0]
    else:  # alphanumeric
        context_patterns = [
            rf"(?i)(?:verification\s*code|security\s*code|code\s*(?:is|:|\-)?)\s*[:\s]*\b([A-Za-z0-9]{{{target_length}}})\b",
            rf"\b([A-Za-z0-9]{{{target_length}}})\b",
        ]
        for pat in context_patterns:
            matches = re.findall(pat, text)
            if matches:
                return matches[0]
    return None


def _score_candidate(msg: EmailMessage, req: EmailVerificationRequest) -> tuple[float, str | None]:
    """Score candidate email based on recipient, timing, platform identity and context."""
    score = 0.0

    # 1. Recipient check: must match registration email
    if req.registration_email.lower() not in (msg.recipient or "").lower():
        return 0.0, None

    # 2. Timing check: within [-180s, +900s] of blocker_started_at
    time_diff = msg.date_timestamp - req.blocker_started_at
    if -180.0 <= time_diff <= 900.0:
        score += 25.0
    elif -300.0 <= time_diff <= 1800.0:
        score += 10.0
    else:
        return 0.0, None

    sender_lower = (msg.sender or "").lower()
    subject_lower = (msg.subject or "").lower()
    body_lower = (msg.body_text or "").lower()
    full_text = f"{subject_lower} {body_lower}"

    platform_domain = req.platform_domain.lower()
    platform_name = req.platform_name.lower()

    # 3. Platform Identity Scoring (supports 3rd-party ESPs like Resend/Postmark/SendGrid)
    has_platform_identity = False
    if platform_domain in sender_lower:
        score += 40.0
        has_platform_identity = True
    elif platform_name in sender_lower:
        score += 30.0
        has_platform_identity = True

    if platform_name in subject_lower:
        score += 20.0
        has_platform_identity = True

    if platform_domain in full_text:
        score += 20.0
        has_platform_identity = True

    if not has_platform_identity:
        return 0.0, None

    # 4. Verification Context
    verification_cues = ("verify", "verification", "confirm", "confirmation", "code", "one-time", "otp")
    if any(cue in full_text for cue in verification_cues):
        score += 15.0

    # 5. Extract OTP
    code = _extract_otp_code(f"{msg.subject}\n{msg.body_text}", req.expected_code_length, req.expected_code_kind)
    if code:
        score += 20.0
    else:
        return 0.0, None

    return score, code


def resolve_email_otp_from_messages(
    request: EmailVerificationRequest,
    messages: list[EmailMessage],
) -> EmailOtpResolution:
    """Universal Core Resolver.
    
    1. Excludes protected authentication candidates per-candidate.
    2. Scores remaining candidates using universal platform identity scoring.
    3. Requires a unique high-confidence candidate; otherwise returns NEEDS_HUMAN.
    """
    if not messages:
        return EmailOtpResolution(
            status="EMAIL_OTP_NOT_FOUND",
            reason="No messages provided or inbox empty",
            action_required="NEEDS_HUMAN",
        )

    # 1. 逐候选排除 Protected Auth
    valid_candidates: list[EmailMessage] = []
    for msg in messages:
        if not is_protected_auth_email(msg, request):
            valid_candidates.append(msg)

    if not valid_candidates:
        return EmailOtpResolution(
            status="EMAIL_OTP_NOT_FOUND",
            reason="All candidate emails were protected authentication alerts or irrelevant",
            action_required="NEEDS_HUMAN",
        )

    # 2. 评分与匹配
    scored_candidates: list[tuple[float, str, EmailMessage]] = []
    for msg in valid_candidates:
        score, code = _score_candidate(msg, request)
        if score >= 60.0 and code:
            scored_candidates.append((score, code, msg))

    if not scored_candidates:
        return EmailOtpResolution(
            status="EMAIL_OTP_NOT_FOUND",
            reason="No verified email matched platform identity and verification constraints",
            action_required="NEEDS_HUMAN",
        )

    # 按时间降序及分数降序排序
    scored_candidates.sort(key=lambda item: (item[0], item[2].date_timestamp), reverse=True)

    # 3. 唯一性判断
    if len(scored_candidates) == 1:
        best_score, best_code, best_msg = scored_candidates[0]
        return EmailOtpResolution(
            status="RESOLVED",
            code=best_code,
            matched_message_id=best_msg.id,
            reason=f"Unique high-confidence candidate matched (score={best_score})",
        )

    # 若有多封候选，检查是否包含不同的 code
    distinct_codes = {c[1] for c in scored_candidates}
    if len(distinct_codes) > 1:
        return EmailOtpResolution(
            status="EMAIL_OTP_AMBIGUOUS",
            reason=f"Multiple ambiguous candidates found with conflicting codes: {len(distinct_codes)} variants",
            action_required="NEEDS_HUMAN",
        )

    # 如果代码相同且都来自同一平台，取最新的一封
    best_score, best_code, best_msg = scored_candidates[0]
    return EmailOtpResolution(
        status="RESOLVED",
        code=best_code,
        matched_message_id=best_msg.id,
        reason=f"Resolved latest of multiple consistent candidates (score={best_score})",
    )
