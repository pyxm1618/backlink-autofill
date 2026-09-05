# Google Sheet Contract

This Codex plugin uses one shared Google Spreadsheet as the backlink control plane. The private spreadsheet ID is configured locally and must not be committed to this repository.

## Topology

- 所有项目共用同一个 Spreadsheet。
- Tab `外链总表` stores global backlink/platform facts.
- Tab `项目外链管理` stores project-specific execution rows for every project.
- Project isolation is enforced by exact `项目ID` matching. The agent must never read or mutate another project's rows as part of a selected-project run.
- 每次最多读取 100 条 current-project rows whose `状态` is `待提交` unless the user explicitly requests a smaller limit.

## Tab: `外链总表`

Header order is fixed:

外链ID | 平台域名 | 提交入口 | 发现来源 | 发现时间 | 基础状态 | 基础排除原因 | 实测免费 | 实测需登录 | 实测登录方式 | 实测限制 | 实测链接属性 | 最后验证时间 | 平台备注

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

## Tab: `项目外链管理`

Header order is fixed:

项目ID | 外链ID | 平台域名 | 状态 | 尝试次数 | 最近操作时间 | 目标URL | 结果链接 | 原因/备注 | 证据摘要

Field rules:

- `项目ID`: exact project registry ID, e.g. `quick-iching`. This is the hard project-isolation key.
- `外链ID`: foreign key to `外链总表`.
- `平台域名`: copied for human readability; authoritative platform lookup still uses `外链ID`.
- `状态`: execution state. Options: 待提交 / 处理中 / 已提交 / 审核中 / 已排期 / 已上线 / 需人工 / 失败 / 不适用.
  - When a platform has an explicit future launch/publication/scheduled date (even if platform status copy says `Pending`), prioritize `已排期`.
  - `审核中` applies only when pending review without an explicit scheduled date.
  - `已上线` requires a verified, accessible public listing page where the project is live. Never mark `已上线` based solely on dashboard text without a verified public page.
- `尝试次数`: increment only when a real browser execution attempt starts.
- `最近操作时间`: latest execution/status-change timestamp.
- `目标URL`: project page to promote; blank may mean use the project's canonical default URL when the project profile defines one.
- `结果链接`: ONLY public listing / live page URL accessible to users and search engines. Never write dashboard, admin, account, edit, payment, queue, confirmation, or auth URLs here. When public listing URL has not yet been generated, leave blank (dashboard/queue URLs belong in `证据摘要`).
- `原因/备注`: concise reason for failure, human intervention, incompatibility, or other execution note.
- `证据摘要`: short browser-observed evidence supporting the written status, e.g. `Submission received; pending review`. Preserves private dashboard/queue URLs as execution evidence when public listing URL is not yet generated.

Do not duplicate project name, submit URL, SEO copy, keywords, separate submitted/live timestamps, or platform-link facts in this tab. Submit URL comes from `外链总表`; SEO/product content comes from the selected project profile; platform facts belong in `外链总表`.

## Execution selection

For a selected project, the queue predicate is:

```text
项目ID == <selected-project-id>
AND 状态 == 待提交
```

Read at most 100 matching rows per invocation by default. There is no daily quota or scheduler implied by this contract.

## Write integrity

- Every mutation targets the exact original row.
- Re-read the mutated row after writing.
- Never mutate rows for a different `项目ID`.
- Never write `已提交`, `审核中`, `已排期`, or `已上线` without browser-observed evidence.
- `需人工` must include a concrete `原因/备注`.
- Unknown facts remain blank rather than inferred.
