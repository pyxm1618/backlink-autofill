#!/usr/bin/env python3
"""Real browser execution layer for Backlink Autofill.

The runtime is intentionally narrow and model-agnostic. It exposes compact page
state and executes an explicit action plan. It does not decide which backlink
should be submitted or invent any project content.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import BrowserContext, Locator, Page, Playwright, sync_playwright

from credential_store import CredentialStoreError, get_site_password

DEFAULT_CDP_URL = "http://127.0.0.1:9222"


def _probe_cdp(url: str, timeout: float = 0.5) -> dict | None:
    try:
        req_url = url.rstrip("/") + "/json/version"
        with urlopen(req_url, timeout=timeout) as resp:
            data = json.load(resp)
            return data if isinstance(data, dict) and data.get("Browser") else None
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return None

MAX_BODY_EXCERPT = 32000
MAX_ACTIONS = 100
_ALLOWED_ACTIONS = {"fill", "credential_fill", "select", "check", "upload", "click", "submit"}
_SENSITIVE_FIELD_TERMS = (
    "password",
    "passwd",
    "passcode",
    "secret",
    "access token",
    "api key",
    "apikey",
)


class BrowserRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


FORBIDDEN_CONTROL_PLANE_DOMAINS = (
    "docs.google.com",
    "drive.google.com",
    "sheets.google.com",
    "spreadsheets.google.com",
)


def _validate_http_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise BrowserRuntimeError("INVALID_URL", "URL must be a non-empty http(s) URL")
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BrowserRuntimeError("INVALID_URL", "Only absolute http(s) URLs are allowed")
    hostname = (parsed.hostname or "").lower()
    if any(hostname == d or hostname.endswith("." + d) for d in FORBIDDEN_CONTROL_PLANE_DOMAINS):
        raise BrowserRuntimeError(
            "CONTROL_PLANE_URL_FORBIDDEN",
            "Browser Runtime must not be used to navigate to or mutate Google Sheets/Drive control plane",
        )
    return url.strip()


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _field_descriptor(locator: Locator) -> dict[str, str]:
    return locator.evaluate(
        """
        (el) => {
          const labels = el.labels ? Array.from(el.labels).map(x => x.innerText || x.textContent || '') : [];
          const nested = el.closest('label');
          return {
            type: (el.getAttribute('type') || '').toLowerCase(),
            name: el.getAttribute('name') || '',
            id: el.id || '',
            autocomplete: el.getAttribute('autocomplete') || '',
            ariaLabel: el.getAttribute('aria-label') || '',
            label: labels.join(' ') || (nested ? (nested.innerText || nested.textContent || '') : '')
          };
        }
        """
    )


def _is_sensitive_field(locator: Locator) -> bool:
    descriptor = _field_descriptor(locator)
    if descriptor.get("type") == "password":
        return True
    haystack = _normalize_text(" ".join(descriptor.values()))
    return any(term in haystack for term in _SENSITIVE_FIELD_TERMS)


def _interactive_snapshot(page: Page) -> list[dict[str, Any]]:
    return page.evaluate(
        r"""
        () => {
          const visible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
          };

          const cssPath = (el) => {
            if (el.id) return '#' + CSS.escape(el.id);
            const parts = [];
            let node = el;
            while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.body) {
              let part = node.tagName.toLowerCase();
              const name = node.getAttribute('name');
              if (name) {
                const candidate = `${part}[name="${CSS.escape(name)}"]`;
                try {
                  if (document.querySelectorAll(candidate).length === 1) return candidate;
                } catch (_) {}
              }
              const parent = node.parentElement;
              if (parent) {
                const peers = Array.from(parent.children).filter(x => x.tagName === node.tagName);
                if (peers.length > 1) part += `:nth-of-type(${peers.indexOf(node) + 1})`;
              }
              parts.unshift(part);
              node = parent;
              if (parts.length >= 6) break;
            }
            return parts.join(' > ');
          };

          const labelFor = (el) => {
            if (el.labels && el.labels.length) {
              return Array.from(el.labels).map(x => (x.innerText || x.textContent || '').trim()).filter(Boolean).join(' ');
            }
            const nested = el.closest('label');
            return (el.getAttribute('aria-label') || (nested ? (nested.innerText || nested.textContent || '') : '') || '').trim();
          };

          const sensitive = (el, label) => {
            if ((el.getAttribute('type') || '').toLowerCase() === 'password') return true;
            const text = [el.id, el.getAttribute('name'), el.getAttribute('autocomplete'), el.getAttribute('aria-label'), label]
              .filter(Boolean).join(' ').toLowerCase();
            return /password|passwd|passcode|secret|access\s*token|api\s*key/.test(text);
          };

          const nodes = Array.from(document.querySelectorAll(
            'input:not([type="hidden"]), textarea, select, button, a[href], [role="button"]'
          )).filter(visible).slice(0, 200);

          return nodes.map(el => {
            const tag = el.tagName.toLowerCase();
            const type = (el.getAttribute('type') || '').toLowerCase();
            const label = labelFor(el);
            const item = {
              selector: cssPath(el),
              tag,
              type,
              name: el.getAttribute('name') || '',
              label,
              placeholder: el.getAttribute('placeholder') || '',
              required: !!el.required,
              disabled: !!el.disabled,
              sensitive: sensitive(el, label)
            };

            if (tag === 'select') {
              item.value = el.value;
              item.options = Array.from(el.options).slice(0, 60).map(option => ({
                value: option.value,
                text: (option.textContent || '').trim(),
                selected: option.selected
              }));
            } else if (type === 'checkbox' || type === 'radio') {
              item.checked = !!el.checked;
            } else if (type === 'file') {
              item.accept = el.getAttribute('accept') || '';
              item.fileName = el.files && el.files.length ? el.files[0].name : '';
            } else if (tag === 'a') {
              item.href = el.href || '';
              item.text = (el.innerText || el.textContent || '').trim().slice(0, 300);
            } else if (tag === 'button' || el.getAttribute('role') === 'button') {
              item.text = (el.innerText || el.textContent || '').trim().slice(0, 300);
            } else if (!item.sensitive && 'value' in el) {
              item.value = el.value || '';
            }
            return item;
          });
        }
        """
    )


def detect_human_blocker(page: Page, body_excerpt: str | None = None) -> dict[str, str] | None:
    """Detect only high-signal conditions that should be handed to a human.

    Provider names in ordinary footer/legal text are not blockers. Detection
    requires challenge-specific frame/field evidence or explicit challenge copy.
    """

    try:
        signals = page.evaluate(
            """
            () => ({
              frames: Array.from(document.querySelectorAll('iframe')).slice(0, 50).map(el => [
                el.getAttribute('src') || '',
                el.getAttribute('title') || '',
                el.getAttribute('name') || '',
                el.id || ''
              ].join(' ')),
              fields: Array.from(document.querySelectorAll('input')).slice(0, 100).map(el => [
                el.getAttribute('type') || '',
                el.getAttribute('name') || '',
                el.id || '',
                el.getAttribute('autocomplete') || '',
                el.getAttribute('aria-label') || ''
              ].join(' '))
            })
            """
        )
    except Exception:
        signals = {"frames": [], "fields": []}

    if body_excerpt is None:
        try:
            body_excerpt = page.locator("body").inner_text(timeout=2000)
        except Exception:
            body_excerpt = ""

    text = _normalize_text(body_excerpt)
    frame_text = _normalize_text(" ".join(signals.get("frames") or []))
    field_text = _normalize_text(" ".join(signals.get("fields") or []))

    cloudflare_frame = "challenges.cloudflare.com" in frame_text or "cf-chl" in frame_text
    cloudflare_copy = any(
        phrase in text
        for phrase in (
            "checking your browser",
            "performing security verification",
            "verify you are human",
        )
    )
    if cloudflare_frame or ("cloudflare" in text and cloudflare_copy):
        return {"code": "CLOUDFLARE", "reason": "Cloudflare human/security challenge detected"}

    captcha_tokens = ("recaptcha", "hcaptcha", "turnstile", "captcha")
    if any(token in frame_text for token in captcha_tokens):
        return {"code": "CAPTCHA", "reason": "Human verification/CAPTCHA detected"}
    if any(
        phrase in text
        for phrase in (
            "verify you are human",
            "prove you are human",
            "human verification",
            "complete the captcha",
            "solve the captcha",
        )
    ):
        return {"code": "CAPTCHA", "reason": "Human verification challenge detected"}

    if "passkey" in text or "webauthn" in field_text:
        return {"code": "PASSKEY", "reason": "Passkey authentication requires human interaction"}

    # 邮箱验证码组合证据检测：文案中必须明确具有邮箱/收件箱与验证码的关联上下文
    email_otp_phrases = (
        "verify your email",
        "verify email",
        "verification email",
        "code sent to your email",
        "sent a code to",
        "code sent to",
        "sent to your inbox",
        "check your email",
        "check your inbox",
        "email verification",
        "email code",
    )
    has_explicit_email_otp_phrase = any(phrase in text for phrase in email_otp_phrases)
    has_email_context = "email" in text or "inbox" in text
    has_otp_cue = any(
        term in text or term in field_text
        for term in (
            "verification code",
            "security code",
            "one-time-code",
            "one-time code",
            "6-digit code",
            "confirmation code",
            "enter code",
            "resend code",
        )
    )
    has_email_and_code = has_email_context and has_otp_cue

    if has_explicit_email_otp_phrase or has_email_and_code:
        return {"code": "EMAIL_OTP", "reason": "Email verification code required"}

    # 双因子认证：明确包含 2FA/authenticator 提示，或在没有邮箱上下文时的独立 one-time-code
    has_explicit_2fa_phrase = any(
        phrase in text
        for phrase in (
            "two-factor authentication",
            "two factor authentication",
            "2fa",
            "authenticator code",
            "authenticator app",
            "totp",
        )
    )
    if has_explicit_2fa_phrase or ("one-time-code" in field_text and not has_email_context):
        return {"code": "TWO_FACTOR", "reason": "Two-factor authentication step detected"}

    if any(phrase in text for phrase in ("verification code", "security code", "enter code", "confirmation code")):
        return {"code": "VERIFICATION_CHALLENGE", "reason": "Verification challenge step detected"}

    if any(token in field_text for token in ("cc-number", "cardnumber", "card-number")):
        return {"code": "PAYMENT", "reason": "Payment card entry requires human approval"}

    return None


def snapshot_page(page: Page) -> dict[str, Any]:
    body = page.locator("body")
    try:
        text = body.inner_text(timeout=3000)
    except Exception:
        text = ""
    body_excerpt = re.sub(r"\s+", " ", text).strip()[:MAX_BODY_EXCERPT]
    return {
        "url": page.url,
        "title": page.title(),
        "body_excerpt": body_excerpt,
        "interactive": _interactive_snapshot(page),
        "human_blocker": detect_human_blocker(page, body_excerpt),
    }


class BrowserRuntime:
    def __init__(
        self,
        profile_dir: Path,
        *,
        browser_channel: str = "chrome",
        headless: bool = True,
        allowed_upload_root: Path | None = None,
        credential_root: Path | None = None,
        timeout_ms: int = 30_000,
        cdp_url: str | None = None,
        allow_local_fallback: bool | None = None,
        keep_on_human_blocker: bool = False,
        keep_tab: bool = False,
        resume_target_id: str | None = None,
        target_domain: str | None = None,
    ):
        self.profile_dir = Path(profile_dir).expanduser().resolve()
        self.browser_channel = browser_channel
        self.headless = headless
        self.allowed_upload_root = (
            Path(allowed_upload_root).expanduser().resolve() if allowed_upload_root is not None else None
        )
        self.credential_root = Path(credential_root).expanduser().resolve() if credential_root is not None else None
        self.timeout_ms = timeout_ms
        self.cdp_url = cdp_url
        self.allow_local_fallback = allow_local_fallback
        self.keep_on_human_blocker = keep_on_human_blocker
        self.keep_tab = keep_tab
        self.resume_target_id = resume_target_id
        self.target_domain = target_domain
        self.is_external_cdp: bool = False
        self.target_id: str | None = None
        self._stopped_for_human: bool = False
        self._playwright: Playwright | None = None
        self._browser = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    @property
    def context(self) -> BrowserContext | None:
        return self._context

    def _find_page_by_target_id(self, target_id: str) -> Page | None:
        assert self._context is not None
        for page in self._context.pages:
            try:
                session = self._context.new_cdp_session(page)
                info = session.send("Target.getTargetInfo")
                if info.get("targetInfo", {}).get("targetId") == target_id:
                    return page
            except Exception:
                continue
        return None

    def _get_page_target_id(self, page: Page) -> str | None:
        if not self.is_external_cdp or self._context is None:
            return None
        try:
            session = self._context.new_cdp_session(page)
            info = session.send("Target.getTargetInfo")
            tid = info.get("targetInfo", {}).get("targetId")
            session.detach()
            return tid
        except Exception:
            return None

    def __enter__(self) -> "BrowserRuntime":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()

        candidate_cdp = (
            self.cdp_url
            or os.environ.get("BACKLINK_BROWSER_CDP_URL")
            or os.environ.get("SEO_BROWSER_CDP_URL")
        )
        if self.allow_local_fallback is not None:
            allow_fallback = bool(self.allow_local_fallback)
        else:
            allow_fallback = os.environ.get("BACKLINK_ALLOW_LOCAL_FALLBACK", "").strip().lower() in {"1", "true", "yes"}

        if not candidate_cdp and not allow_fallback:
            candidate_cdp = DEFAULT_CDP_URL

        cdp_ready = _probe_cdp(candidate_cdp) if candidate_cdp else None

        if candidate_cdp and cdp_ready:
            try:
                self._browser = self._playwright.chromium.connect_over_cdp(candidate_cdp)
                if not self._browser.contexts:
                    raise BrowserRuntimeError("NO_BROWSER_CONTEXT", "Connected CDP browser has no contexts")
                self._context = self._browser.contexts[0]
                self.is_external_cdp = True
            except Exception as exc:
                if isinstance(exc, BrowserRuntimeError):
                    raise
                self._playwright.stop()
                self._playwright = None
                raise BrowserRuntimeError("BROWSER_CONNECT_FAILED", f"Could not connect over CDP to {candidate_cdp}: {exc}") from exc

            self._context.set_default_timeout(self.timeout_ms)

            if self.resume_target_id:
                matched_page = self._find_page_by_target_id(self.resume_target_id)
                if matched_page is None:
                    self._playwright.stop()
                    self._playwright = None
                    raise BrowserRuntimeError(
                        "TARGET_TAB_LOST",
                        f"Target tab {self.resume_target_id} was not found in browser session",
                    )
                self.page = matched_page
                self.target_id = self.resume_target_id
            else:
                self.page = self._context.new_page()
                self.target_id = self._get_page_target_id(self.page)

            return self

        if candidate_cdp and not cdp_ready and not allow_fallback:
            self._playwright.stop()
            self._playwright = None
            raise BrowserRuntimeError(
                "BROWSER_HOST_UNAVAILABLE",
                f"Fixed CDP browser host at {candidate_cdp} is unavailable. Refusing silent fallback in production mode.",
            )

        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                channel=self.browser_channel,
                headless=self.headless,
                accept_downloads=False,
            )
        except Exception as exc:
            self._playwright.stop()
            self._playwright = None
            raise BrowserRuntimeError(
                "BROWSER_LAUNCH_FAILED",
                f"Could not launch browser channel {self.browser_channel!r}: {type(exc).__name__}",
            ) from exc

        self._context.set_default_timeout(self.timeout_ms)
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self.target_id = self._get_page_target_id(self.page)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.is_external_cdp:
            if self.page is not None:
                should_keep = (
                    bool(self.resume_target_id)
                    or self.keep_tab
                    or (self.keep_on_human_blocker and self._stopped_for_human)
                )
                if not should_keep:
                    try:
                        if not self.page.is_closed():
                            self.page.close()
                    except Exception:
                        pass
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
        else:
            if self._context is not None:
                try:
                    self._context.close()
                except Exception:
                    pass
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass

        self._context = None
        self._browser = None
        self._playwright = None
        self.page = None

    def navigate(self, url: str) -> dict[str, Any]:
        url = _validate_http_url(url)
        assert self.page is not None
        # When resuming an existing target tab already at the target URL,
        # avoid a hard reload so in-memory form state (such as an OTP verification screen) is preserved.
        if self.resume_target_id and self.page.url.rstrip("/") == url.rstrip("/"):
            snapshot = snapshot_page(self.page)
            if snapshot.get("human_blocker"):
                self._stopped_for_human = True
            return snapshot

        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            self.page.wait_for_timeout(100)
        except Exception as exc:
            raise BrowserRuntimeError(
                "NAVIGATION_FAILED",
                f"Navigation failed: {type(exc).__name__}",
            ) from exc
        snapshot = snapshot_page(self.page)
        if snapshot.get("human_blocker"):
            self._stopped_for_human = True
        return snapshot

    def inspect(self, url: str) -> dict[str, Any]:
        snapshot = self.navigate(url)
        return {
            "ok": True,
            "page": snapshot,
            "target_id": self.target_id,
            "is_external_cdp": self.is_external_cdp,
            "stopped_for_human": self._stopped_for_human,
        }

    def _unique_locator(self, selector: str) -> Locator:
        if not isinstance(selector, str) or not selector.strip():
            raise BrowserRuntimeError("INVALID_SELECTOR", "Action selector must be non-empty")
        assert self.page is not None
        locator = self.page.locator(selector.strip())
        try:
            count = locator.count()
        except Exception as exc:
            raise BrowserRuntimeError("INVALID_SELECTOR", "Could not evaluate action selector") from exc
        if count == 0:
            raise BrowserRuntimeError("ELEMENT_NOT_FOUND", f"No element matches selector {selector!r}")
        if count != 1:
            raise BrowserRuntimeError("AMBIGUOUS_SELECTOR", f"Selector matches {count} elements: {selector!r}")
        return locator

    def _verify_non_sensitive(self, locator: Locator) -> None:
        try:
            if _is_sensitive_field(locator):
                raise BrowserRuntimeError(
                    "SENSITIVE_FIELD",
                    "Sensitive fields require credential_fill or human/browser credential handling",
                )
        except BrowserRuntimeError:
            raise
        except Exception as exc:
            raise BrowserRuntimeError("FIELD_INSPECTION_FAILED", "Could not inspect target field safely") from exc

    def _verify_password_target(self, locator: Locator) -> None:
        try:
            descriptor = _field_descriptor(locator)
            if descriptor.get("type") != "password":
                raise BrowserRuntimeError(
                    "CREDENTIAL_TARGET_NOT_PASSWORD",
                    "credential_fill may only target an input with type=password",
                )
        except BrowserRuntimeError:
            raise
        except Exception as exc:
            raise BrowserRuntimeError("FIELD_INSPECTION_FAILED", "Could not inspect credential target safely") from exc

    def _resolve_upload(self, raw_path: Any) -> Path:
        if self.allowed_upload_root is None:
            raise BrowserRuntimeError("UPLOAD_ROOT_REQUIRED", "Upload actions require an allowed project asset root")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise BrowserRuntimeError("INVALID_UPLOAD", "Upload path must be non-empty")
        root = self.allowed_upload_root.resolve()
        path = Path(raw_path).expanduser().resolve()
        if not _is_inside(path, root):
            raise BrowserRuntimeError(
                "UPLOAD_OUTSIDE_PROJECT",
                "Upload file is outside the selected project's allowed asset root",
            )
        if not path.is_file():
            raise BrowserRuntimeError("UPLOAD_NOT_FOUND", "Upload file does not exist")
        return path

    def _site_password_for_action(self, action: dict[str, Any]) -> str:
        if self.credential_root is None:
            raise BrowserRuntimeError("CREDENTIAL_ROOT_REQUIRED", "credential_fill requires a local credential root")
        if action.get("credential") != "site_password":
            raise BrowserRuntimeError("INVALID_CREDENTIAL_KIND", "credential_fill supports only site_password")
        mode = action.get("mode") or "existing_only"
        account = action.get("account")
        assert self.page is not None
        parsed = urlparse(self.page.url)
        current_domain = (parsed.hostname or "").lower()
        if not current_domain:
            raise BrowserRuntimeError("INVALID_CREDENTIAL_DOMAIN", "could not resolve current page domain")

        # 第一层防御：Target Domain Allow Rule
        if self.target_domain:
            allowed = self.target_domain.lower().strip()
            if current_domain != allowed and not current_domain.endswith("." + allowed):
                raise BrowserRuntimeError(
                    "CREDENTIAL_TARGET_MISMATCH",
                    f"Current page domain {current_domain!r} does not match allowed target domain {allowed!r}",
                )

        # 第二层防御：通用第三方 Identity Provider 域名黑名单
        forbidden_idps = (
            "google.com", "accounts.google.com",
            "github.com",
            "twitter.com", "x.com",
            "apple.com", "appleid.apple.com",
            "microsoft.com", "login.microsoftonline.com",
            "facebook.com",
            "linkedin.com",
            "auth0.com", "okta.com",
        )
        for idp in forbidden_idps:
            if current_domain == idp or current_domain.endswith("." + idp):
                raise BrowserRuntimeError(
                    "PROTECTED_OAUTH_DOMAIN",
                    f"credential_fill is strictly forbidden on third-party identity provider domain {current_domain!r}",
                )

        try:
            return get_site_password(
                self.credential_root,
                current_domain,
                account=account,
                mode=mode,
            )
        except CredentialStoreError as exc:
            raise BrowserRuntimeError(exc.code, exc.message) from exc

    def execute(self, url: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(actions, list):
            raise BrowserRuntimeError("INVALID_ACTIONS", "Actions must be a JSON array")
        if len(actions) > MAX_ACTIONS:
            raise BrowserRuntimeError("TOO_MANY_ACTIONS", f"At most {MAX_ACTIONS} browser actions are allowed per plan")

        initial_page = self.navigate(url)
        assert self.page is not None
        evidence: list[dict[str, Any]] = []

        if initial_page.get("human_blocker"):
            self._stopped_for_human = True
            return {
                "ok": True,
                "actions": evidence,
                "page": initial_page,
                "stopped_for_human": True,
                "target_id": self.target_id,
                "is_external_cdp": self.is_external_cdp,
            }

        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                raise BrowserRuntimeError("INVALID_ACTION", f"Action {index} must be an object")
            action_type = action.get("type")
            selector = action.get("selector")
            if action_type not in _ALLOWED_ACTIONS:
                raise BrowserRuntimeError("INVALID_ACTION", f"Unsupported action type at index {index}")

            locator = self._unique_locator(selector)
            try:
                if action_type == "fill":
                    self._verify_non_sensitive(locator)
                    value = action.get("value")
                    if not isinstance(value, str):
                        raise BrowserRuntimeError("INVALID_ACTION", f"Fill action {index} requires a string value")
                    locator.fill(value)
                    readback = locator.input_value()
                    if readback != value:
                        raise BrowserRuntimeError("READBACK_MISMATCH", f"Fill read-back mismatch at action {index}")

                elif action_type == "credential_fill":
                    self._verify_password_target(locator)
                    password = self._site_password_for_action(action)
                    locator.fill(password)
                    if locator.input_value() != password:
                        raise BrowserRuntimeError("READBACK_MISMATCH", f"Credential fill read-back mismatch at action {index}")
                    readback = {"credential": "site_password", "verified": True}

                elif action_type == "select":
                    value = action.get("value")
                    if not isinstance(value, str):
                        raise BrowserRuntimeError("INVALID_ACTION", f"Select action {index} requires a string value")
                    locator.select_option(value=value)
                    readback = locator.input_value()
                    if readback != value:
                        raise BrowserRuntimeError("READBACK_MISMATCH", f"Select read-back mismatch at action {index}")

                elif action_type == "check":
                    locator.check()
                    readback = locator.is_checked()
                    if readback is not True:
                        raise BrowserRuntimeError("READBACK_MISMATCH", f"Checkbox read-back mismatch at action {index}")

                elif action_type == "upload":
                    path = self._resolve_upload(action.get("path"))
                    locator.set_input_files(str(path))
                    readback = locator.evaluate("el => el.files && el.files.length ? el.files[0].name : ''")
                    if readback != path.name:
                        raise BrowserRuntimeError("READBACK_MISMATCH", f"Upload read-back mismatch at action {index}")

                elif action_type in {"click", "submit"}:
                    locator.click()
                    self.page.wait_for_timeout(200)
                    readback = {"url": self.page.url, "title": self.page.title()}

                evidence.append(
                    {
                        "index": index,
                        "type": action_type,
                        "selector": selector,
                        "status": "verified",
                        "readback": readback,
                    }
                )
            except BrowserRuntimeError:
                raise
            except Exception as exc:
                raise BrowserRuntimeError(
                    "ACTION_FAILED",
                    f"Browser action {index} ({action_type}) failed for selector {selector!r}: {type(exc).__name__}",
                ) from exc

            current_page = snapshot_page(self.page)
            if current_page.get("human_blocker"):
                self._stopped_for_human = True
                return {
                    "ok": True,
                    "actions": evidence,
                    "page": current_page,
                    "stopped_for_human": True,
                    "target_id": self.target_id,
                    "is_external_cdp": self.is_external_cdp,
                }

        return {
            "ok": True,
            "actions": evidence,
            "page": snapshot_page(self.page),
            "stopped_for_human": False,
            "target_id": self.target_id,
            "is_external_cdp": self.is_external_cdp,
        }
