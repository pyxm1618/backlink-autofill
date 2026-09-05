# Private Data Model

This document defines the canonical local private-data layout for Backlink Autofill.

## Root

All reusable private data lives under:

```text
~/.backlink-autofill/
```

The public repository must not contain private submitter data, Google Spreadsheet IDs, browser sessions, generated platform passwords, or private project assets.

## Shared control plane

All projects use one private Google Spreadsheet. Its ID is stored once at:

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

- one control-plane file is shared by every project;
- project rows are isolated by exact `项目ID`;
- Spreadsheet ID is private and never committed;
- plugin reinstall preserves existing config;
- batch size is per invocation, never a daily quota/schedule.

## One shared submitter profile

```text
~/.backlink-autofill/submitter-profile.json
```

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

- one reusable human/operator identity for all projects;
- subsequent installs preserve it;
- passwords are never stored here.

## Dedicated backlink-platform credential store

Passwords generated specifically for backlink-platform accounts live only at:

```text
~/.backlink-autofill/credentials/
```

This store is shared by platform/domain, not by project, because the same operator account can be reused across projects.

Rules:

1. A confirmed **new backlink-platform account** may receive an independently generated password via `create_or_reuse`.
2. An existing backlink-platform login may use `existing_only`; if no stored credential exists, no password is invented.
3. Google, email, GitHub, and other primary-account passwords are not imported/read into this store.
4. Credential directory permissions are `0700`; credential files are `0600` where supported.
5. Raw password values never go into chat, Google Sheets, project data, checkpoints, recipes, action JSON, or CLI/browser evidence output.
6. Browser `credential_fill` resolves the password by the **current page domain** directly from this local store.
7. Plugin reinstall preserves the credential directory and all existing site credentials.

The store intentionally uses local plaintext protected by filesystem permissions because these credentials are for independently generated backlink-platform accounts, not primary user accounts. This is an explicit product trade-off for unattended execution.

## Per-project isolation

Every project's private material lives under:

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

Hard isolation rules:

1. Explicit selected project ID determines the only project directory the AI may use.
2. The same project ID is the only `项目外链管理` row set the run may mutate.
3. Missing project data/assets must not come from sibling project directories.
4. Updating project A must preserve project B.
5. Derived target-site images stay inside the selected project directory.
6. Originals are preserved.

## Browser/runtime data

The installer preserves these shared directories:

```text
~/.backlink-autofill/
├── browser-profile/   # persistent automation browser state
├── runtime/           # project/row checkpoints and handoff state
├── recipes/           # domain-level selectors/flow knowledge
└── credentials/       # locally generated backlink-platform credentials
```

Rules:

- `runtime/` checkpoints are project/row scoped and never persist secrets;
- `recipes/` are domain-level and contain no project marketing copy or credential values;
- `credentials/` is the only intentional password persistence surface;
- CAPTCHA/2FA/security-challenge solutions are never persisted.

## Install/update invariant

Given:

```text
~/.backlink-autofill/
├── submitter-profile.json
├── control-plane.json
├── credentials/
├── browser-profile/
├── runtime/
├── recipes/
└── projects/
    ├── quick-iching/
    └── project-b/
```

Plugin reinstall must preserve every private item above. Updating a Quick I Ching asset pack may change only `projects/quick-iching/` and must preserve the shared profile, control plane, credentials, browser/runtime/recipes, and sibling projects.

## Runtime resolution order

For one submission run:

1. explicit selected project ID;
2. shared control plane;
3. reviewed public project profile;
4. shared submitter profile;
5. selected project's private assets only;
6. selected project's exact Sheet rows;
7. platform row joined from `外链总表` by `外链ID`;
8. domain recipe if valid;
9. domain credential metadata/value only inside the credential-aware browser runtime when the login/registration policy permits it.

No sibling-project or other-project-row fallback is allowed.