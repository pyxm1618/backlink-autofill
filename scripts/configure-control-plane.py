#!/usr/bin/env python3
import argparse
import json
import os
import tempfile
from pathlib import Path

MASTER_SHEET = "外链总表"
PROJECT_SHEET = "项目外链管理"


def write_atomic(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description="Configure the shared Backlink Autofill Google Sheet control plane")
    parser.add_argument("--spreadsheet-id", required=True, help="private Google Spreadsheet ID")
    parser.add_argument("--batch-size", type=int, default=100, help="default max rows per invocation (1-100)")
    parser.add_argument("--home", default=str(Path.home()), help="home directory used for private config")
    args = parser.parse_args()

    spreadsheet_id = args.spreadsheet_id.strip()
    if not spreadsheet_id:
        raise SystemExit("spreadsheet-id must not be empty")
    if not 1 <= args.batch_size <= 100:
        raise SystemExit("batch-size must be between 1 and 100")

    root = Path(args.home).expanduser().resolve() / ".backlink-autofill"
    path = root / "control-plane.json"
    payload = {
        "schema_version": 1,
        "spreadsheet_id": spreadsheet_id,
        "master_sheet": MASTER_SHEET,
        "project_sheet": PROJECT_SHEET,
        "default_batch_size": args.batch_size,
    }
    write_atomic(path, payload)
    print(f"Configured shared control plane: {path}")
    print(f"Master tab: {MASTER_SHEET}")
    print(f"Project tab: {PROJECT_SHEET}")
    print(f"Default per-run batch size: {args.batch_size}")


if __name__ == "__main__":
    main()
