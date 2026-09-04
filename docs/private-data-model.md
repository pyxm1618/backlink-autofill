# Private Data Model

This document defines the canonical local private-data layout for Backlink Autofill.

## Root

All reusable private data lives under:

```text
~/.backlink-autofill/
```

The public plugin repository must not contain the user's private submitter data or private project assets.

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
2. Missing project data/assets must not be sourced from sibling project directories.
3. Installing/updating project A must not delete, replace or rewrite project B.
4. Derived image files for a target site stay inside the selected project directory.
5. Originals are preserved; resizing/reformatting/compression creates derived copies.

## Install/update invariant

Given this state:

```text
~/.backlink-autofill/
├── submitter-profile.json
└── projects/
    ├── quick-iching/
    └── project-b/
```

Installing/updating a Quick I Ching private pack may change only:

```text
projects/quick-iching/
```

It must preserve:

```text
submitter-profile.json
projects/project-b/
```

The private-pack installer should back up the existing private root before applying updates, then merge only the project directories included in that pack.

## Runtime resolution order

For a submission, the Skill resolves data in this order:

1. Explicit selected project ID from the plugin project registry.
2. Reviewed public project profile from the plugin.
3. Shared submitter profile from `~/.backlink-autofill/submitter-profile.json`.
4. Private project assets from `~/.backlink-autofill/projects/<project-id>/` only.
5. Verified canonical project source when allowed by the task.

No sibling-project fallback is allowed.
