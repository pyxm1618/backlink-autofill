# Backlink Submission Agent v2 Phase 1 — As-Built Plan

Date: 2026-09-05
Status: implementation complete through CI/local-browser acceptance; real external-site E2E still required

## Goal

Build a project-isolated Codex backlink submission agent that:

- starts from the existing shared Google Sheets control plane;
- reads only the explicitly selected project's `待提交` rows;
- processes at most 100 rows per invocation;
- executes ordinary website work headlessly;
- automatically performs ordinary final submission when safe;
- opens a visible browser only for genuine human-only blockers;
- writes evidence-backed execution state to the exact project row;
- enriches master platform facts only from direct observation;
- uses no separate LLM API.

Discovery and project-row creation remain a separate workflow.

## Canonical architecture

```text
Codex / current ChatGPT model
        |
        +-- Google Drive/Sheets connector
        |      -> shared control Spreadsheet
        |           |- 外链总表
        |           `- 项目外链管理
        |
        +-- backlink-autofill Skill
        |      -> project selection / policy / mapping / evidence rules
        |
        `-- local Playwright runtime
               -> persistent browser profile
               -> headless ordinary execution
               -> headed human handoff on exception
```

Google Sheets is never automated through browser clicks.

## Canonical Sheet contract

All projects share one Spreadsheet. Project isolation is by exact `项目ID`.

### `外链总表`

```text
外链ID | 平台域名 | 提交入口 | 发现来源 | 发现时间 | 基础状态 | 基础排除原因 |
实测免费 | 实测需登录 | 实测登录方式 | 实测限制 | 实测链接属性 | 最后验证时间 | 平台备注
```

`基础状态`:

```text
候选 | 已排除 | 失效
```

Observed values remain blank until directly verified.

### `项目外链管理`

```text
项目ID | 外链ID | 平台域名 | 状态 | 尝试次数 | 最近操作时间 |
目标URL | 结果链接 | 原因/备注 | 证据摘要
```

`状态`:

```text
待提交 | 处理中 | 已提交 | 审核中 | 已排期 | 已上线 | 需人工 | 失败 | 不适用
```

Queue predicate:

```text
项目ID == selected project ID
AND 状态 == 待提交
```

Default batch maximum: 100 rows per invocation. No daily limit, scheduler, cron, or timed task.

## Private runtime model

```text
~/.backlink-autofill/
├── submitter-profile.json       # one shared personal profile
├── control-plane.json           # one shared private Spreadsheet config
├── browser-profile/             # persistent browser state
├── runtime/                     # per-project/row checkpoints
├── recipes/                     # reusable domain recipes
└── projects/
    ├── quick-iching/
    ├── project-b/
    └── ...
```

Hard rule: selected-project facts/assets may come only from `projects/<project-id>/`; sibling project fallback is forbidden.

Passwords, passcodes, tokens, API keys, and security-challenge solutions are never stored in checkpoints, recipes, or browser action JSON.

---

## Step 1 — Bind Google Sheets and lock the schema

Implemented:

- Codex plugin declares the official Google Drive connector in `.app.json`.
- Plugin declares `Write` capability.
- `references/project-sheet-contract.md` fixes the exact two-tab Chinese schema.
- Validator rejects missing/obsolete schema assumptions.

Acceptance:

- plugin structural validator passes;
- live Spreadsheet metadata/header read matches the contract.

## Step 2 — Shared private control-plane configuration

Implemented:

- `scripts/configure-control-plane.py` writes:

```json
{
  "schema_version": 1,
  "spreadsheet_id": "<private>",
  "master_sheet": "外链总表",
  "project_sheet": "项目外链管理",
  "default_batch_size": 100
}
```

- config is shared by all projects;
- plugin reinstall preserves it;
- install also preserves shared profile, project directories, browser profile, runtime checkpoints, and recipes.

No per-project `execution.json` exists or is required.

## Step 3 — Deterministic state/checkpoint/recipe storage

Implemented in `plugins/backlink-autofill/scripts/execution_state.py`.

Responsibilities:

- Chinese Sheet status ↔ internal state mapping;
- atomic checkpoint writes;
- checkpoint project/row isolation;
- canonical domain recipe paths;
- recursive rejection of password/token/secret-like data.

Acceptance:

- unit tests cover round-trip, isolation, invalid identity, atomic writes, domain normalization, and sensitive-data rejection.

## Step 4 — Real headless browser runtime

Implemented in:

- `browser_runtime.py`
- `browser_cli.py`

Supported deterministic actions:

- inspect/navigate;
- fill;
- select;
- check;
- selected-project upload;
- click;
- submit;
- post-action snapshot/read-back.

Properties:

- persistent browser profile;
- compact interactive snapshot instead of full-page dumping when possible;
- sensitive field redaction/refusal;
- upload root confinement to selected-project assets;
- human-blocker detection;
- action evidence.

CI uses Playwright Chromium. Personal runtime defaults to installed Google Chrome.

## Step 5 — Headed human handoff

Implemented in `browser_handoff.py` and exposed through `browser_cli.py`:

```text
handoff-start
handoff-status
handoff-finish
```

Behavior:

1. headless execution stops on a human-only blocker;
2. current safe state is checkpointed;
3. headless browser closes and releases the persistent profile;
4. a detached headed browser opens the same profile;
5. only safe reversible actions may be replayed: `fill/select/check/upload`;
6. arbitrary click/submit is never replayed;
7. human completes the blocker;
8. final page state is captured for evidence and normal automation may resume.

CI runs the headed lifecycle under Xvfb.

## Step 6 — Turn the Skill into the queue executor

Implemented in `skills/backlink-autofill/SKILL.md`.

Per invocation:

1. require explicit project selection;
2. read `control-plane.json`;
3. validate live Sheet names/headers;
4. recover selected-project `处理中` rows conservatively;
5. select at most 100 exact-project `待提交` rows;
6. re-read exact row before mutation;
7. mark exact row `处理中`, increment attempts, verify write;
8. join `外链总表` by exact `外链ID`;
9. load only shared identity + selected-project profile/assets;
10. try domain recipe, otherwise compact browser inspection;
11. discover constraints through the real flow rather than pre-researching DR/DA/Follow/login/free status;
12. automatically submit ordinary safe/free flows;
13. hand off genuine human-only blockers;
14. classify result only from browser evidence;
15. update and re-read the exact project row;
16. enrich master facts only when directly observed;
17. save/refresh domain recipe after verified stable flow;
18. continue until batch exhausted or human handoff pauses the run.

## Step 7 — CI, documentation, and staged real acceptance

Implemented CI gates:

- plugin structure/manifest/schema validation;
- execution-state tests;
- Playwright dependency install;
- real headless Chromium fixture E2E;
- headed handoff fixture E2E under Xvfb;
- isolated-HOME installer/control-plane preservation tests.

Implemented documentation:

- current v2 README;
- private data model;
- Sheet contract;
- current design spec;
- this as-built plan.

### Live Google Sheet acceptance

Completed against the real control Spreadsheet:

1. verified exact two-tab metadata and headers;
2. wrote temporary master/project acceptance rows;
3. read them back;
4. updated exact project row `待提交 -> 处理中` and attempt count;
5. read back the exact mutation;
6. cleared the temporary rows;
7. re-read both tabs to confirm cleanup.

### Remaining real external-site acceptance

CI/local fixtures are not evidence that a real backlink platform accepted a listing.

Before calling v2 fully proven end-to-end, run from the user's installed Codex environment:

1. install/update plugin and Playwright runtime dependency;
2. configure the real private control-plane Spreadsheet ID locally;
3. ensure Quick I Ching shared profile/assets are installed;
4. put one real target into `外链总表` and one `quick-iching / 待提交` row into `项目外链管理`;
5. invoke `$backlink-autofill` for Quick I Ching with a one-row batch;
6. observe real website mutation/submission evidence;
7. verify exact Sheet state/result/evidence write-back;
8. verify no sibling project row changed;
9. when a genuine challenge naturally occurs, verify headed human takeover on the user's desktop.

Do not merge PR #2 or describe real external submission as proven until the real-site test succeeds.

## Current acceptance ledger

| Layer | Status |
|---|---|
| Plugin packaging / Google Drive binding | PASS |
| Shared Sheet schema contract | PASS |
| Live Sheet structured read/write round-trip | PASS |
| Shared profile / project isolation installer | PASS |
| State/checkpoint/recipe tests | PASS |
| Headless browser fixture E2E | PASS |
| Headed handoff fixture E2E | PASS |
| Autonomous queue Skill contract | PASS |
| Real external backlink submission | PENDING |
| Real desktop human handoff | PENDING until naturally triggered |

This ledger is intentionally evidence-based: untested external behavior remains `PENDING`, not assumed success.
