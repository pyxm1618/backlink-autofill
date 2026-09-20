# Google Sheet Contract

This Codex plugin uses one shared Google Spreadsheet as the backlink control plane. The private spreadsheet ID is configured locally and must not be committed to this repository.

> [!IMPORTANT]
> ## 2026-09-20 业务展示层规则（当前权威）
>
> `外链总表` 继续保留 A:N 技术字段供现有自动化兼容使用；其中 `基础状态`、`基础排除原因` 在 UI 中隐藏，不作为用户日常判断字段。用户日常以新增的 O:R 四列为准：
>
> - `状态`：只允许空白或 `可用`。空白天然表示“尚未完成验证/仍是候选”；不再显示“候选”状态。只有已经明确可作为外链渠道使用，或某项目已经真实提交成功/进入审核/排期/上线，才填 `可用`。
> - `淘汰原因`：只写已经明确不能采用的原因，例如无可执行外链入口、平台当前不可用、垃圾/PBN、纯付费等。非空即进入 `黑名单` 视图。疑似、未知、未核验不得填写。
> - `平台类型`：只有明确识别后才填写，例如 AI工具目录、Startup目录、MCP目录、优惠券目录、本地商家目录、内容投稿等；不确定留空。
> - `获取方式`：只有明确后才填写，例如 `免费`、`换链`、`免费（付费可选）`、`付费-only`；不确定留空。
>
> A:N 已有实测字段仍继续承载精确平台事实：`提交入口 / 实测免费 / 实测需登录 / 实测登录方式 / 实测限制 / 实测链接属性 / 最后验证时间 / 平台备注`。任何字段都遵循 **known-only** 原则：有直接、明确证据才写；未知、推测、历史疑似信息一律留空。
>
> `实测链接属性` 仍是强证据字段：只有公开结果页已上线，并直接检查目标 `<a>` 的 DOM `rel` 后，才允许写 `Follow / Nofollow / UGC / Sponsored`。平台宣传、第三方数据库、提交页说明不能代替 DOM 实测。
>
> 数据流保持不变：新发现域名可以先进入 `外链总表` 并投影到 `外链管理`；`外链管理` 的真实执行结果必须反向沉淀已经确认的平台事实。项目级 `不适用` 不等于平台淘汰；例如仅限 MCP、仅限本地商家、需互链等，如果渠道本身真实可用，应在 Master 记录类型/限制，而不是因为 Quick I Ching 不适配就全局淘汰。纯付费-only 按当前业务策略进入淘汰/黑名单。
>
> 为兼容现有生产脚本，隐藏技术列仍使用旧内部状态：`基础状态=候选/已排除/失效`。它们只是执行门禁实现细节：业务层 `状态=可用` 的平台在技术列仍可保持 `候选`；业务层 `淘汰原因` 非空时，技术列同步为 `已排除/失效`。不得把隐藏技术状态直接展示为业务结论。


## Topology

- 所有项目共用同一个 Spreadsheet。
- Tab `外链总表` stores global backlink/platform facts (日常隐藏，不影响程序读写).
- Project isolation is enforced by exact `项目ID` matching. Routine runs must never mutate another project's rows. (Authorized Exception: when platform-level global unavailability such as dead domain or closed submissions is confirmed on `外链总表`, the agent is authorized to sync other projects' unstarted `待提交` rows to `不适用`/`失败` using `validate_cross_project_sync_mutation`).
- 每次最多读取 100 条 current-project rows whose `状态` is `待提交` unless the user explicitly requests a smaller limit.

## Tab: `外链总表`

Header order is fixed:

外链ID | 平台域名 | 提交入口 | 发现来源 | 发现时间 | 基础状态(隐藏技术列) | 基础排除原因(隐藏技术列) | 实测免费 | 实测需登录 | 实测登录方式 | 实测限制 | 实测链接属性 | 最后验证时间 | 平台备注 | 状态 | 淘汰原因 | 平台类型 | 获取方式

Field rules:

- `外链ID`: stable global ID and join key.
- `平台域名`: canonical domain.
- `提交入口`: best known submission/listing entry URL.
- `发现来源`: where the candidate was originally discovered, such as Google search, competitor backlinks, a directory list, community recommendation, or manual entry. This is provenance only and is not a submission gate.
- `发现时间`: first discovery timestamp/date.
- `基础状态`: cheap discovery-stage status only. Options: 候选 / 已排除 / 失效.
- `基础排除原因`: only for obvious junk, dead, malicious, duplicate, or unusable candidates.
- `实测免费`: blank until observed during execution. Options: 免费 / 非免费 / 混合.
- `实测需登录`: blank until observed. Options: 需要 / 不需要.
- `实测登录方式`: observed login method such as Google, GitHub, email/password, or other.
- `实测限制`: observed platform constraint such as AI-only, reciprocal-link required, or other concrete rule.
- `实测链接属性`: ONLY filled after public listing is verified live and the target `<a>` tag's `rel` attribute in the DOM is directly observed (Follow / Nofollow / UGC / Sponsored). If listing is not yet live, MUST stay blank. Prior research, BacklinkOS provenance, and submission pages MUST NEVER be used to infer this field.
- `最后验证时间`: timestamp/date of the most recent direct verification.
- `平台备注`: concise platform-level notes only; never project-specific execution status.

Unknown observed facts stay blank. Do not guess.

## Tab: `外链管理`

Header order is fixed:

项目ID | 外链ID | 外链域名 | 状态 | 尝试次数 | 最近操作时间 | 目标URL | 结果链接 | 原因/备注 | 证据摘要

Field rules:

- `项目ID` (Col A): exact project registry ID, e.g. `quick-iching`. This is the hard project-isolation key.
- `外链ID` (Col B, UI 隐藏列): foreign key to `外链总表`. Stable foreign join key, technical identifier hidden from routine user view.
- `外链域名` (Col C): copied for human readability; authoritative platform lookup still uses `外链ID`.
- `状态` (Col D): execution state. Options: 待提交 / 处理中 / 已提交 / 审核中 / 已排期 / 已上线 / 需人工 / 失败 / 不适用.
  - When a platform has an explicit future launch/publication/scheduled date (even if platform status copy says `Pending`), prioritize `已排期`.
  - `审核中` applies only when pending review without an explicit scheduled date.
  - `已上线` requires a verified, accessible public listing page where the project is live. Never mark `已上线` based solely on dashboard text without a verified public page.
- `尝试次数` (Col E, UI 隐藏列): increment only when a real browser execution attempt starts. Technical audit field hidden from routine user view.
- `最近操作时间` (Col F): latest execution/status-change timestamp.
- `目标URL` (Col G, UI 隐藏列): project page to promote; blank means use the project's canonical default URL when the project profile defines one. Preserves deep-link capability while hidden from routine user view.
- `结果链接` (Col H): ONLY public listing / live page URL accessible to users and search engines. Never write dashboard, admin, account, edit, payment, queue, confirmation, or auth URLs here. When public listing URL has not yet been generated, leave blank (dashboard/queue URLs belong in `证据摘要`).
- `原因/备注` (Col I): concise reason for failure, human intervention, incompatibility, or other execution note.
- `证据摘要` (Col J): short browser-observed evidence supporting the written status, e.g. `Submission received; pending review`. Preserves private dashboard/queue URLs as execution evidence when public listing URL is not yet generated.

### UI Visibility and Freeze

- **Daily Visible Columns**: `项目ID` (A), `外链域名` (C), `状态` (D), `最近操作时间` (F), `结果链接` (H), `原因/备注` (I), `证据摘要` (J).
- **Hidden Technical Columns**: `外链ID` (B), `尝试次数` (E), `目标URL` (G).
- **Column Freeze**: Freeze physical columns A:C (up to `外链域名`). Because column B is hidden, scrolling horizontally keeps `项目ID` and `外链域名` continuously anchored.

Do not duplicate project name, submit URL, SEO copy, keywords, separate submitted/live timestamps, or platform-link facts in this tab. Submit URL comes from `外链总表`; SEO/product content comes from the selected project profile; platform facts belong in `外链总表`.

## Execution Selection & Master Gate Protection

> [!IMPORTANT]
> **待提交 ≠ Ready (Execution Handoff Contract)**:
> In the universal backlog architecture, `外链管理` stores full projected backlog for each project (thousands of rows).
> Most backlog candidates intentionally have submission entry `UNKNOWN` and have not yet undergone Phase C entry verification.
> 1. Autofill MUST ONLY consume the intersection of `(项目ID == selected project ID AND 状态 == 待提交)` AND the provided Phase C Ready Allowlist.
> 2. If the Ready Allowlist contains 10 items, attempt at most these 10 items; NEVER auto-backfill from ordinary pending backlog rows.
> 3. If running standalone without a Ready Allowlist, Autofill MUST fail closed and refuse to scan raw pending rows with blank submission entries.

For a selected project with an active Ready Allowlist, the queue predicate is:

```text
项目ID == <selected-project-id>
AND 状态 == 待提交
AND 外链ID in Ready Allowlist
```

Read at most 100 matching rows per invocation by default (bounded by the size of the Ready Allowlist).

### Master Gate Protection Rules

Before launching a browser execution attempt for any `待提交` row, join `外链总表` by `外链ID`:

1. **Master row missing**:
   - `状态 = 失败`
   - `原因/备注 = 外链ID在外链总表中不存在`
2. **Master row duplicate**:
   - `状态 = 失败`
   - `原因/备注 = 外链ID在外链总表中不唯一`
3. **Master `基础状态 == 已排除`**:
   - `状态 = 不适用`
   - `原因/备注 = 外链总表基础状态为已排除：<基础排除原因>`
   - Do NOT launch browser submission.
4. **Master `基础状态 == 失效`**:
   - `状态 = 失败`
   - `原因/备注 = 外链总表基础状态为失效`
   - Do NOT launch browser submission.
5. **Master missing `提交入口`**:
   - `状态 = 失败`
   - `原因/备注 = 缺少有效提交入口`

## Email Verification (OTP & Magic Link) Contract

Email verification during backlink platform onboarding:

1. **Default to Automated Resolution**:
   - When encountering platform email verification (numeric OTP, alphanumeric code, or platform verification link / Magic Link), the host agent attempts automated resolution via authorized mail capability (Codex authorized Gmail app or Antigravity Gmail MCP).
2. **Two-layer Security Defense for Magic Links**:
   - **Layer 1 (High-confidence platform message)**: Verified recipient, narrow blocker time window, sender/subject/body platform identity matching, and strict exclusion of protected authentication messages.
   - **Layer 2 (Controlled browser navigation & identity closure)**: Initial verification URL may pass through trusted ESP redirect hosts (e.g. Postmark, SendGrid, Resend, SES, click-tracking domain), but navigation must remain strictly controlled, tokenized URLs are never logged/persisted, and the browser must reach target platform identity closure without falling into protected primary IdP authentication flows.
3. **Strict Prohibition on Primary IdP & Security Auth**:
   - Strictly forbidden from auto-processing: Google account security verification, GitHub primary-account challenge, Microsoft/Apple primary IdP verification, password reset, account recovery, banking/payment verification, and 2FA/passkeys/SMS.
4. **Fallback to `需人工`**:
   - Enter `需人工` only when mail capability is unavailable, no matching email is found, multiple conflicting emails exist, protected auth is detected, verification fails, or result is ambiguous.

## Write integrity

- Every mutation targets the exact original row.
- Never mutate rows for a different `项目ID` (except for authorized global exclusion sync of unstarted `待提交` rows).
- `需人工` must include a concrete `原因/备注`.
- Unknown facts remain blank rather than inferred.
