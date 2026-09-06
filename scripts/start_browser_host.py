#!/usr/bin/env python3
"""Start or safely reuse the project's visible, persistent Chrome CDP session.
Follows the exact mechanism and contract from SEO-Skills/runtime/start_live_browser.py.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

DEFAULT_PORT = 9222
DEFAULT_PROFILE = Path.home() / ".backlink-autofill" / "browser-profile"
DEFAULT_WAIT_SECONDS = 20.0
CHROME_CANDIDATES = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"),
)
START_URL = "about:blank"


def chrome_command(port: int, profile: Path, binary: Path | str, start_url: str = START_URL) -> list[str]:
    return [
        str(binary),
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        start_url,
    ]


def _validate_port(port: int) -> None:
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"CDP port must be between 1 and 65535: {port}")


def _cdp_version_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/json/version"


def read_cdp_version(port: int) -> dict | None:
    _validate_port(port)
    try:
        with urlopen(_cdp_version_url(port), timeout=0.5) as response:
            payload = json.load(response)
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and payload.get("Browser") else None


def port_is_free(port: int) -> bool:
    _validate_port(port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def dedicated_process_matches(port: int, expected_profile: Path) -> bool:
    profile_flag = f"--user-data-dir={Path(expected_profile).expanduser().resolve()}"
    port_flag = f"--remote-debugging-port={port}"
    result = subprocess.run(
        ["ps", "-axo", "command="],
        capture_output=True,
        text=True,
        check=False,
    )
    for command_line in result.stdout.splitlines():
        if port_flag in command_line and profile_flag in command_line and "Chrome" in command_line:
            return True
    return False


def start_chrome(port: int, profile: Path, binary: Path | str, start_url: str = START_URL) -> subprocess.Popen:
    Path(profile).mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        chrome_command(port, profile, binary, start_url),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def wait_for_cdp(port: int, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        version = read_cdp_version(port)
        if version is not None:
            return version
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"Chrome CDP endpoint did not become available on 127.0.0.1:{port}")
        time.sleep(min(0.2, remaining))


def ensure_browser(port: int, profile: Path, binary: Path | str, wait_seconds: float = DEFAULT_WAIT_SECONDS, start_url: str = START_URL) -> str:
    _validate_port(port)
    existing = read_cdp_version(port)
    if existing is not None:
        if dedicated_process_matches(port, profile):
            return "reused"
        raise RuntimeError(
            f"CDP port {port} is already served by an unknown process; refusing to reuse or replace it"
        )
    if not port_is_free(port):
        raise RuntimeError(f"CDP port {port} is occupied; refusing to kill an unknown process")

    process = start_chrome(port, profile, binary, start_url)
    try:
        wait_for_cdp(port, wait_seconds)
    except Exception:
        process.terminate()
        raise
    return "started"


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("macOS Google Chrome executable was not found")


def main() -> int:
    parser = argparse.ArgumentParser(description="Start or safely reuse the persistent Chrome CDP session.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE))
    parser.add_argument("--wait-seconds", type=float, default=DEFAULT_WAIT_SECONDS)
    parser.add_argument("--start-url", default=START_URL)
    args = parser.parse_args()

    port = args.port
    profile = Path(args.profile_dir).expanduser().resolve()

    try:
        status = ensure_browser(port, profile, find_chrome(), args.wait_seconds, args.start_url)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"BLOCKED: {exc}")
        return 2

    print(json.dumps({
        "ok": True,
        "status": status,
        "cdp_url": f"http://127.0.0.1:{port}",
        "profile_dir": str(profile),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
