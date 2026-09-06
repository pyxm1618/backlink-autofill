#!/usr/bin/env python3
"""JSON-only CLI wrapper around the Backlink Autofill browser runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from browser_handoff import HandoffError, handoff_status, request_handoff_finish, start_handoff
    from browser_runtime import BrowserRuntime, BrowserRuntimeError
    from execution_state import (
        clear_human_pending,
        list_human_pending,
        load_human_pending,
        resolve_human_pending,
        ProductionSheetGate,
        EvidenceContractError,
    )
except ModuleNotFoundError as exc:
    print(
        json.dumps(
            {
                "ok": False,
                "error_code": "DEPENDENCY_MISSING",
                "message": "Browser runtime dependency is missing; install scripts/requirements.txt and Playwright Chromium",
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile-dir", required=True)
    parser.add_argument("--browser-channel", default="chrome")
    parser.add_argument("--url", required=True)
    parser.add_argument("--headed", action="store_true", help="show the browser window; headless is default")
    parser.add_argument("--cdp-url", help="CDP endpoint URL (e.g. http://127.0.0.1:9222)")
    parser.add_argument("--allow-local-fallback", action="store_true", default=None, help="allow fallback to local Chromium in CI/test")
    parser.add_argument("--keep-on-human-blocker", action="store_true", help="keep tab open on human blocker")
    parser.add_argument("--target-id", help="CDP target ID to attach/resume")
    parser.add_argument("--target-domain", help="Allowed target domain for credential fill")


def _add_handoff_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--handoff-root", required=True)
    parser.add_argument("--handoff-id", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backlink Autofill browser runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect")
    _add_common(inspect_parser)

    execute_parser = subparsers.add_parser("execute")
    _add_common(execute_parser)
    execute_parser.add_argument("--allowed-upload-root")
    execute_parser.add_argument("--credential-root")
    execute_parser.add_argument("--actions-json", required=True)

    handoff_start_parser = subparsers.add_parser("handoff-start")
    handoff_start_parser.add_argument("--profile-dir", required=True)
    handoff_start_parser.add_argument("--browser-channel", default="chrome")
    handoff_start_parser.add_argument("--url", required=True)
    handoff_start_parser.add_argument("--allowed-upload-root")
    handoff_start_parser.add_argument("--credential-root")
    handoff_start_parser.add_argument("--replay-actions-json", default="[]")
    _add_handoff_identity(handoff_start_parser)

    handoff_status_parser = subparsers.add_parser("handoff-status")
    _add_handoff_identity(handoff_status_parser)

    handoff_finish_parser = subparsers.add_parser("handoff-finish")
    _add_handoff_identity(handoff_finish_parser)

    pending_list_parser = subparsers.add_parser("human-pending-list")
    pending_list_parser.add_argument("--runtime-root", required=True)
    pending_list_parser.add_argument("--project-id", required=True)

    pending_resolve_parser = subparsers.add_parser("human-pending-resolve")
    pending_resolve_parser.add_argument("--runtime-root", required=True)
    pending_resolve_parser.add_argument("--project-id", required=True)
    pending_resolve_parser.add_argument("--backlink-id", required=True)
    pending_resolve_parser.add_argument("--terminal-status", required=True)
    pending_resolve_parser.add_argument("--cdp-url", help="Optional CDP endpoint URL to best-effort close resolved tab")

    pending_clear_parser = subparsers.add_parser("human-pending-clear")
    pending_clear_parser.add_argument("--runtime-root", required=True)
    pending_clear_parser.add_argument("--project-id", required=True)
    pending_clear_parser.add_argument("--backlink-id", required=True)
    pending_clear_parser.add_argument("--admin-override", action="store_true", help="Explicit administrative confirmation")

    val_proj_parser = subparsers.add_parser("validate-project-mutation")
    val_proj_parser.add_argument("--evidence-json", required=True)
    val_proj_parser.add_argument("--proposed-json", required=True)
    val_proj_parser.add_argument("--strict-schedule", action="store_true")

    val_master_parser = subparsers.add_parser("validate-master-mutation")
    val_master_parser.add_argument("--evidence-json", required=True)
    val_master_parser.add_argument("--prior-json", default="{}")
    val_master_parser.add_argument("--proposed-json", required=True)

    otp_parser = subparsers.add_parser("resolve-email-otp")
    _add_common(otp_parser)
    otp_parser.add_argument("--stdin", action="store_true", required=True, help="read OTP ephemerally from stdin")

    return parser


def _emit_error(code: str, message: str) -> int:
    print(
        json.dumps({"ok": False, "error_code": code, "message": message}, ensure_ascii=False),
        file=sys.stderr,
    )
    return 2


def _parse_json_array(raw: str, error_code: str, label: str):
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HandoffError(error_code, f"{label} must contain valid JSON")
    if not isinstance(payload, list):
        raise HandoffError(error_code, f"{label} must contain a JSON array")
    return payload


def main() -> int:
    args = build_parser().parse_args()

    try:
        if args.command == "inspect":
            with BrowserRuntime(
                Path(args.profile_dir),
                browser_channel=args.browser_channel,
                headless=not args.headed,
                cdp_url=args.cdp_url,
                allow_local_fallback=args.allow_local_fallback,
                keep_on_human_blocker=args.keep_on_human_blocker,
                resume_target_id=args.target_id,
                target_domain=args.target_domain,
            ) as runtime:
                result = runtime.inspect(args.url)

        elif args.command == "execute":
            try:
                actions = json.loads(args.actions_json)
            except json.JSONDecodeError:
                return _emit_error("INVALID_ACTIONS_JSON", "actions-json must contain valid JSON")

            with BrowserRuntime(
                Path(args.profile_dir),
                browser_channel=args.browser_channel,
                headless=not args.headed,
                allowed_upload_root=Path(args.allowed_upload_root) if args.allowed_upload_root else None,
                credential_root=Path(args.credential_root) if args.credential_root else None,
                cdp_url=args.cdp_url,
                allow_local_fallback=args.allow_local_fallback,
                keep_on_human_blocker=args.keep_on_human_blocker,
                resume_target_id=args.target_id,
                target_domain=args.target_domain,
            ) as runtime:
                result = runtime.execute(args.url, actions)

        elif args.command == "human-pending-list":
            items = list_human_pending(Path(args.runtime_root), project_id=args.project_id)
            result = {"ok": True, "count": len(items), "project_id": args.project_id, "items": items}

        elif args.command == "human-pending-resolve":
            pending_record = load_human_pending(Path(args.runtime_root), args.project_id, args.backlink_id)
            target_id = pending_record.get("target_id") if pending_record else None

            resolved = resolve_human_pending(
                Path(args.runtime_root),
                project_id=args.project_id,
                backlink_id=args.backlink_id,
                terminal_status=args.terminal_status,
            )
            result = {
                "ok": True,
                "resolved": resolved,
                "project_id": args.project_id,
                "backlink_id": args.backlink_id,
                "terminal_status": args.terminal_status,
            }

            # Best-effort tab cleanup: 终态已确认，Tab 关闭仅为资源清理，任何失败绝不污染业务状态
            if resolved and target_id:
                cleanup_status = "SKIPPED"
                cdp_candidate = args.cdp_url or os.environ.get("BACKLINK_BROWSER_CDP_URL") or os.environ.get("SEO_BROWSER_CDP_URL") or "http://127.0.0.1:9222"
                try:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as pw:
                        browser = pw.chromium.connect_over_cdp(cdp_candidate, timeout=2000)
                        if browser.contexts:
                            ctx = browser.contexts[0]
                            for p in ctx.pages:
                                sess = None
                                try:
                                    sess = ctx.new_cdp_session(p)
                                    info = sess.send("Target.getTargetInfo")
                                    if info.get("targetInfo", {}).get("targetId") == target_id:
                                        p.close()
                                        cleanup_status = "CLOSED"
                                        break
                                except Exception:
                                    continue
                                finally:
                                    if sess is not None:
                                        try:
                                            sess.detach()
                                        except Exception:
                                            pass
                except Exception:
                    cleanup_status = "TAB_CLEANUP_FAILED"
                result["tab_cleanup"] = cleanup_status

        elif args.command == "human-pending-clear":
            if not args.admin_override:
                return _emit_error(
                    "ADMIN_OVERRIDE_REQUIRED",
                    "human-pending-clear is an admin-only operation requiring --admin-override. "
                    "Use human-pending-resolve after verifying stable terminal status."
                )
            clear_human_pending(
                Path(args.runtime_root),
                project_id=args.project_id,
                backlink_id=args.backlink_id,
                admin_override=True,
            )
            result = {"ok": True, "cleared": True, "project_id": args.project_id, "backlink_id": args.backlink_id}

        elif args.command == "handoff-start":
            replay = _parse_json_array(
                args.replay_actions_json,
                "INVALID_REPLAY_ACTIONS_JSON",
                "replay-actions-json",
            )
            result = start_handoff(
                profile_dir=Path(args.profile_dir),
                browser_channel=args.browser_channel,
                url=args.url,
                handoff_root=Path(args.handoff_root),
                handoff_id=args.handoff_id,
                replay_actions=replay,
                allowed_upload_root=Path(args.allowed_upload_root) if args.allowed_upload_root else None,
                credential_root=Path(args.credential_root) if args.credential_root else None,
            )

        elif args.command == "handoff-status":
            result = handoff_status(
                handoff_root=Path(args.handoff_root),
                handoff_id=args.handoff_id,
            )

        elif args.command == "handoff-finish":
            result = request_handoff_finish(
                handoff_root=Path(args.handoff_root),
                handoff_id=args.handoff_id,
            )

        elif args.command == "validate-project-mutation":
            try:
                evidence = json.loads(args.evidence_json)
                proposed = json.loads(args.proposed_json)
            except json.JSONDecodeError:
                return _emit_error("INVALID_JSON", "evidence-json and proposed-json must be valid JSON")
            validated = ProductionSheetGate.validate_project_mutation(
                evidence=evidence,
                proposed=proposed,
                strict_schedule=args.strict_schedule,
            )
            result = {"ok": True, "validated": validated}

        elif args.command == "validate-master-mutation":
            try:
                evidence = json.loads(args.evidence_json)
                prior = json.loads(args.prior_json) if args.prior_json else {}
                proposed = json.loads(args.proposed_json)
            except json.JSONDecodeError:
                return _emit_error("INVALID_JSON", "evidence-json, prior-json and proposed-json must be valid JSON")
            validated = ProductionSheetGate.validate_master_mutation(
                evidence=evidence,
                prior_facts=prior,
                proposed=proposed,
            )
            result = {"ok": True, "validated": validated}

        elif args.command == "resolve-email-otp":
            if not args.target_id:
                return _emit_error("MISSING_TARGET_ID", "--target-id is required for resolve-email-otp")
            if not args.stdin:
                return _emit_error("STDIN_REQUIRED", "OTP must be passed via --stdin ephemeral channel")

            otp_code = sys.stdin.read().strip()
            if not otp_code:
                return _emit_error("EMPTY_OTP_INPUT", "No OTP code received on stdin")

            with BrowserRuntime(
                profile_dir=Path(args.profile_dir),
                browser_channel=args.browser_channel,
                headless=not args.headed,
                cdp_url=args.cdp_url,
                allow_local_fallback=args.allow_local_fallback,
                resume_target_id=args.target_id,
            ) as runtime:
                result = runtime.resolve_email_otp(args.target_id, otp_code)

        else:
            return _emit_error("INVALID_COMMAND", "unsupported command")

        print(json.dumps(result, ensure_ascii=False))
        return 0

    except EvidenceContractError as exc:
        return _emit_error("EVIDENCE_CONTRACT_VIOLATION", str(exc))
    except BrowserRuntimeError as exc:
        return _emit_error(exc.code, exc.message)
    except HandoffError as exc:
        return _emit_error(exc.code, exc.message)
    except Exception as exc:
        return _emit_error("UNEXPECTED_BROWSER_ERROR", f"Unexpected browser runtime failure: {type(exc).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
