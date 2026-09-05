# Backlink Submission Agent v2 — Design

Date: 2026-09-05
Status: approved and under implementation

## Goal

Evolve Backlink Autofill into a project-isolated Codex submission agent that reads a shared Google Sheets queue, processes at most 100 pending rows per invocation, runs ordinary website work headlessly, requests human takeover only for genuine blockers, and writes evidence-backed execution state back to the queue.

## Scope boundary

Current implementation starts from an already-populated control Spreadsheet. Discovery and the logic that creates project rows are separate follow-up work.

In scope:

1. explicit project selection;
2. structured Google Sheets queue reads/writes;
3. exact project-row isolation by `项目ID`;
4. up to 100 `待提交` rows per invocation;
5. shared submitter profile plus selected-project-only assets;
6. persistent headless browser execution;
7. autonomous ordinary final submission when no human-only condition exists;
8. headed human takeover for genuine blockers;
9. evidence-backed project status updates;
10. verified platform-fact enrichment of the master tab after the execution path is proven;
11. reusable domain recipes.

Out of scope for this implementation:

- discovering new backlink opportunities;
- redesigning the discovery Skill in the same change;
- scheduled/daily execution;
- Semrush/DR/DA gating;
- pre-researching Follow/Nofollow, login method, price, AI-only status, or approval time when execution can determine them more reliably.

## Core principles

- **Submit instead of over-screening.** Discovery does minimal junk/dead/malicious filtering; execution is the primary validation mechanism.
- **Unknown stays blank.** Platform facts are written only when directly observed.
- **One control plane, strict project isolation.** All projects share one Spreadsheet, but a selected-project run may touch only rows whose `项目ID` exactly matches that project.
- **Shared identity, isolated project data.** Personal identity is global; project facts/assets are project-specific.
- **Autonomous by default.** Ordinary safe submissions may include the final Submit action automatically.
- **Human only on exception.** Security challenges, payment, unusual authorization, or missing facts require human takeover.
- **Evidence before status.** No success-like state is written from model narration alone.
- **Run-based, not time-based.** Default batch size is 100 per invocation. There is no scheduler or daily quota.

## Google Sheets topology

One private Google Spreadsheet is the shared control plane for all projects. Its ID is stored locally in `~/.backlink-autofill/control-plane.json` and is never committed.

It has exactly two canonical tabs.

### `外链总表`

Global platform/opportunity facts. Exact headers:

`外链ID | 平台域名 | 提交入口 | 发现来源 | 发现时间 | 基础状态 | 基础排除原因 | 实测免费 | 实测需登录 | 实测登录方式 | 实测限制 | 实测链接属性 | 最后验证时间 | 平台备注`

Discovery-stage finite status:

- `候选`
- `已排除`
- `失效`

Observed fields remain blank until directly verified. Finite observed values include:

- `实测免费`: `免费 / 非免费 / 混合`
- `实测需登录`: `需要 / 不需要`
- `实测链接属性`: `Follow / Nofollow / UGC / Sponsored / 混合`

`发现来源` is provenance only, such as Google search, competitor backlinks, a directory list, community recommendation, or manual entry. It is not a submission gate.

### `项目外链管理`

All projects share this execution table. Exact headers:

`项目ID | 外链ID | 平台域名 | 状态 | 尝试次数 | 最近操作时间 | 目标URL | 结果链接 | 原因/备注 | 证据摘要`

Status values:

- `待提交`
- `处理中`
- `已提交`
- `审核中`
- `已排期`
- `已上线`
- `需人工`
- `失败`
- `不适用`

The queue predicate for a selected project is:

```text
项目ID == <selected-project-id>
AND 状态 == 待提交
```

Read at most 100 matching rows per invocation by default.

The project table deliberately does not duplicate submit URLs, SEO copy, keywords, project name, separate submitted/live timestamps, or platform-wide facts. Join `外链总表` by `外链ID` for platform data; load marketing/product facts from the selected project profile.

## Shared private configuration

### Control plane

`~/.backlink-autofill/control-plane.json`

```json
{
  "schema_version": 1,
  "spreadsheet_id": "",
  "master_sheet": "外链总表",
  "project_sheet": "项目外链管理",
  "default_batch_size": 100
}
```

This file is shared by every project and preserved across plugin reinstalls.

### Shared submitter profile

`~/.backlink-autofill/submitter-profile.json`

One reusable personal identity/contact profile for every project. Passwords are never stored.

### Per-project data

`~/.backlink-autofill/projects/<project-id>/`

Only the explicitly selected project's data/assets may be read. Never inspect sibling projects as fallback.

### Runtime

```text
~/.backlink-autofill/
├── browser-profile/
├── runtime/
└── recipes/
```

All are preserved across reinstall. They must not intentionally store passwords or security-challenge solutions.

## Google Sheets execution boundary

Sheets are accessed through the Google Drive/Sheets connector declared by the Codex plugin. Browser automation must never click spreadsheet cells.

For every selected-project mutation:

1. resolve the private control Spreadsheet;
2. read exact tab metadata/headers;
3. filter rows by exact selected `项目ID`;
4. preserve original row identity;
5. re-read the target row immediately before a state-changing write when concurrent change is possible;
6. write only that row;
7. re-read and verify the written values.

No other project's row may be mutated.

## Execution state machine

Internal state names may remain English in code, but Google Sheet values are the Chinese canonical values above.

Primary transitions:

- `待提交 -> 处理中`
- `处理中 -> 已提交 | 审核中 | 已排期 | 已上线 | 需人工 | 失败 | 不适用`
- `需人工 -> 处理中` after human intervention
- `已提交 | 审核中 | 已排期 -> 已上线` after later verified evidence
- `失败 -> 待提交` only by explicit retry action/policy

`尝试次数` increments only when a real browser attempt starts. `最近操作时间` changes when execution/status changes. `原因/备注` records concise blocker/failure/incompatibility context. `证据摘要` records browser-observed evidence supporting the state.

## Browser execution boundary

The website executor is a real local browser automation component, not narrative prompting.

Target design:

- persistent profile under `~/.backlink-autofill/browser-profile/`;
- headless by default;
- compact interactive DOM/form extraction rather than sending full pages when possible;
- support navigation, form inspection, text/select/file input, reversible actions, final Submit, and read-back evidence;
- reuse domain recipes from `~/.backlink-autofill/recipes/`;
- reopen the same persistent profile visibly for human takeover when needed.

## Autonomous final submission

The old universal `human must click final Submit` rule is removed.

The agent may automatically execute the final Submit/Publish/Send-for-review action when all are true:

- ordinary backlink/listing/profile submission;
- no payment is required;
- no CAPTCHA, Cloudflare, 2FA, passkey, SMS/phone verification, or similar challenge is present;
- no unusual legal/authorization judgment is required;
- all required facts come from approved project/shared data;
- resulting browser state can be read back.

Otherwise move to `需人工` or another evidence-supported terminal state.

## Human takeover

Human-only examples:

- CAPTCHA / slider / Cloudflare challenge;
- 2FA / passkey / SMS / phone verification;
- manual email verification that cannot safely be automated;
- payment/paid-plan choice;
- unusual terms/authorization requiring judgment;
- missing required factual data;
- browser security/access block.

On takeover:

1. save a local checkpoint;
2. write `需人工`, a concrete `原因/备注`, and evidence to the exact project row;
3. reopen the same persistent browser profile visibly when technically possible;
4. restore the target/reversible form state;
5. tell the user only what action is required;
6. resume automation after the human step.

Never solve or bypass security controls.

## Recipe cache and token strategy

Save verified reusable platform behavior under `~/.backlink-autofill/recipes/<domain>.json` without passwords or project-specific copy.

Long-term token savings come primarily from:

1. structured Sheets reads/writes instead of spreadsheet UI automation;
2. compact interactive DOM snapshots;
3. reusable domain recipes;
4. deeper model reasoning only for new/changed/ambiguous sites.

Headless versus visible browser mode is not itself the primary token lever.

## Truthfulness contract

- `处理中` requires a real execution start/checkpoint.
- `已提交` requires actual final submission plus resulting browser evidence.
- `审核中` requires explicit platform review/queue evidence.
- `已排期` requires explicit scheduled/launch evidence.
- `已上线` requires a verified resulting/public listing state.
- `失败` requires a concrete failure reason/evidence.
- `不适用` requires an observed incompatibility with the selected project.
- `需人工` requires a concrete human-only blocker.

Narrative intention is never execution evidence.

## Follow-up discovery work

After the execution path is proven, separately update the discovery Skill so it:

1. finds candidates;
2. normalizes and deduplicates before writing;
3. rejects only obvious junk/dead/malicious candidates cheaply;
4. writes minimal rows to `外链总表` and corresponding project queue rows;
5. does not use Semrush/authority/Follow status as a submission gate;
6. lets real submission progressively enrich the verified platform facts in `外链总表`.
