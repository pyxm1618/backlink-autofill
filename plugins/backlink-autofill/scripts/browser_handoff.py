#!/usr/bin/env python3
"""Detached headed-browser handoff lifecycle for Backlink Autofill."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from browser_runtime import BrowserRuntime, BrowserRuntimeError, snapshot_page

_HANDOFF_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_REPLAY_ACTIONS = {"fill", "credential_fill", "select", "check", "upload"}
_CREDENTIAL_FORBIDDEN_KEYS = {"value", "password", "passwd", "secret", "token", "api_key", "apikey"}


class HandoffError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _validate_handoff_id(value: str) -> str:
    if not isinstance(value, str) or not _HANDOFF_ID_RE.fullmatch(value.strip()):
        raise HandoffError("INVALID_HANDOFF_ID", "handoff-id must be a safe non-empty identifier")
    return value.strip()


def _session_dir(root: Path, handoff_id: str) -> Path:
    return Path(root).expanduser().resolve() / _validate_handoff_id(handoff_id)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_replay_actions(actions: Any) -> list[dict[str, Any]]:
    if actions is None:
        return []
    if not isinstance(actions, list):
        raise HandoffError("INVALID_REPLAY_ACTIONS", "replay actions must be a JSON array")
    if len(actions) > 100:
        raise HandoffError("INVALID_REPLAY_ACTIONS", "replay actions may contain at most 100 actions")

    for index, action in enumerate(actions):
        if not isinstance(action, dict) or action.get("type") not in _SAFE_REPLAY_ACTIONS:
            raise HandoffError(
                "UNSAFE_REPLAY_ACTION",
                f"handoff replay action {index} must be fill/credential_fill/select/check/upload; click and submit are never replayed",
            )

        if action.get("type") == "credential_fill":
            normalized_keys = {str(key).lower().replace("-", "_") for key in action}
            if normalized_keys & _CREDENTIAL_FORBIDDEN_KEYS:
                raise HandoffError(
                    "UNSAFE_REPLAY_ACTION",
                    f"credential replay action {index} must not contain a secret value",
                )
            if action.get("credential") != "site_password":
                raise HandoffError(
                    "UNSAFE_REPLAY_ACTION",
                    f"credential replay action {index} must use site_password",
                )
            if action.get("mode") not in {"create_or_reuse", "existing_only"}:
                raise HandoffError(
                    "UNSAFE_REPLAY_ACTION",
                    f"credential replay action {index} has an invalid mode",
                )

    return actions


def start_handoff(
    *,
    profile_dir: Path,
    browser_channel: str,
    url: str,
    handoff_root: Path,
    handoff_id: str,
    replay_actions: Any = None,
    allowed_upload_root: Path | None = None,
    credential_root: Path | None = None,
) -> dict[str, Any]:
    session = _session_dir(handoff_root, handoff_id)
    session.mkdir(parents=True, exist_ok=True)
    state_path = session / "state.json"

    if state_path.exists():
        current = _read_json(state_path)
        if current.get("state") in {"STARTING", "READY_FOR_HUMAN", "FINISH_REQUESTED"}:
            raise HandoffError("HANDOFF_ALREADY_ACTIVE", "this handoff session is already active")

    replay = _validate_replay_actions(replay_actions)
    finish_path = session / "finish.request"
    finish_path.unlink(missing_ok=True)

    request = {
        "schema_version": 1,
        "profile_dir": str(Path(profile_dir).expanduser().resolve()),
        "browser_channel": browser_channel,
        "url": url,
        "allowed_upload_root": str(Path(allowed_upload_root).expanduser().resolve()) if allowed_upload_root else None,
        "credential_root": str(Path(credential_root).expanduser().resolve()) if credential_root else None,
        "replay_actions": replay,
    }
    _atomic_json(session / "request.json", request)
    _atomic_json(state_path, {"ok": True, "state": "STARTING", "headed": True, "pid": None})

    worker_path = Path(__file__).resolve()
    stderr_handle = open(session / "worker.stderr.log", "a", encoding="utf-8")
    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": stderr_handle,
        "close_fds": True,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        popen_kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(
            [sys.executable, str(worker_path), "--worker", str(session)],
            **popen_kwargs,
        )
    finally:
        stderr_handle.close()

    started = {"ok": True, "state": "STARTING", "headed": True, "pid": process.pid}
    _atomic_json(state_path, started)
    return started


def handoff_status(*, handoff_root: Path, handoff_id: str) -> dict[str, Any]:
    session = _session_dir(handoff_root, handoff_id)
    state_path = session / "state.json"
    if not state_path.exists():
        raise HandoffError("HANDOFF_NOT_FOUND", "handoff session state does not exist")
    return _read_json(state_path)


def request_handoff_finish(*, handoff_root: Path, handoff_id: str) -> dict[str, Any]:
    session = _session_dir(handoff_root, handoff_id)
    if not (session / "state.json").exists():
        raise HandoffError("HANDOFF_NOT_FOUND", "handoff session state does not exist")
    (session / "finish.request").write_text("finish\n", encoding="utf-8")
    return {"ok": True, "state": "FINISH_REQUESTED", "headed": True}


def _worker(session: Path) -> int:
    state_path = session / "state.json"
    try:
        request = _read_json(session / "request.json")
        replay = _validate_replay_actions(request.get("replay_actions"))
        profile_dir = Path(request["profile_dir"])
        upload_root = Path(request["allowed_upload_root"]) if request.get("allowed_upload_root") else None
        credential_root = Path(request["credential_root"]) if request.get("credential_root") else None

        with BrowserRuntime(
            profile_dir,
            browser_channel=request.get("browser_channel") or "chrome",
            headless=False,
            allowed_upload_root=upload_root,
            credential_root=credential_root,
        ) as runtime:
            if replay:
                result = runtime.execute(request["url"], replay)
                page_state = result["page"]
                replay_evidence = result["actions"]
            else:
                result = runtime.inspect(request["url"])
                page_state = result["page"]
                replay_evidence = []

            ready = {
                "ok": True,
                "state": "READY_FOR_HUMAN",
                "headed": True,
                "pid": os.getpid(),
                "page": page_state,
                "replay_evidence": replay_evidence,
            }
            _atomic_json(state_path, ready)

            finish_path = session / "finish.request"
            while not finish_path.exists():
                if runtime.page is None or runtime.page.is_closed():
                    _atomic_json(
                        state_path,
                        {
                            "ok": True,
                            "state": "BROWSER_CLOSED",
                            "headed": True,
                            "pid": os.getpid(),
                        },
                    )
                    return 0
                time.sleep(0.2)

            final_page = snapshot_page(runtime.page) if runtime.page and not runtime.page.is_closed() else None
            _atomic_json(
                state_path,
                {
                    "ok": True,
                    "state": "FINISHED",
                    "headed": True,
                    "pid": os.getpid(),
                    "page": final_page,
                },
            )
            return 0

    except BrowserRuntimeError as exc:
        _atomic_json(
            state_path,
            {"ok": False, "state": "ERROR", "headed": True, "error_code": exc.code, "message": exc.message},
        )
        return 2
    except HandoffError as exc:
        _atomic_json(
            state_path,
            {"ok": False, "state": "ERROR", "headed": True, "error_code": exc.code, "message": exc.message},
        )
        return 2
    except Exception as exc:
        _atomic_json(
            state_path,
            {
                "ok": False,
                "state": "ERROR",
                "headed": True,
                "error_code": "HANDOFF_WORKER_FAILED",
                "message": f"headed handoff worker failed: {type(exc).__name__}",
            },
        )
        return 2


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return _worker(Path(sys.argv[2]).expanduser().resolve())
    print("browser_handoff.py is an internal worker; use browser_cli.py", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
