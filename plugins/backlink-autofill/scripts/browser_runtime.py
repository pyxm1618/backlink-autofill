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
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from playwright.sync_api import BrowserContext, Locator, Page, Playwright, sync_playwright

from credential_store import CredentialStoreError, get_site_password

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
IDLE_WORKER_URLS = {"about:blank", "chrome://newtab/", "chrome://new-tab-page/"}
AI_WORKER_WINDOW_NAME = "backlink-autofill:ai-worker:v1"


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
        runtime_root_env = os.environ.get("BACKLINK_RUNTIME_ROOT")
        self.runtime_root = (
            Path(runtime_root_env).expanduser().resolve()
            if runtime_root_env
            else self.profile_dir.parent / "runtime"
        )
        self.is_external_cdp: bool = False
        self.target_id: str | None = None
        self._stopped_for_human: bool = False
        self._last_blocker: dict[str, str] | None = None
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
            session = None
            try:
                session = self._context.new_cdp_session(page)
                info = session.send("Target.getTargetInfo")
                if info.get("targetInfo", {}).get("targetId") == target_id:
                    return page
            except Exception:
                continue
            finally:
                if session is not None:
                    try:
                        session.detach()
                    except Exception:
                        pass
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

    def _active_human_pending_target_ids(self) -> set[str]:
        """Return unresolved durable HUMAN_PENDING target IDs across all projects."""
        pending_root = self.runtime_root / "human-pending"
        if not pending_root.exists() or not pending_root.is_dir():
            return set()

        target_ids: set[str] = set()
        try:
            pending_files = list(pending_root.glob("*/*.json"))
        except OSError:
            return set()

        for pending_file in pending_files:
            try:
                payload = json.loads(pending_file.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or payload.get("status") != "NEEDS_HUMAN":
                continue
            target_id = payload.get("target_id")
            if isinstance(target_id, str) and target_id.strip():
                target_ids.add(target_id.strip())
        return target_ids

    @staticmethod
    def _page_has_idle_url(page: Page) -> bool:
        try:
            return not page.is_closed() and page.url in IDLE_WORKER_URLS
        except Exception:
            return False

    @staticmethod
    def _is_ai_worker_page(page: Page) -> bool:
        try:
            return not page.is_closed() and page.evaluate("window.name") == AI_WORKER_WINDOW_NAME
        except Exception:
            return False

    @staticmethod
    def _mark_ai_worker_page(page: Page) -> None:
        try:
            page.evaluate("name => { window.name = name; }", AI_WORKER_WINDOW_NAME)
        except Exception:
            pass

    def _is_idle_worker_page(self, page: Page, protected_target_ids: set[str]) -> bool:
        if not self._page_has_idle_url(page) or not self._is_ai_worker_page(page):
            return False
        target_id = self._get_page_target_id(page)
        return not target_id or target_id not in protected_target_ids

    def _acquire_worker_page(self, *, exclude_page: Page | None = None) -> Page:
        assert self._context is not None
        protected_target_ids = self._active_human_pending_target_ids()

        idle_pages = [
            page
            for page in self._context.pages
            if page is not exclude_page and self._is_idle_worker_page(page, protected_target_ids)
        ]
        if idle_pages:
            worker = idle_pages[0]
            # Compact only pages positively identified as AI-owned workers. A blank URL
            # alone is never ownership evidence, and unresolved pending target IDs win.
            for extra in idle_pages[1:]:
                try:
                    extra.close()
                except Exception:
                    pass
            return worker

        # Bootstrap exactly one unprotected blank page as the AI worker. Other unmarked
        # blank pages are user-owned/unknown and are never compacted merely by URL.
        for page in self._context.pages:
            if page is exclude_page or not self._page_has_idle_url(page):
                continue
            target_id = self._get_page_target_id(page)
            if target_id and target_id in protected_target_ids:
                continue
            self._mark_ai_worker_page(page)
            return page

        worker = self._context.new_page()
        self._mark_ai_worker_page(worker)
        return worker

    def _release_worker_page(self) -> None:
        if self.page is None:
            return
        try:
            if self.page.is_closed():
                return
        except Exception:
            return

        try:
            if self.page.url != "about:blank":
                self.page.goto(
                    "about:blank",
                    wait_until="commit",
                    timeout=min(self.timeout_ms, 5_000),
                )
            self._mark_ai_worker_page(self.page)
        except Exception:
            # A worker that cannot be reset safely should not linger as an orphan.
            try:
                if not self.page.is_closed():
                    self.page.close()
            except Exception:
                pass

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
                self.page = self._acquire_worker_page()
                self._mark_ai_worker_page(self.page)
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
                # Resumed targets are protected until the durable pending record is
                # explicitly resolved after business-terminal evidence. Blocker absence
                # alone is not terminal completion.
                preserve_exact_tab = (
                    self.keep_tab
                    or bool(self.resume_target_id)
                    or (self.keep_on_human_blocker and self._stopped_for_human)
                )
                if preserve_exact_tab:
                    # The protected page is no longer available to AI automation. Keep it
                    # untouched and immediately ensure a separate idle worker exists so
                    # subsequent tasks can continue without reusing the human's tab.
                    try:
                        self._acquire_worker_page(exclude_page=self.page)
                    except Exception:
                        # Never sacrifice or mutate a human-pending tab merely because a
                        # replacement worker could not be created; the next run can retry.
                        pass
                else:
                    # Ordinary AI work releases the page back to one reusable idle
                    # worker instead of creating/closing a renderer for every task.
                    self._release_worker_page()
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
                self._last_blocker = snapshot.get("human_blocker")
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
            self._last_blocker = snapshot.get("human_blocker")
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
                self._last_blocker = current_page.get("human_blocker")
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

    def resolve_email_otp(self, target_id: str, otp_code: str, wait_timeout_ms: int = 5000) -> dict[str, Any]:
        """Fill ephemeral email verification code into target tab and submit.
        
        Security guarantees:
        - Never returns or echoes the OTP code in result dictionary.
        - Preserves existing tab state; does not reload or restart page.
        """
        assert self.page is not None
        if not otp_code or not str(otp_code).strip():
            raise BrowserRuntimeError("EMPTY_OTP", "OTP code cannot be empty")

        clean_code = str(otp_code).strip()

        candidate_selectors = [
            'input[autocomplete="one-time-code"]',
            'input[placeholder*="code" i]',
            'input[placeholder*="digit" i]',
            'input[name*="code" i]',
            'input[name*="otp" i]',
            'form input[type="text"]:not([disabled])',
            'input:not([type="hidden"]):not([disabled])',
        ]
        input_locator = None
        for sel in candidate_selectors:
            loc = self.page.locator(sel).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    input_locator = loc
                    break
            except Exception:
                continue

        if input_locator is None:
            raise BrowserRuntimeError("OTP_INPUT_NOT_FOUND", "Could not locate visible OTP input on current page")

        try:
            input_locator.fill(clean_code)
        except Exception as exc:
            raise BrowserRuntimeError("OTP_FILL_FAILED", f"Failed to fill OTP input: {type(exc).__name__}") from exc

        button_selectors = [
            'button[type="submit"]',
            'button:has-text("Verify")',
            'button:has-text("Continue")',
            'button:has-text("Confirm")',
            'button:has-text("Submit")',
            'input[type="submit"]',
        ]
        submit_locator = None
        for b_sel in button_selectors:
            b_loc = self.page.locator(b_sel).first
            try:
                if b_loc.count() > 0 and b_loc.is_visible():
                    submit_locator = b_loc
                    break
            except Exception:
                continue

        if submit_locator is not None:
            try:
                submit_locator.click()
            except Exception as exc:
                raise BrowserRuntimeError("OTP_SUBMIT_FAILED", f"Failed to click OTP submit button: {type(exc).__name__}") from exc

        try:
            self.page.wait_for_timeout(500)
        except Exception:
            pass

        current_snapshot = snapshot_page(self.page)
        if not current_snapshot.get("human_blocker"):
            self._stopped_for_human = False

        return {
            "ok": True,
            "action": "EMAIL_OTP_RESOLVED",
            "target_id": self.target_id,
            "current_url": self.page.url,
            "stopped_for_human": self._stopped_for_human,
        }


    def resolve_email_magic_link(self, target_id: str, magic_link: str, platform_domain: str) -> dict[str, Any]:
        """Navigate to verified email Magic Link and confirm platform identity closure.

        Security guarantees:
        - Never echoes the tokenized URL in return value, logs, or exceptions.
        - Enforces initial DNS boundary check before navigating: host must be platform domain or approved ESP.
        - Enforces two-layer safety: verifies closure does not land on protected primary IdP.
        - Strictly decouples Safe Navigation / Platform Closure from Verification Success:
          * Query validation uses parse_qs for exact key/value matching (no substring containment).
          * Rejects invalid/expired paths (/invalid, /expired, etc.) and unverified parameters.
          * Blocker-cleared transition strictly requires prior blocker to be EMAIL_OTP and
            requires positive continuation evidence (generic homepage is rejected).
          * Plain stopped=True -> blocker=None alone is NEVER considered verification success.
          * Lacking positive proof raises MAGIC_LINK_UNCONFIRMED.
        """
        from email_otp_resolver import is_allowed_initial_magic_link_host, validate_magic_link_closure

        assert self.page is not None
        if not magic_link or not str(magic_link).strip():
            raise BrowserRuntimeError("EMPTY_MAGIC_LINK", "Magic link URL cannot be empty")

        clean_url = str(magic_link).strip()
        parsed = urlparse(clean_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BrowserRuntimeError("INVALID_MAGIC_LINK", "Invalid magic link URL scheme or netloc")

        initial_host = (parsed.netloc or "").split(":")[0].lower()
        if not is_allowed_initial_magic_link_host(initial_host, platform_domain):
            raise BrowserRuntimeError(
                "MAGIC_LINK_HOST_FORBIDDEN",
                f"Initial magic link host {initial_host} is not permitted for target platform {platform_domain}",
            )

        prior_blocker = self._last_blocker
        if not prior_blocker and self.page:
            try:
                prior_blocker = snapshot_page(self.page).get("human_blocker")
            except Exception:
                prior_blocker = None
        prior_is_email_otp = bool(prior_blocker and prior_blocker.get("code") == "EMAIL_OTP")

        try:
            self.page.goto(clean_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            self.page.wait_for_timeout(1000)
        except Exception as exc:
            raise BrowserRuntimeError("MAGIC_LINK_NAVIGATION_FAILED", f"Magic link navigation failed: {type(exc).__name__}") from exc

        final_url = self.page.url
        if not validate_magic_link_closure(final_url, platform_domain):
            parsed_final = urlparse(final_url)
            final_host = (parsed_final.netloc or "").split(":")[0].lower()
            if any(idp in final_host for idp in ("google.com", "github.com", "microsoft.com", "apple.com")):
                raise BrowserRuntimeError("PROTECTED_AUTH_NAVIGATED", f"Magic link navigated to protected IdP {final_host}; cannot auto-authenticate")
            raise BrowserRuntimeError("MAGIC_LINK_CLOSURE_FAILED", f"Magic link failed to reach platform domain {platform_domain}; landed on {final_host}")

        current_snapshot = snapshot_page(self.page)
        body_lower = (current_snapshot.get("body_excerpt") or "").lower()
        parsed_final = urlparse(final_url)
        final_path = parsed_final.path.lower()
        path_segments = [s for s in final_path.split("/") if s]

        # 1. 明确的 invalid / expired 路径拦截 (/invalid, /expired 等)
        invalid_expired_path_tokens = {"invalid", "expired", "token-expired", "link-expired", "already-used", "link-invalid", "token-invalid"}
        if any(seg in invalid_expired_path_tokens for seg in path_segments) or any(
            p in final_path for p in ("/invalid", "/expired", "/token-expired", "/link-expired", "/already-used")
        ):
            raise BrowserRuntimeError(
                "MAGIC_LINK_EXPIRED_OR_INVALID",
                f"Magic link reached invalid or expired path: {final_path}",
            )

        # 2. Query 严格使用 parse_qs 校验 (拒绝 substring 假匹配，拦截 unverified=true 等)
        query_params = parse_qs(parsed_final.query)
        reject_query_keys = {"error", "expired", "invalid", "unverified", "not_verified"}
        for qk, qvals in query_params.items():
            qk_lower = qk.lower()
            if qk_lower in reject_query_keys:
                raise BrowserRuntimeError(
                    "MAGIC_LINK_EXPIRED_OR_INVALID",
                    f"Magic link query parameter indicates invalid or unverified status: {qk}",
                )
            if qk_lower == "status" and any(v.lower() in ("expired", "invalid", "unverified", "failed") for v in qvals):
                raise BrowserRuntimeError(
                    "MAGIC_LINK_EXPIRED_OR_INVALID",
                    "Magic link query status indicates expired or invalid",
                )

        # 检查 DOM 文本中明确的失效/过期短语
        expired_invalid_dom_phrases = (
            "link has expired", "token has expired", "link is expired", "link expired",
            "magic link expired", "link is invalid", "invalid verification link",
            "token is invalid", "invalid token", "link has already been used",
            "already been used", "link already used", "this link is no longer valid",
        )
        if any(phrase in body_lower for phrase in expired_invalid_dom_phrases):
            raise BrowserRuntimeError(
                "MAGIC_LINK_EXPIRED_OR_INVALID",
                "Magic link has expired, is invalid, or has already been used",
            )

        # 3. 检查正面验证成功证据 (Positive Verification Evidence)
        SUCCESS_QUERY_KEYS = {
            "verified": {"true", "1", "yes", "success"},
            "verify": {"true", "1", "yes", "success"},
            "confirmed": {"true", "1", "yes", "success"},
            "confirm": {"true", "1", "yes", "success"},
            "email_verified": {"true", "1", "yes", "success"},
            "status": {"verified", "confirmed", "success"},
            "auth": {"success", "verified"},
            "success": {"true", "1", "verified"},
        }
        has_explicit_url_success = False
        for qk, qvals in query_params.items():
            qk_lower = qk.lower()
            if qk_lower in SUCCESS_QUERY_KEYS:
                if any(v.lower() in SUCCESS_QUERY_KEYS[qk_lower] for v in qvals):
                    has_explicit_url_success = True
                    break

        if any(seg in final_path for seg in ("/verification-success", "/email-confirmed", "/account-verified", "/confirm-success")):
            has_explicit_url_success = True

        explicit_dom_success_phrases = (
            "email verified", "email has been verified", "email successfully verified",
            "successfully confirmed", "account activated", "your email is confirmed",
            "account is verified", "verification successful", "email address confirmed",
            "your account has been activated", "logged in successfully", "sign in confirmed",
        )
        has_explicit_dom_success = any(phrase in body_lower for phrase in explicit_dom_success_phrases)

        # 4. blocker-cleared transition：必须确认 prior blocker 是 EMAIL_OTP，且具备可信 continuation 证据
        path_stripped = final_path.strip("/")
        has_session_markers = any(cue in body_lower for cue in ("logout", "sign out", "my account", "sign-out", "log-out"))
        is_generic_homepage = (path_stripped == "" and not parsed_final.query)

        continuation_path_cues = (
            "/submit", "/new", "/dashboard", "/onboarding", "/app",
            "/settings", "/profile", "/create", "/projects", "/listing", "/welcome"
        )
        has_continuation_path = any(cue in final_path for cue in continuation_path_cues)
        has_unauthenticated_cues = any(cue in body_lower for cue in ("please sign in", "please log in", "sign in to your account"))

        is_verified_continuation = (
            (has_continuation_path or has_session_markers)
            and not is_generic_homepage
            and not has_unauthenticated_cues
            and not any(term in body_lower for term in ("invalid", "expired", "failed to verify", "error"))
        )

        has_blocker_cleared_transition = (
            prior_is_email_otp
            and not current_snapshot.get("human_blocker")
            and is_verified_continuation
        )

        if not (has_explicit_url_success or has_explicit_dom_success or has_blocker_cleared_transition):
            raise BrowserRuntimeError(
                "MAGIC_LINK_UNCONFIRMED",
                "Magic link landed on platform but lacks definitive verification success evidence or verified continuation",
            )

        # 正面证据确凿，解除 human blocker 停顿
        if not current_snapshot.get("human_blocker"):
            self._stopped_for_human = False
            self._last_blocker = None

        safe_landed_domain = (parsed_final.netloc or "").split(":")[0].lower()

        return {
            "ok": True,
            "action": "MAGIC_LINK_RESOLVED",
            "verification_succeeded": True,
            "closure_verified": True,
            "target_id": self.target_id,
            "safe_landed_domain": safe_landed_domain,
            "stopped_for_human": self._stopped_for_human,
        }

