---
name: backlink-autofill
description: Use when running backlink submissions for an explicitly selected project from the shared Google Sheets control queue with Codex.
---

# Backlink Autofill

## Core principle

Backlink Autofill is a **Codex plugin/Skill**, not a Google plugin and not a browser-side AI client. Google Drive/Sheets is the structured queue/control plane; the website itself is controlled by the plugin's Playwright browser runtime.

The AI is the current signed-in Codex/ChatGPT model. **Do not call or require a separate LLM API**, API key, model endpoint, OpenRouter account, or second model service.

Normal flow:

```text
explicit project
→ read only that project's 待提交 rows
→ process at most 100 rows per invocation
→ headless browser by default
→ submit ordinary safe/free flows automatically
→ write evidence-backed state to the exact Sheet row
→ continue
```

Do not narrate every successful row. Interrupt the user only for a genuine human-only blocker or genuinely missing factual data.

## Hard gates

1. **Project selection is explicit.** Read `../../references/project-registry.json`. The user must name/select a project. Never infer it from the website, previous run, or the fact that only one project exists.
2. **Project isolation is strict.** Read project-specific facts/assets only for the selected project. Mutate only Sheet rows whose `项目ID` exactly equals that selected project ID.
3. **Browser action evidence is mandatory.** Never claim navigation, filling, clicking, uploading, submitting, login, or success from intention. A browser action must actually run and its returned state/read-back must support the claim.
4. **Google Sheets is structured control data.** Never use browser automation to read or edit Google Sheets. Use the connected Google Drive/Sheets capability for bounded reads/searches and exact writes.
5. **Security challenges are human-only.** Never solve or bypass CAPTCHA, Cloudflare/Turnstile, 2FA, passkeys, SMS/phone verification, or similar controls.
6. **Passwords are different.** Existing/primary account passwords, passcodes, tokens, secrets, API keys, session credentials, and security-challenge solutions must never be placed in chat, Google Sheets, project data, checkpoints, recipes, or browser action JSON. A confirmed **new backlink-platform account** may use an independently generated per-site password from the local credential store via `credential_fill`; the password value itself remains local and model-invisible.
7. **No cross-project assets.** **Never search sibling project directories** for a logo, screenshot, contact, social URL, copy, keyword, or other project-specific value.
8. **Evidence before status.** Never write success-like states (`已提交`, `审核中`, `已排期`, `已上线`) without browser-observed evidence.

## Private runtime model

Read `~/.backlink-autofill/control-plane.json` before queue work:

```json
{
  "schema_version": 1,
  "spreadsheet_id": "<private>",
  "master_sheet": "外链总表",
  "project_sheet": "项目外链管理",
  "default_batch_size": 100
}
```

If missing/invalid, stop before browser work. Do not guess a Spreadsheet by title.

Shared reusable identity:

```text
~/.backlink-autofill/submitter-profile.json
```

Selected-project-only private data:

```text
~/.backlink-autofill/projects/<project-id>/
```

Browser/runtime storage:

```text
~/.backlink-autofill/browser-profile/
~/.backlink-autofill/runtime/
~/.backlink-autofill/recipes/
~/.backlink-autofill/credentials/
```

`credentials/` is a shared local store keyed by platform domain for passwords created specifically for backlink-platform accounts. It is not project content. Never copy credential values into another persistence surface.

## Canonical Sheet contract

Read `../../references/project-sheet-contract.md` and use its exact Chinese headers/statuses.

Queue predicate:

```text
项目ID == selected project ID
AND 状态 == 待提交
```

Process **at most 100 rows per invocation** by default. If the user requests fewer, obey the smaller limit. There is no daily quota, scheduler, cron, or implicit time-based run.

### Queue discovery

1. Resolve the exact Spreadsheet ID from `control-plane.json`.
2. Verify tabs `外链总表` and `项目外链管理` and their exact headers.
3. Search/read `项目外链管理` for the exact selected `项目ID` in bounded ranges.
4. Retain only exact `状态 == 待提交` rows, preserving original Sheet row numbers.
5. Select at most the configured batch limit in Sheet order unless explicitly told otherwise.

Never select another project's rows even if its domain or target looks related.

## Interrupted and human-row recovery

Before taking new `待提交` rows, inspect selected-project `处理中` rows and active checkpoints/handoffs.

- Active checkpoint/handoff with known reversible state → resume it first.
- Previous run stopped with uncertain final-submit outcome → do not reset/retry; set/keep `需人工` with `上次执行中断，提交结果不确定，避免重复提交`.
- Retry only when evidence proves no submission occurred or the user explicitly directs a retry.
- A `需人工` row may be resumed when the user explicitly asks and evidence proves the final Submit **did not occur**. Do not increment `尝试次数` merely for continuing the same still-open attempt.
- If the only previous blocker was new-account password creation and no final Submit occurred, the new `credential_fill` policy may resume that same attempt after the old visible handoff is cleanly closed/unlocked.

## Per-row execution loop

### 1. Re-read and lock the exact row

Immediately before new execution:

1. re-read the exact original row;
2. confirm `项目ID` still equals selected project;
3. confirm status is still eligible for this action (`待提交`, or an explicitly resumed known-safe `需人工` row);
4. for a new `待提交` attempt set `状态 = 处理中`, increment `尝试次数`, and set `最近操作时间`;
5. for continuation of the same proven-unsubmitted attempt, set `状态 = 处理中` without incrementing the attempt count;
6. **Re-read the exact row after every Sheet mutation** and verify intended values.

Create/update a project+row checkpoint before website mutation. Checkpoints contain only safe state, never credentials.

### 2. Resolve platform row

Join by `外链ID` to exactly one row in `外链总表`; require a valid `提交入口`.

- no exact master row → `失败`, `外链ID在外链总表中不存在`;
- duplicate exact master rows → `失败`, `外链ID在外链总表中不唯一`;
- invalid/missing submit URL → `失败`, `缺少有效提交入口`.

Do not silently web-search a replacement URL for a data-integrity failure.

### 3. Load only approved project data

Load:

1. selected reviewed project profile from `../../references/projects/...`;
2. shared `submitter-profile.json`;
3. only `~/.backlink-autofill/projects/<project-id>/` and its assets.

**Never search sibling project directories** as fallback.

If `目标URL` is blank, use the selected project's canonical URL only when unambiguous. Never invent features, AI claims, pricing, metrics, awards, integrations, company claims, reviews, or partnerships.

### 4. Recipe first, compact inspection second

Use `~/.backlink-autofill/recipes/<domain>.json` when a verified stable recipe exists. Recipes contain selectors/navigation/success indicators, never credentials or project copy.

If missing/stale, inspect the real page with the browser runtime's compact interactive snapshot. **Headless is default** and the persistent profile is:

```text
~/.backlink-autofill/browser-profile/
```

Do not use screenshots/full-page dumps when compact DOM/form state is sufficient.

### 5. Discover platform facts by execution

Do not pre-research DR/DA, Follow status, login method, price, AI-only status, or review time when the live flow can reveal them.

Record only directly observed facts. Unknown stays blank.

Examples:
- free / paid-only / mixed submission;
- login required or not;
- observed login method;
- AI-only/SaaS-only constraints;
- reciprocal/badge requirement;
- review queue/scheduling behavior.

Fast handling:
- incompatible eligibility → `不适用`, continue;
- no free path under free-run policy → `不适用`, record `实测免费 = 非免费`;
- mandatory project-site modification/reciprocal badge → `需人工`;
- clearly dead submission page → `失败`; master may become `失效` with evidence.

### 6. Login and credential behavior

Reuse the persistent browser profile.

- already logged in → continue;
- ordinary OAuth with already-authorized session and no challenge → may continue automatically;
- confirmed new backlink-platform account with Password / Confirm Password fields → use `credential_fill` with `credential = site_password`, `mode = create_or_reuse`, and the approved registration account;
- existing backlink-platform login → use `credential_fill` with `mode = existing_only` **only if** a credential already exists for that current domain/account;
- existing login with no stored site credential → human handoff; do not invent a new password for a login form;
- Google/email/GitHub/other primary account password → human/browser credential manager; never import or read it;
- CAPTCHA/Cloudflare/2FA/passkey/SMS/phone verification/payment → human handoff.

`credential_fill` must resolve the credential by the **current page domain**, not an arbitrary domain supplied by the model. It may return only non-secret evidence such as `{credential: site_password, verified: true}`.

### 7. Build and execute an explicit action plan

Allowed ordinary actions:

- `fill` for non-sensitive text/textarea fields;
- `credential_fill` for the local per-site password policy above;
- select/dropdown;
- understood ordinary checkbox;
- selected-project file upload;
- ordinary navigation/click;
- final submit when allowed below.

Normal `fill` must continue refusing sensitive/password fields. Never put the password value in action JSON.

Uploads must stay inside the selected project's private asset root. Derived image variants stay in that same project directory.

**Read the form back after filling.** Verify ordinary field values, uploaded filename, and credential-fill success without exposing secret values.

### 8. Final submit policy

**Final submit may be automatic** when all are true:

- free/non-payment path;
- no security/human blocker;
- all required facts are approved;
- no unusual legal authorization or external project-site modification;
- final action/result can be read back.

Do not stop merely because the button is named Submit/Publish/Launch/Post/Create Listing/Send for Review. Do not autonomously make payments or accept unusual commitments.

### 9. Human handoff

Use human handoff for security challenge, missing primary credential, payment, unusual authorization, mandatory external site change, or other genuinely human-only step.

When handing off:

1. save credential-free checkpoint;
2. write exact project row `需人工` + concrete `原因/备注` + concise `证据摘要` and verify by re-read;
3. close headless browser to unlock the persistent profile;
4. launch `handoff-start` on the same profile;
5. replay only safe reversible actions. `credential_fill` is safe to replay because the secret remains in the local credential store and does not enter replay JSON; never replay arbitrary click/final submit;
6. pause the batch and tell the user only the required action.

Do not continue other rows while the profile is held by an active handoff.

After the user finishes:

1. read `handoff-status`;
2. request `handoff-finish`;
3. wait for `FINISHED`, inspect final page state;
4. if blocker remains, keep `需人工`;
5. otherwise classify result, write/verify exact row, then resume headless work.

### 10. Classify outcome from evidence

Use strongest real evidence:

- `已上线` — listing/result verified live;
- `已排期` — explicit scheduled publication/launch;
- `审核中` — explicit review/moderation pending;
- `已提交` — final submission confirmed/received with no stronger state;
- `不适用` — observed eligibility/payment/product constraint;
- `失败` — concrete execution failure with no evidence of successful submission;
- `需人工` — human-only blocker or ambiguous post-submit outcome.

If final Submit was clicked but outcome is ambiguous, use `需人工` with `已执行提交但结果不明确，避免重复提交`; never auto-retry.

`证据摘要` must be short and factual.

### 11. Update exact project row

Normally update only:
- `状态`;
- `最近操作时间`;
- `结果链接` when observed;
- `原因/备注` when needed;
- `证据摘要`.

Then **Re-read the exact row after every Sheet mutation** and verify it. Never mutate another project's row.

### 12. Enrich master facts from direct observation only

Update matching `外链总表` row only with facts directly observed:
- `实测免费`;
- `实测需登录`;
- `实测登录方式`;
- `实测限制`;
- `实测链接属性` only after real live-link/HTML evidence;
- `最后验证时间`;
- concise platform notes.

Unknowns remain blank. Project-specific status/result URL never propagates to other projects.

### 13. Save/refresh domain recipe

After a verified stable flow, save selectors/navigation/success indicators. Never store password/token/secret/session credential, generated password, or project-specific copy inside a recipe.

### 14. Finish or continue

Delete completed-row checkpoints once the row reaches a non-ambiguous terminal state. Keep checkpoint for `需人工`/ambiguous interrupted work.

Continue until batch exhausted, invocation limit reached, human handoff pauses the run, or a control-plane/browser-level failure makes continuation unsafe.

## Truthfulness contract

- `Planned`: no website mutation happened.
- `Attempted`: an actual browser action was issued but intended result not verified.
- `Filled`: actual field/file mutation was read back and verified; for credentials, verification must not expose the secret.
- `Submitted`: real final action occurred and browser produced evidence of receipt/result.

Never upgrade state based on narration, prior conversation, or inference.

## User-facing behavior

Ordinary automatic rows: no visible browser, no per-row confirmation.

At uninterrupted batch end, report compact totals.

For `需人工`, open visible handoff and report only platform/domain, required human action, and that batch is paused. Never print generated/stored passwords unless the user explicitly asks to retrieve one through an appropriate secure local workflow.