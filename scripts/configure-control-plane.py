#!/usr/bin/env python3
import argparse
import json
import os
import tempfile
from pathlib import Path

MASTER_SHEET = "外链总表"
PROJECT_SHEET = "外链管理"
OLD_PROJECT_SHEET = "项目外链管理"


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


def safe_migrate_control_plane(config_path: Path, available_worksheets: list[str] | None = None) -> bool:
    """Migrate legacy project_sheet name with strict verification conditions.

    Rules:
    - Only migrate if current project_sheet is '项目外链管理'.
    - If available_worksheets is provided, ensure '外链管理' exists before migrating.
    - Preserves spreadsheet_id, schema_version, default_batch_size, and other settings.
    - Reads back to verify the atomic write.
    """
    if not config_path.exists():
        return False

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    if not isinstance(data, dict):
        return False

    current_project = data.get("project_sheet")
    if current_project != OLD_PROJECT_SHEET:
        # Already migrated or not using legacy name
        return False

    if available_worksheets is not None:
        if PROJECT_SHEET not in available_worksheets:
            print(f"Warning: Cannot migrate control plane yet: tab {PROJECT_SHEET!r} not found in verified worksheets.")
            return False

    data["project_sheet"] = PROJECT_SHEET
    write_atomic(config_path, data)

    # Verification readback
    readback = json.loads(config_path.read_text(encoding="utf-8"))
    if readback.get("project_sheet") != PROJECT_SHEET:
        raise RuntimeError("Verification readback failed during control plane migration")

    print(f"Successfully migrated control plane project_sheet: {OLD_PROJECT_SHEET} -> {PROJECT_SHEET}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Configure or migrate the shared Backlink Autofill Google Sheet control plane")
    parser.add_argument("--spreadsheet-id", help="private Google Spreadsheet ID")
    parser.add_argument("--batch-size", type=int, default=100, help="default max rows per invocation (1-100)")
    parser.add_argument("--home", default=str(Path.home()), help="home directory used for private config")
    parser.add_argument("--migrate", action="store_true", help="safely migrate legacy project_sheet to 外链管理")
    args = parser.parse_args()

    root = Path(args.home).expanduser().resolve() / ".backlink-autofill"
    path = root / "control-plane.json"

    if args.migrate:
        migrated = safe_migrate_control_plane(path)
        if not migrated:
            print("No migration needed or configuration not found.")
        return

    if not args.spreadsheet_id:
        raise SystemExit("--spreadsheet-id is required when configuring a new control plane")

    spreadsheet_id = args.spreadsheet_id.strip()
    if not spreadsheet_id:
        raise SystemExit("spreadsheet-id must not be empty")
    if not 1 <= args.batch_size <= 100:
        raise SystemExit("batch-size must be between 1 and 100")

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
