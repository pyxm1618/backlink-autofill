# Private Data Model

This document defines the canonical local private-data layout for Backlink Autofill.

## Root

All reusable private data lives under:

```text
~/.backlink-autofill/
```

The public plugin repository must not contain the user's private submitter data, Google Spreadsheet ID, browser session data, or private project assets.

## Shared control plane

All projects use one private Google Spreadsheet control plane. Its ID is stored once at:

```text
~/.backlink-autofill/control-plane.json
```

Canonical schema:

```json
{
  "schema_version": 1,
  "spreadsheet_id": "",
  "master_sheet": "外链总表",
  "project_sheet": "项目外链管理",
  "default_batch_size": 100
}
```

Rules:

- One control-plane file is shared by every project.
- Projects are isolated inside `项目外链管理` by exact `项目ID`, not by separate Spreadsheet files.
- The Spreadsheet ID is private local configuration and must never be committed to the public repository.
- Configure or replace this file explicitly with `scripts/configure-control-plane.py`.
- Plugin reinstall must preserve an existing `control-plane.json` unchanged.
- `default_batch_size` is a per-invocation maximum, not a daily quota or schedule.

## One shared submitter profile

There is exactly one reusable human/operator profile:

```text
~/.backlink-autofill/submitter-profile.json
```

It is shared by every project. A new project must not create its own duplicate personal profile.

Canonical schema:

```json
{
  "schema_version": 1,
  "name": "",
  "registration_email": "",
  "country": "",
  "region": "",
  "city": "",
  "company": null,
  "job_title": "",
  "phone": "",
  "x_twitter": null,
  "linkedin": null,
  "github": null,
  "default_username": null,
  "notes": []
}
```

Rules:

- First install may seed this file.
- Subsequent plugin/project installs or asset updates must preserve it if it already exists.
- Missing reusable facts can be added once and then reused.
- Passwords must never be stored here.

## Per-project isolation

Every project's private material lives under its project ID:

```text
~/.backlink-autofill/projects/<project-id>/
```

Recommended layout:

```text
projects/<project-id>/
├── assets.json
├── assets/
│   ├── logo-original.png
│   ├── hero-original.png
│   ├── screenshots/
│   └── derived/
└── source/
```

`assets.json` is the local manifest describing semantic roles, paths, dimensions and adaptation policy for that project's assets.

Hard isolation rules:

1. The explicitly selected project ID determines the only private project directory the AI may use.
2. The same project ID is the only `项目外链管理` row set the agent may process during that run.
3. Missing project data/assets must not be sourced from sibling project directories.
4. Installing/updating project A must not delete, replace or rewrite project B.
5. Derived image files for a target site stay inside the selected project directory.
6. Originals are preserved; resizing/reformatting/compression creates derived copies.

## Browser/runtime data

The installer ensures these shared directories exist without replacing their contents:

```text
~/.backlink-autofill/
├── browser-profile/   # persistent automation browser profile/session
├── runtime/           # per-project/per-row transient checkpoints
└── recipes/           # reusable domain-level browser recipes
```

Rules:

- Reinstalling the plugin must preserve all three directories and their contents.
- `runtime/` checkpoints are keyed by selected project and Sheet row/target identity.
- `recipes/` are platform/domain-level and must not contain project-specific marketing copy.
- None of these locations may store passwords, authentication secrets, CAPTCHA solutions, or security tokens intentionally.

## Install/update invariant

Given this state:

```text
~/.backlink-autofill/
├── submitter-profile.json
├── control-plane.json
├── browser-profile/
├── runtime/
├── recipes/
└── projects/
    ├── quick-iching/
    └── project-b/
```

Installing/updating the Codex plugin must preserve every private item above. Installing/updating a Quick I Ching private asset pack may change only:

```text
projects/quick-iching/
```

It must preserve the shared submitter profile, shared control plane, browser/runtime/recipe data, and every sibling project directory.

## Runtime resolution order

For a submission run, the Skill resolves data in this order:

1. Explicit selected project ID from the plugin project registry.
2. Shared control plane from `~/.backlink-autofill/control-plane.json`.
3. Reviewed public project profile from the plugin.
4. Shared submitter profile from `~/.backlink-autofill/submitter-profile.json`.
5. Private project assets from `~/.backlink-autofill/projects/<project-id>/` only.
6. `项目外链管理` rows whose `项目ID` exactly equals the selected project ID.
7. Platform data joined from `外链总表` by `外链ID`.
8. Verified canonical project source when allowed by the task.

No sibling-project or other-project-row fallback is allowed.
