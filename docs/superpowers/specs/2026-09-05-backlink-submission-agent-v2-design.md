# Backlink Submission Agent v2 — Design

Date: 2026-09-05
Status: approved for implementation planning

## Goal

Evolve the current single-target autofill workflow into a project-isolated submission agent that starts from the existing project execution table, processes up to 100 pending targets per invocation, runs ordinary work headlessly, opens a visible browser only when human intervention is required, and writes verified execution state back to the project table.

## Scope for the first implementation

This implementation begins at **reading the existing project execution table**.

In scope:

1. resolve the explicitly selected project;
2. read the existing Google Sheet execution queue through the Google Drive/Sheets connector;
3. filter rows to the selected project only;
4. select up to 100 pending rows per invocation;
5. execute backlink submissions in a persistent local browser profile, headless by default;
6. automatically complete the final submission when the flow is ordinary and no human-only condition is present;
7. checkpoint and open a visible browser when human intervention is required;
8. write the verified execution outcome back to the existing project execution row;
9. reuse the shared submitter profile and only the selected project's private assets;
10. cache reusable domain recipes after verified successful runs.

Explicitly out of scope for this implementation:

- backlink discovery;
- changing the discovery skill;
- creating or populating project rows from discovery results;
- redesigning the master backlink database;
- synchronizing newly observed platform facts into the current master/channel table.

Master-fact synchronization is deliberately deferred because the current master/channel table contains legacy researched values such as authority, DoFollow and free-status claims that are not guaranteed to be execution-verified. The master schema and discovery write path will be redesigned together in a separate task so verified observations cannot be mixed with old assumptions.

## Current Google Sheet compatibility contract

The current live execution source is the Google Spreadsheet titled:

`外链管理总控表`

Current execution tab:

`多项目外链进度与排期表`

The tab currently contains multiple projects in one table. Project isolation in this phase is therefore logical rather than physical: the agent must filter by the exact `项目名称` value for the explicitly selected project and must never mutate another project's row.

Current columns A:L are:

1. `项目名称`
2. `外链平台`
3. `当前状态`
4. `提交日期`
5. `预计上线 / 计划 Launch 日期`
6. `履约/要求配合状态`
7. `实际落地链接 (Live URL)`
8. `实际是否 DoFollow`
9. `Google 收录`
10. `被推广目标页 (Target URL)`
11. `锚文本 / 关键词`
12. `账号 / 备注`

The first implementation must not require this table to be migrated before use.

The current workbook has no Quick I Ching rows yet. Therefore code/CI tests use fixtures modeled on the live schema, and real Quick I Ching queue E2E begins only after the discovery/write-side workflow has produced at least one Quick I Ching row.

## Queue selection

The Google Sheet must be accessed through the structured Google Drive/Sheets connector, not by browser-clicking spreadsheet cells.

Selection rules:

1. explicit project selection remains mandatory;
2. search/read only the execution tab;
3. filter to rows whose `项目名称` exactly matches the configured project queue name;
4. only rows with `当前状态 = 1-待提交 (To Submit)` are eligible for automatic processing;
5. preserve sheet row numbers because status writes must target the original row;
6. take at most 100 eligible rows per invocation by default;
7. a user may request a smaller batch for that invocation;
8. there is no daily quota, scheduler, cron, or timed task requirement.

If a project has zero eligible rows, stop cleanly and report an empty queue; do not borrow rows from another project.

## Current-sheet status compatibility

Existing statuses observed in the live table:

- `1-待提交 (To Submit)` → internal `PENDING`
- `2-排队审核中 (In Review)` → internal `UNDER_REVIEW`
- `3-已排期待Launch (Scheduled)` → internal `SCHEDULED`
- `4-已成功上线 (Live)` → internal `LIVE`

The submission agent additionally needs these execution outcomes. Until the discovery/write-side table schema is redesigned, write them as explicit text in the same `当前状态` cell:

- `处理中 (In Progress)` → internal `IN_PROGRESS`
- `已提交待确认 (Submitted)` → internal `SUBMITTED`
- `需人工 (Needs Human)` → internal `NEEDS_HUMAN`
- `失败 (Failed)` → internal `FAILED`
- `不适用 (Not Applicable)` → internal `NOT_APPLICABLE`

Do not renumber or reinterpret the existing 1/2/3/4 legacy labels.

Use `账号 / 备注` for concise compatibility-mode evidence/reason text until a future table migration introduces dedicated execution fields. Do not overwrite useful existing notes; append a timestamped agent entry.

Use `提交日期` only when a final submission was actually completed. Use `实际落地链接 (Live URL)` only when a public/result URL is actually observed. Do not guess DoFollow or Google indexing values.

## State machine

Internal states:

- `PENDING`
- `IN_PROGRESS`
- `SUBMITTED`
- `UNDER_REVIEW`
- `SCHEDULED`
- `LIVE`
- `NEEDS_HUMAN`
- `FAILED`
- `NOT_APPLICABLE`

Primary transitions:

- `PENDING -> IN_PROGRESS`
- `IN_PROGRESS -> SUBMITTED | UNDER_REVIEW | SCHEDULED | LIVE | NEEDS_HUMAN | FAILED | NOT_APPLICABLE`
- `NEEDS_HUMAN -> IN_PROGRESS` after the human step is completed
- `SUBMITTED | UNDER_REVIEW | SCHEDULED -> LIVE` after later verified evidence
- `FAILED -> PENDING` only by an explicit retry action/policy

The durable browser/runtime checkpoint is stored locally, not encoded into spreadsheet cells.

If a previous run left a row as `处理中 (In Progress)` but there is no matching active local checkpoint, the agent must not blindly continue or mark success. It should recover conservatively to `1-待提交 (To Submit)` when no mutation evidence exists, or to `失败 (Failed)` when evidence shows an incomplete/failed attempt.

## Private runtime configuration

Reusable personal identity remains global:

`~/.backlink-autofill/submitter-profile.json`

Project assets remain isolated:

`~/.backlink-autofill/projects/<project-id>/`

Add per-project private execution configuration:

`~/.backlink-autofill/projects/<project-id>/execution.json`

Schema:

```json
{
  "schema_version": 1,
  "project_id": "quick-iching",
  "queue": {
    "spreadsheet_id": "",
    "sheet_name": "多项目外链进度与排期表",
    "project_name": "Quick I Ching"
  },
  "default_batch_size": 100
}
```

Private spreadsheet IDs are never committed to the public repository.

Global local runtime paths:

```text
~/.backlink-autofill/
├── browser-profile/
├── runtime/
│   └── <project-id>/
└── recipes/
```

`runtime/` contains transient per-row checkpoints and evidence metadata. `recipes/` contains domain-level reusable navigation/form mappings. Neither may contain passwords.

## Google connector boundary

Google Sheets queue reads/writes use the official Google Drive connector binding. Browser automation must not be used to manipulate spreadsheet cells.

The connector workflow must:

1. read spreadsheet metadata and exact visible sheet name;
2. use bounded row searches/reads;
3. preserve original row numbers;
4. re-read the target row before writing when its state could have changed;
5. write only the selected project's exact row;
6. verify the written cell values after the update.

This separation keeps spreadsheet operations deterministic and reduces browser/token overhead.

## Browser execution boundary

The browser execution layer is a real local automation component, not narrative instructions.

Use Playwright Python `1.62.0` with a dedicated persistent browser profile under `~/.backlink-autofill/browser-profile/`.

The browser layer must expose deterministic operations for Codex to call, including:

- open/navigate;
- inspect interactive form state;
- fill text;
- select options;
- click reversible navigation/actions;
- upload a selected-project file;
- read back field/page state;
- click final submit when allowed;
- capture checkpoint/evidence;
- reopen the same persistent profile in visible mode for human takeover.

For new/unknown sites, Codex reasons over a compact interactive DOM/form snapshot rather than the full page when possible.

## Autonomous submission policy

The old universal `human must click final Submit` rule is removed.

The agent may execute final Submit/Publish/Send-for-review automatically when all are true:

- it is an ordinary backlink/listing/profile submission;
- no payment is required;
- no CAPTCHA, 2FA, passkey, SMS/phone verification or similar security challenge is present;
- no unusual legal/authorization decision is presented;
- all submitted facts come from approved project/shared data;
- the browser can read back a clear resulting state.

If these conditions are not met, do not guess or bypass. Move the row to `NEEDS_HUMAN` or another evidence-supported state.

## Headless default and human takeover

Normal execution uses the persistent automation browser profile in headless mode.

Human takeover conditions include:

- CAPTCHA / slider / Cloudflare challenge;
- 2FA / passkey / SMS / phone verification;
- manual email verification that cannot be automated safely;
- payment/paid plan choice;
- unusual terms/authorization requiring judgment;
- missing required factual information;
- browser security/access block.

On takeover:

1. save a local checkpoint with project ID, sheet row number, domain, URL, form/evidence state and reason;
2. write `需人工 (Needs Human)` plus a concise appended note to the exact project row;
3. close the headless context cleanly;
4. reopen the same persistent browser profile visibly;
5. restore/navigate to the blocked target and restore reversible form state when necessary;
6. tell the user only what intervention is required;
7. after the user completes the human step, continue automation from the checkpoint.

The implementation must not attempt to solve or bypass security challenges.

## Project/data isolation

- Explicit project selection is mandatory.
- Read queue rows only for the selected project name.
- Write only the selected project's exact row numbers.
- Load shared identity only from `submitter-profile.json`.
- Load project facts/assets only from the selected public profile and `projects/<project-id>/`.
- Never search sibling project directories for missing assets/facts.
- Never use another project's sheet row, target URL, anchor, account note or result URL.

## Domain recipe cache

After a verified successful run, save reusable platform-level behavior to:

`~/.backlink-autofill/recipes/<canonical-domain>.json`

Recipes may store selectors, navigation steps, login entry points, upload mappings and success indicators, but not passwords or project-specific text.

On later runs:

1. try the valid recipe first;
2. verify selectors/page state before mutating;
3. fall back to fresh compact DOM inspection if the recipe is stale;
4. refresh the recipe only after a verified successful flow.

Recipe reuse is the primary long-term token optimization.

## Truthfulness/evidence contract

No state transition is based only on model narration.

- `IN_PROGRESS` requires an execution start/checkpoint.
- `SUBMITTED` requires an actual final submission action plus resulting page evidence.
- `UNDER_REVIEW` requires explicit platform evidence of review/queue status.
- `SCHEDULED` requires explicit platform evidence of a scheduled/launch state.
- `LIVE` requires an actually reachable/result listing state.
- `FAILED` requires recorded failure evidence/reason.
- `NOT_APPLICABLE` requires an observed incompatibility with the selected project.

Spreadsheet writes must be verified by re-read.

## Follow-up work deliberately separated

After this execution path is proven, handle these in a separate design/implementation cycle:

1. simplify backlink discovery to find + normalize + deduplicate + obvious-junk rejection;
2. redesign the master backlink schema so legacy researched claims and execution-verified facts are distinct;
3. change discovery/project-table write logic accordingly;
4. add verified platform-fact propagation from execution into the redesigned master table;
5. optionally migrate from the current multi-project execution tab to physically separate project spreadsheets if still valuable.

This separation prevents the execution build from being blocked by a larger database/discovery migration.