# Canonical Backlink Sheet Contract

This file defines the canonical Google Sheets schema used by Backlink Submission Agent v2.

Do not commit a private Google Spreadsheet ID or URL here.

## Current physical topology

Current v2 uses one existing workbook with two tabs:

1. `外链总表` — global platform/opportunity facts.
2. `项目外链管理` — per-project execution queue and history.

The execution agent reads only rows whose `项目ID` exactly matches the explicitly selected project. It must never mutate another project's row.

Default execution batch size is **maximum 100 PENDING rows per invocation**. There is no daily quota, cron, scheduler, or calendar-based execution requirement.

## Tab: 外链总表

Headers, in exact order:

| Col | Header | Meaning |
| --- | --- | --- |
| A | 外链ID | Stable global backlink/opportunity ID |
| B | 平台域名 | Canonical platform domain |
| C | 提交入口 | Submission/listing entry URL |
| D | 来源 | Discovery source |
| E | 发现时间 | Discovery timestamp |
| F | 基础状态 | Minimal discovery state |
| G | 基础排除原因 | Only obvious junk/dead/malicious reject reason |
| H | 实测免费 | Execution-observed free/paid fact |
| I | 实测需登录 | Execution-observed login requirement |
| J | 实测登录方式 | Execution-observed login method(s) |
| K | 实测限制 | Execution-observed product/platform constraint |
| L | 实测链接属性 | Verified live-link rel behavior |
| M | 最后验证时间 | Last direct verification timestamp |
| N | 平台备注 | Platform-level notes only |

Allowed finite values:

- `基础状态`: `ACTIVE`, `REJECTED`, `DEAD`
- `实测免费`: `YES`, `NO`, `MIXED`, or blank when unknown
- `实测需登录`: `YES`, `NO`, or blank when unknown
- `实测链接属性`: `FOLLOW`, `NOFOLLOW`, `UGC`, `SPONSORED`, `MIXED`, or blank when unknown

Rules:

- Discovery only needs to fill the minimal discovery fields A:G.
- H:N stay blank until directly observed during submission or later verification.
- Unknown facts stay blank. Never guess.
- Project-specific states such as whether Quick I Ching was submitted do not belong here.

## Tab: 项目外链管理

Headers, in exact order:

| Col | Header | Meaning |
| --- | --- | --- |
| A | 项目ID | Stable project ID, e.g. `quick-iching` |
| B | 项目名称 | Human-readable project name |
| C | 外链ID | Foreign key to `外链总表.外链ID` |
| D | 平台域名 | Cached platform domain for readability/execution |
| E | 提交入口 | Submission/listing entry URL |
| F | 状态 | Canonical project execution state |
| G | 尝试次数 | Number of execution attempts |
| H | 最近尝试时间 | Last attempt timestamp |
| I | 提交时间 | Confirmed submission timestamp |
| J | 上线时间 | Confirmed live timestamp |
| K | 结果链接 | Result/listing URL when available |
| L | 实际链接属性 | Actual rel behavior for this project's live link |
| M | 目标URL | Project URL/page intended for the backlink |
| N | 锚文本/关键词 | Intended anchor/keyword when relevant |
| O | 失败原因 | Machine/human-readable failure reason |
| P | 人工原因 | Exact reason human takeover is required |
| Q | 证据摘要 | Browser evidence supporting the current status |
| R | 项目备注 | Project-specific notes only |

Canonical status values:

- `PENDING`
- `IN_PROGRESS`
- `SUBMITTED`
- `UNDER_REVIEW`
- `SCHEDULED`
- `LIVE`
- `NEEDS_HUMAN`
- `FAILED`
- `NOT_APPLICABLE`

Allowed `实际链接属性` values:

- `FOLLOW`
- `NOFOLLOW`
- `UGC`
- `SPONSORED`
- `MIXED`
- blank when not yet verified

## Queue selection contract

For an explicitly selected project ID `<project-id>`:

1. Read `项目外链管理`.
2. Filter exact `项目ID == <project-id>`.
3. From those rows, select only `状态 == PENDING`.
4. Process at most 100 rows per invocation unless the user explicitly requests a smaller number.
5. Never change rows belonging to another project.
6. Before every row write, preserve the original row number and re-read the target row.
7. After every row write, re-read the same row and verify the mutation.

## Evidence rule

`SUBMITTED`, `UNDER_REVIEW`, `SCHEDULED`, or `LIVE` may only be written after real browser evidence supports that state.

`证据摘要` should record a concise observable reason, for example:

- `Success page: Submission received`
- `Dashboard status: Pending review`
- `Public listing URL verified`

Narrative intention is not evidence.

## Human takeover rule

Use `NEEDS_HUMAN` only when a genuine human-only blocker appears, such as CAPTCHA, Cloudflare challenge, 2FA, passkey, SMS/phone verification, payment/plan choice, unusual authorization, or missing required factual data.

Write the exact blocker to `人工原因` and preserve the current browser/checkpoint state for resumption.
