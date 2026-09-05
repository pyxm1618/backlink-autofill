# backlink-autofill

`backlink-autofill` is a **Codex plugin/Skill** for executing backlink submissions from a shared Google Sheets control queue. It uses the model already available in the user's signed-in Codex/ChatGPT plan and does **not** require a separate LLM API, OpenRouter account, or model API key.

## Current v2 workflow

The execution path is:

```text
explicit project
→ read that project's 待提交 rows from Google Sheets
→ process at most 100 rows per invocation
→ run ordinary website work headlessly
→ submit automatically when the flow is ordinary and safe
→ write evidence-backed status back to the exact project row
→ continue
```

**Headless is the default.** Website automation uses the plugin's Playwright runtime with one dedicated persistent browser profile under `~/.backlink-autofill/browser-profile/`.

**Final submit may be automatic.** The agent does not stop merely because a button says Submit, Publish, Launch, Post, Create Listing, or Send for Review. It stops and opens a visible browser only for a genuine human-only condition such as CAPTCHA/Cloudflare, 2FA/passkey/SMS verification, password entry, payment, unusual authorization, or missing factual information.

Google Sheets is not manipulated through the browser. The Codex plugin binds the official Google Drive/Sheets capability for structured queue reads and writes.

## Shared Google Sheets control plane

All projects use one Spreadsheet with two tabs:

### `外链总表`

Platform-level discovery and execution facts. Discovery writes only minimal candidate information; execution fills observed facts only when they are actually verified.

Current columns:

```text
外链ID | 平台域名 | 提交入口 | 发现来源 | 发现时间 | 基础状态 | 基础排除原因 |
实测免费 | 实测需登录 | 实测登录方式 | 实测限制 | 实测链接属性 | 最后验证时间 | 平台备注
```

`发现来源` means where the candidate was originally discovered, such as Google search, a directory list, competitor backlink discovery, or manual input. It is provenance only and does not affect submission decisions.

### `项目外链管理`

The execution queue for every project. Projects share this tab and are strictly isolated by `项目ID`.

```text
项目ID | 外链ID | 平台域名 | 状态 | 尝试次数 | 最近操作时间 |
目标URL | 结果链接 | 原因/备注 | 证据摘要
```

Canonical project statuses are:

```text
待提交 | 处理中 | 已提交 | 审核中 | 已排期 | 已上线 | 需人工 | 失败 | 不适用
```

The normal queue predicate is exactly:

```text
项目ID == explicitly selected project
AND 状态 == 待提交
```

The default limit is **100 rows per invocation**. There is no daily quota, cron, scheduler, or timed task requirement.

## Private data model

### One shared submitter profile

One shared submitter profile is reused by every project:

```text
~/.backlink-autofill/submitter-profile.json
```

A project must not create a duplicate personal profile.

### One shared control-plane config

The private Spreadsheet ID is stored locally once:

```text
~/.backlink-autofill/control-plane.json
```

Example shape:

```json
{
  "schema_version": 1,
  "spreadsheet_id": "<private spreadsheet id>",
  "master_sheet": "外链总表",
  "project_sheet": "项目外链管理",
  "default_batch_size": 100
}
```

### Per-project assets remain isolated

```text
~/.backlink-autofill/
├── submitter-profile.json
├── control-plane.json
├── browser-profile/
├── runtime/
├── recipes/
└── projects/
    ├── quick-iching/
    │   ├── assets.json
    │   ├── assets/
    │   └── source/
    ├── project-b/
    └── project-c/
```

Rules:

- The shared submitter profile is created once and reused across all projects.
- Installing/updating a project must not overwrite the existing shared profile or sibling projects.
- Project logos, screenshots, source files, project contact/social data, and derived image variants stay under `projects/<project-id>/`.
- The AI **must never borrow assets from a sibling project** when the selected project is missing something.
- Passwords, passcodes, tokens, and API keys are never stored in project data, checkpoints, recipes, or browser action JSON.
- Browser session/cookie state may be shared through the dedicated browser profile, while submitted project content remains project-isolated.

See `docs/private-data-model.md` and `plugins/backlink-autofill/references/project-sheet-contract.md` for the canonical contracts.

## Install for personal Codex use

From this repository/branch:

```bash
python3 scripts/install-personal.py
python3 -m pip install -r plugins/backlink-autofill/scripts/requirements.txt
```

The first command:

- installs the Codex plugin into `~/plugins/backlink-autofill`;
- safely adds/updates the personal plugin marketplace entry;
- creates missing private runtime directories;
- preserves an existing submitter profile, control-plane config, browser profile, recipes, checkpoints, and all project directories.

The second command installs the only browser-runtime Python dependency, Playwright `1.62.0`. The normal personal runtime uses the installed Google Chrome channel. CI installs Playwright Chromium separately for isolated browser tests.

Configure the shared control Spreadsheet once:

```bash
python3 scripts/configure-control-plane.py \
  --spreadsheet-id '<YOUR_SPREADSHEET_ID>'
```

This writes only local private configuration under `~/.backlink-autofill/control-plane.json`; the real Spreadsheet ID is intentionally not committed to the public repository.

Restart/reload Codex after installing/updating the plugin.

## Run

Normal invocation:

```text
$backlink-autofill
当前项目：Quick I Ching。
```

Optional smaller batch:

```text
$backlink-autofill
当前项目：Quick I Ching。
这次先处理 5 条。
```

The agent reads `项目外链管理`, selects only the current project's `待提交` rows, and processes them in Sheet order. Ordinary successful rows run without opening a visible browser and without asking for per-row confirmation.

If a human-only blocker occurs, the current row becomes `需人工`, the batch pauses, and the runtime reopens the **same persistent browser profile** visibly. After the human step is completed, the agent resumes from the saved checkpoint instead of starting the target over blindly.

## Evidence and truthfulness

Success-like states require real evidence:

- `已提交`: final submission action occurred and receipt/result evidence was observed;
- `审核中`: the site explicitly reports review/moderation pending;
- `已排期`: the site explicitly reports scheduled publication/launch;
- `已上线`: the listing/result is actually reachable;
- `不适用`: the real flow exposes an incompatibility such as AI-only eligibility for a non-AI project or paid-only submission under the current free-run policy;
- `需人工`: a human-only blocker or ambiguous post-submit state makes automatic continuation unsafe.

If final Submit was clicked but the outcome is ambiguous, the agent must not retry automatically; it records `需人工` to avoid duplicate submission.

## Domain recipes and token use

After a verified stable platform flow, the runtime can save a domain recipe under:

```text
~/.backlink-autofill/recipes/<domain>.json
```

Recipes contain reusable navigation/selectors/success indicators, not credentials or project copy. Later projects can reuse the known platform flow, reducing repeated page analysis and model token use.

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
  scripts/execution_state.py
  scripts/requirements.txt
  tests/
docs/private-data-model.md
scripts/configure-control-plane.py
scripts/install-personal.py
scripts/validate-plugin.mjs
```

## Validation

Structural validation:

```bash
node scripts/validate-plugin.mjs
```

Browser/state tests after Playwright is installed:

```bash
python3 plugins/backlink-autofill/tests/test_execution_state.py -v
python3 plugins/backlink-autofill/tests/test_browser_runtime.py -v
```

GitHub Actions additionally installs isolated Chromium and runs the headed human-handoff test under Xvfb. CI validates code/runtime contracts; it is **not** evidence that a specific real backlink website has accepted a real listing.

## Acceptance boundary

Before calling a real platform integration proven, run a staged real test:

1. verify the live Google Sheet headers and project-row read/write path;
2. run one real `待提交` target for the selected project;
3. verify actual website mutation and final-result evidence;
4. verify the exact Sheet row was updated and no sibling-project row changed;
5. separately test a human-blocker flow when one naturally occurs.

Do not describe a real external submission as successful based only on CI or local HTML fixtures.