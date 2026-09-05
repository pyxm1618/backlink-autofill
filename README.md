# backlink-autofill

`backlink-autofill` is a **Codex plugin/Skill** for executing backlink submissions from a shared Google Sheets control queue. It uses the model already available in the user's signed-in Codex/ChatGPT plan and does **not** require a separate LLM API, OpenRouter account, or model API key.

## Current v2 workflow

```text
explicit project
→ read that project's 待提交 rows from Google Sheets
→ process at most 100 rows per invocation
→ run ordinary website work headlessly
→ create/reuse a dedicated site password when a new backlink account needs one
→ submit automatically when the flow is ordinary and safe
→ write evidence-backed status back to the exact project row
→ continue
```

**Headless is the default.** Automation runs via a persistent Chrome CDP session (`http://127.0.0.1:9222`, or `BACKLINK_BROWSER_CDP_URL`) reusing a single persistent browser context, avoiding per-task browser spawning:
- **Terminal task tab cleanup**: When an ordinary task reaches a terminal state (`已提交`, `审核中`, `已排期`, `已上线`, `失败`, `不适用`) and confirms Sheet exact-row read-back, its browser tab is automatically closed;
- **Non-blocking HUMAN_PENDING**: If a genuine blocker (CAPTCHA, 2FA, SMS, phone, payment) or unresolvable verification occurs, the task enters `需人工` and preserves its tab in the persistent Chrome window. **The batch does NOT stop**—subsequent tasks continue execution immediately;
- **Best-effort pending cleanup**: When a pending task is resumed and reaches a terminal state, the system attempts an external CDP close on that tab. Cleanup errors do not pollute or revert the confirmed terminal state.

**Final submit may be automatic.** The agent does not stop merely because a button says Submit, Publish, Launch, Post, Create Listing, or Send for Review. Genuine human-only blockers remain CAPTCHA/Cloudflare, 2FA/passkey/SMS verification, payment, unusual authorization, missing factual information, or an unauthenticated state that local site credentials cannot resolve.

**Existing Account ≠ Existing Submission & Preflight Gate.** Stored site credentials justify attempting login, not proof of platform account existence. Once authenticated, the agent strictly runs **Existing Submission Preflight** (`detect_existing_project_submission`) on the listings/dashboard view:
- `FOUND`: The project already exists—Final Submit is strictly forbidden;
- `UNKNOWN`: Status is ambiguous—halts safely to `需人工` without duplicate submission;
- `NOT_FOUND`: Only then proceeds with submission.

**Host-agnostic EMAIL_OTP & Ephemeral Stdin.** For email verification codes, the system automatically checks host mail capabilities:
- In **Codex**, via the authorized Gmail connected app;
- In **Google Antigravity**, via the authorized Gmail MCP (`gmail_search`, `gmail_get_message`);
- Both share the universal Core Resolver (`email_otp_resolver.py`) with strict platform matching and IdP protection (Google/GitHub/payment auth emails rejected);
- The OTP is passed via **ephemeral child process `stdin`** into CLI memory—it **never** touches argv, Google Sheets, checkpoints, pending records, recipes, or logs.

**Evidence Contract & ProductionSheetGate.** Google Sheets is not manipulated through the browser. Structured reads and writes go through the official Google Drive/Sheets capability, guarded by `ProductionSheetGate`:
- `实测链接属性` strictly requires live DOM inspection of target `<a>` tag `rel` attribute;
- `结果链接` strictly requires positive verification of unauthenticated public accessibility;
- Every Sheet write must be verified by an immediate **exact-row read-back**.

## Shared Google Sheets control plane

All projects use one Spreadsheet with two tabs.

### `外链总表`

Platform-level discovery and execution facts:

```text
外链ID | 平台域名 | 提交入口 | 发现来源 | 发现时间 | 基础状态 | 基础排除原因 |
实测免费 | 实测需登录 | 实测登录方式 | 实测限制 | 实测链接属性 | 最后验证时间 | 平台备注
```

`发现来源` is only provenance: Google search, competitor backlink discovery, a directory list, manual input, etc. It is not a submission gate. Unknown observed facts stay blank until actually verified.

### `项目外链管理`

All project execution rows share this tab and are strictly isolated by `项目ID`:

```text
项目ID | 外链ID | 平台域名 | 状态 | 尝试次数 | 最近操作时间 |
目标URL | 结果链接 | 原因/备注 | 证据摘要
```

Statuses:

```text
待提交 | 处理中 | 已提交 | 审核中 | 已排期 | 已上线 | 需人工 | 失败 | 不适用
```

Queue predicate:

```text
项目ID == explicitly selected project
AND 状态 == 待提交
```

Default limit: **100 rows per invocation**. There is no daily quota, cron, scheduler, or timed task requirement.

## Private data model

### One shared submitter profile

One shared submitter profile is reused by every project:

```text
~/.backlink-autofill/submitter-profile.json
```

### One shared control-plane config

```text
~/.backlink-autofill/control-plane.json
```

Example:

```json
{
  "schema_version": 1,
  "spreadsheet_id": "<private spreadsheet id>",
  "master_sheet": "外链总表",
  "project_sheet": "项目外链管理",
  "default_batch_size": 100
}
```

### Dedicated local site credentials

Backlink-platform passwords generated by this system live only under:

```text
~/.backlink-autofill/credentials/
```

Rules:

- a **confirmed new backlink-platform account** may use a generated independent password;
- the password is generated locally with Python `secrets`, stored per platform domain, and reused for that platform later;
- credential directory is `0700`; credential files are `0600`;
- the raw password does **not** go into chat, Google Sheets, project data, checkpoints, recipes, logs, or browser action JSON;
- the browser uses `credential_fill`, which resolves the secret directly from the local store and returns only non-secret verification evidence;
- `create_or_reuse` is allowed only for a confirmed new account registration flow;
- `existing_only` is used for login and never invents a new password;
- Google/email/GitHub/other primary-account passwords are never imported into this store.

This means a routine free directory that asks the agent to create Password + Confirm Password no longer needs to interrupt the user merely for password creation.

### Per-project assets remain isolated

```text
~/.backlink-autofill/
├── submitter-profile.json
├── control-plane.json
├── credentials/
├── browser-profile/
├── runtime/
├── recipes/
└── projects/
    ├── <project-a>/
    │   ├── assets.json
    │   ├── assets/
    │   └── source/
    ├── project-b/
    └── project-c/
```

Rules:

- shared submitter data is configured once;
- installing/updating preserves the shared profile, control-plane config, credentials, browser state, recipes, runtime state, and sibling projects;
- project logos, screenshots, project contact/social data, source files, and derived images stay under `projects/<project-id>/`;
- the AI **must never borrow assets from a sibling project**;
- credential values never belong in project directories, checkpoints, or recipes.

See `docs/private-data-model.md` and `plugins/backlink-autofill/references/project-sheet-contract.md` for the canonical contracts.

## Install for personal Codex use

From the repository/branch:

```bash
python3 scripts/install-personal.py
python3 -m pip install -r plugins/backlink-autofill/scripts/requirements.txt
```

The installer:

- installs the Codex plugin into `~/plugins/backlink-autofill`;
- safely updates the personal marketplace entry;
- creates missing private runtime directories, including `credentials/`;
- preserves existing profile, control-plane config, credentials, browser profile, checkpoints, recipes, and every project directory.

The second command installs Playwright `1.62.0`. On systems where Python is externally managed (PEP 668), use an appropriate virtual environment or the local environment policy already chosen for that machine rather than silently changing system Python policy.

Configure the shared Spreadsheet once:

```bash
python3 scripts/configure-control-plane.py \
  --spreadsheet-id '<YOUR_SPREADSHEET_ID>'
```

Restart/reload Codex after installing/updating.

## Run

Normal invocation:

```text
$backlink-autofill
当前项目：<项目名称或项目ID>。
```

Optional smaller batch:

```text
$backlink-autofill
当前项目：<项目名称或项目ID>。
这次先处理 5 条。
```

The agent reads `项目外链管理`, selects only the current project's eligible rows, and processes them in Sheet order. Ordinary successful rows run without opening a visible browser or asking for per-row confirmation. Upon reaching a terminal status and writing back to Sheet with exact-row confirmation, the corresponding task tab is automatically closed to keep browser resources bounded.

For a new backlink-platform account, the action plan may include:

```text
credential_fill
credential = site_password
mode = create_or_reuse
```

For an existing login, it may use `existing_only` only when this system already has a credential for the current domain/account. Stored credentials justify attempting login, not proof that the account exists. If explicit account not found is returned, it safely falls back to signup.

Before any irreversible Final Submit, the agent performs **Existing Submission Preflight** against the authenticated listings/dashboard. If the project already exists (`FOUND`), Final Submit is strictly blocked; if ambiguous (`UNKNOWN`), it halts to `需人工`.

If an email verification code is required, the agent first attempts automated, host-agnostic EMAIL_OTP resolution using the host's mail capability (Codex Gmail connected app or Antigravity Gmail MCP) via the shared Core Resolver and ephemeral stdin injection. If automated mail retrieval is unavailable or an unresolvable blocker occurs (e.g. CAPTCHA, 2FA, SMS), the current row becomes `需人工`, its browser tab is preserved in the persistent Chrome window, and a durable `human_pending` record is stored. The batch does NOT pause—subsequent tasks continue execution immediately.

When human-pending tasks are completed and resumed, reaching a confirmed terminal state triggers best-effort cleanup of the preserved tab without affecting the recorded status.

## Evidence and truthfulness

Success-like states require real evidence:

- `已提交`: final submission occurred and receipt/result evidence was observed;
- `审核中`: site explicitly reports review/moderation pending;
- `已排期`: site explicitly reports scheduled publication/launch;
- `已上线`: listing/result is actually reachable;
- `不适用`: real flow exposes an incompatibility such as AI-only eligibility or paid-only submission under free-run policy;
- `需人工`: human-only blocker or ambiguous post-submit state makes automatic continuation unsafe.

If final Submit was clicked but outcome is ambiguous, the agent must not retry automatically; it records `需人工` to avoid duplicates.

## Domain recipes and token use

Verified stable flows may save domain recipes under:

```text
~/.backlink-autofill/recipes/<domain>.json
```

Recipes contain navigation/selectors/success indicators, never credentials or project copy. Later projects can reuse known flows and reduce repeated model analysis.

## Repository layout

```text
.agents/plugins/marketplace.json
plugins/backlink-autofill/
  .app.json
  .codex-plugin/plugin.json
  skills/backlink-autofill/SKILL.md
  references/project-registry.json
  references/project-sheet-contract.md
  references/projects/quick-iching.md
  scripts/browser_cli.py
  scripts/browser_runtime.py
  scripts/browser_handoff.py
  scripts/credential_store.py
  scripts/execution_state.py
  scripts/requirements.txt
  tests/
docs/private-data-model.md
scripts/configure-control-plane.py
scripts/install-personal.py
scripts/validate-plugin.mjs
```

## Validation

```bash
node scripts/validate-plugin.mjs
python3 plugins/backlink-autofill/tests/test_execution_state.py -v
python3 plugins/backlink-autofill/tests/test_browser_runtime.py -v
```

GitHub Actions additionally installs isolated Chromium and runs headed handoff tests under Xvfb. CI validates code/runtime contracts; it does **not** prove a specific external site accepted a listing.

## Acceptance boundary

Before calling a real platform integration proven:

1. verify live Sheet read/write;
2. run a real selected-project target;
3. verify actual website mutation and final-result evidence;
4. verify exact project-row writeback and no sibling-row mutation;
5. verify human handoff when naturally required;
6. for password-registration flows, verify local credential creation/reuse without exposing the secret.

Do not describe an external submission as successful based only on CI/local fixtures.