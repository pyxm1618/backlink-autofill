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
    handoff_start_parser.add_argument("--replay-actions-json", default="[]")
    _add_handoff_identity(handoff_start_parser)

    handoff_status_parser = subparsers.add_parser("handoff-status")
    _add_handoff_identity(handoff_status_parser)

    handoff_finish_parser = subparsers.add_parser("handoff-finish")
    _add_handoff_identity(handoff_finish_parser)

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
            ) as runtime:
                result = runtime.execute(args.url, actions)

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

        else:
            return _emit_error("INVALID_COMMAND", "unsupported command")

        print(json.dumps(result, ensure_ascii=False))
        return 0

    except BrowserRuntimeError as exc:
        return _emit_error(exc.code, exc.message)
    except HandoffError as exc:
        return _emit_error(exc.code, exc.message)
    except Exception as exc:
        return _emit_error("UNEXPECTED_BROWSER_ERROR", f"Unexpected browser runtime failure: {type(exc).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
