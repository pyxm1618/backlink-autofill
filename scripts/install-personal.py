#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path

PLUGIN_NAME = "backlink-autofill"
PLUGIN_RELATIVE_PATH = f"./plugins/{PLUGIN_NAME}"


def load_marketplace(path: Path):
    if not path.exists():
        return {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Refusing to overwrite invalid marketplace JSON: {path}: {exc}")
    if not isinstance(data.get("plugins"), list):
        raise SystemExit(f"Refusing to overwrite marketplace without a plugins array: {path}")
    return data


def ensure_submitter_profile(home: Path):
    config_dir = home / ".backlink-autofill"
    config_dir.mkdir(parents=True, exist_ok=True)
    profile_path = config_dir / "submitter-profile.json"
    if profile_path.exists():
        return profile_path, False

    profile = {
        "fullName": "",
        "email": "",
        "company": "",
        "country": "",
        "role": "",
        "phone": "",
        "socialUrls": {}
    }
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return profile_path, True


def main():
    parser = argparse.ArgumentParser(description="Install Backlink Autofill as a personal Codex plugin")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]), help="repository root")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    source = repo / "plugins" / PLUGIN_NAME
    if not (source / ".codex-plugin" / "plugin.json").exists():
        raise SystemExit(f"Plugin source not found: {source}")

    home = Path.home()
    destination = home / "plugins" / PLUGIN_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)

    marketplace_path = home / ".agents" / "plugins" / "marketplace.json"
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    marketplace = load_marketplace(marketplace_path)

    entry = {
        "name": PLUGIN_NAME,
        "source": {"source": "local", "path": PLUGIN_RELATIVE_PATH},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
        "category": "Marketing",
    }
    marketplace["plugins"] = [p for p in marketplace["plugins"] if p.get("name") != PLUGIN_NAME] + [entry]
    marketplace_path.write_text(json.dumps(marketplace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    profile_path, created = ensure_submitter_profile(home)

    print(f"Installed plugin: {destination}")
    print(f"Updated marketplace: {marketplace_path}")
    print(f"Submitter profile: {profile_path}{' (created)' if created else ' (preserved)'}")
    print("Fill reusable name/email/company/country details there once; never put site passwords in this file.")
    print("Restart/reload Codex, then invoke $backlink-autofill and explicitly name the project.")


if __name__ == "__main__":
    main()
