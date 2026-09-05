---
name: backlink-autofill
description: Use when running backlink submissions for an explicitly selected project from the shared Google Sheets control queue with Codex.
---

# Backlink Autofill

## Core principle

Backlink Autofill is a **Codex plugin/Skill**, not a separate Google plugin and not a browser-side AI client. Google Drive/Sheets is a connected capability used as the structured queue/control plane; the website itself is controlled by the plugin's real Playwright browser runtime.

The AI is the current Codex/ChatGPT model. **Do not call or require a separate LLM API**, API key, model endpoint, OpenRouter account, or second model service.

The normal job is:

```text
explicit project
→ read only that project's 待提交 rows
→ process at most 100 rows per invocation
→ use headless browser by default
→ submit ordinary safe/free flows automatically
→ write evidence-backed state to the exact Sheet row
→ continue
```

Do not narrate every successful row. Interrupt the user only when a genuine human-only blocker occurs or when required factual data is missing.

## Hard gates

1. **Project selection is explicit.** Read `../../references/project-registry.json`. The user must name/select a project. Never infer the project from the current website, the previous run, or the fact that only one project exists.
2. **Project isolation is strict.** A run may read project-specific facts/assets only for the selected project and may mutate only Sheet rows whose `项目ID` exactly equals that selected project ID.
3. **Browser action evidence is mandatory.** Never claim navigation, filling, clicking, uploading, submitting, login, or success from intention or prose. A browser action must actually run and its returned state/read-back must support the claim.
4. **Google Sheets is structured control data.** Never use browser automation to read or edit Google Sheets. Use the connected Google Drive/Sheets capability for metadata, bounded row reads/searches, and writes.
5. **Security challenges are human-only.** Never solve or bypass CAPTCHA, Cloudflare/Turnstile, 2FA, passkeys, SMS/phone verification, or similar controls.
6. **Passwords are different.** Never put passwords, passcodes, tokens, secrets, or API keys in chat, project data, checkpoints, recipes, or browser action JSON. Password fields are handled by the human/browser credential manager in visible mode.
7. **No cross-project assets.** Never search sibling project directories for a logo, screenshot, contact, social URL, copy, keyword, or any other project-specific value.
8. **Evidence before status.** Never write success-like states (`已提交`, `审核中`, `已排期`, `已上线`) without browser-observed evidence.

## Private runtime model

Read `~/.backlink-autofill/control-plane.json` before any queue work.

Expected structure:

```json
{
  "schema_version": 1,
  "spreadsheet_id": "<private>",
  "master_sheet": "外链总表",
  "project_sheet": "项目外链管理",
  "default_batch_size": 100
}
```

If this file is missing or invalid, stop before browser work. Do not guess a spreadsheet by title.

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
```

The browser profile is shared across projects only for browser account/session continuity. Project content/assets remain isolated.

## Canonical Sheet contract

Read `../../references/project-sheet-contract.md` and use its exact Chinese headers/statuses.

The queue predicate is exactly:

```text
项目ID == selected project ID
AND 状态 == 待提交
```

Process **at most 100 rows per invocation** by default. If the user asks for fewer, obey the smaller limit. There is no daily quota, scheduler, cron, or implicit time-based run.

### Queue discovery

1. Resolve the exact Spreadsheet ID from `control-plane.json`.
2. Use the connected Google Drive/Sheets capability to read Spreadsheet metadata.
3. Verify both tabs exist with the exact names `外链总表` and `项目外链管理`.
4. Read/verify their header rows before mutating anything.
5. Search/read `项目外链管理` in bounded ranges for the exact selected `项目ID`.
6. From those rows, retain only exact `状态 == 待提交` rows, preserving their original Sheet row numbers.
7. Select at most the configured batch limit (default 100) in Sheet order unless the user explicitly requests another ordering.

Do not select another project's rows even if its domain, backlink ID, target URL, or notes look relevant.

## Interrupted-row recovery

Before taking new `待提交` rows, check selected-project rows already marked `处理中`.

- If an active human handoff/checkpoint exists, resume that one first.
- If a previous run stopped with uncertain submission outcome, do **not** silently reset to `待提交` and resubmit. Move it to `需人工` with `原因/备注 = 上次执行中断，提交结果不确定，避免重复提交` and preserve evidence/checkpoint.
- Only retry a failed/ambiguous submission when evidence proves no submission occurred or the user explicitly directs a retry.

This prevents duplicate listings caused by process crashes.

## Per-row execution loop

For each selected queue row:

### 1. Re-read and lock the exact row

Immediately before starting the target:

1. re-read the exact original row;
2. confirm `项目ID` still equals the selected project ID;
3. confirm `状态` is still `待提交`;
4. if either changed, skip it without mutation;
5. update only that row to:
   - `状态 = 处理中`
   - increment `尝试次数` by 1
   - `最近操作时间 = current timestamp`
6. **Re-read the exact row after every Sheet mutation** and verify the intended values before continuing.

Create/update a local project+row checkpoint before website mutation so an interrupted run is recoverable.

### 2. Resolve the platform row

Use the queue row's `外链ID` to find exactly one matching row in `外链总表`.

Require a usable `提交入口`.

- no matching master row → project row `失败`, reason `外链ID在外链总表中不存在`;
- multiple exact matches → project row `失败`, reason `外链ID在外链总表中不唯一`;
- missing/invalid submit URL → project row `失败`, reason `缺少有效提交入口`.

These are data-integrity failures; do not invent a URL by searching the web as a silent substitute.

### 3. Load only approved project data

Load:

1. selected reviewed project profile from `../../references/projects/...`;
2. `~/.backlink-autofill/submitter-profile.json`;
3. only `~/.backlink-autofill/projects/<project-id>/` and its `assets.json` if present.

**Never search sibling project directories** as fallback.

If `目标URL` is blank, use the selected project's canonical URL only when the reviewed profile defines it unambiguously.

Never invent features, AI capabilities, pricing, metrics, awards, integrations, founder facts, testimonials, partnerships, user counts, or legal-company claims.

### 4. Use recipe first, then compact browser inspection

A valid domain recipe in:

```text
~/.backlink-autofill/recipes/<domain>.json
```

may supply stable navigation/form selectors. It contains no credentials or project copy.

If no valid recipe exists or selectors no longer match, inspect the target with the real browser runtime and reason from its compact interactive snapshot.

Personal install runtime command path:

```text
~/plugins/backlink-autofill/scripts/browser_cli.py
```

Development checkout may use the repository copy of the same script.

**Headless is default.** Use the persistent profile:

```text
~/.backlink-autofill/browser-profile/
```

Do not take screenshots or feed full-page content to the model when the compact DOM/form snapshot is sufficient.

### 5. Discover constraints by actually entering the flow

Do not pre-research DR/DA, Follow status, login requirements, or free/paid status before execution unless the current page itself exposes them.

During real execution, collect only directly observed platform facts, for example:

- free submission is available;
- paid-only submission;
- login is required/not required;
- Google/GitHub/email login is offered;
- AI-only/SaaS-only constraint;
- reciprocal link/badge required;
- review queue/scheduling behavior.

Unknown stays blank.

#### Fast incompatibility handling

Do not interrupt the user for obvious non-security incompatibility:

- selected project violates an observed platform eligibility rule → `不适用` and continue;
- paid-only submission when no free path exists → `不适用`, record `实测免费 = 非免费`, and continue;
- reciprocal-link/badge is mandatory and would require modifying the project site → normally `需人工` because it requires an external project change;
- dead/removed submission page with clear evidence → project `失败`; master may be updated to `失效` with verification timestamp.

Example: Quick I Ching encountering an explicitly AI-only directory is `不适用`, not a reason to invent an AI feature.

### 6. Login behavior

Reuse the persistent automation profile.

- already logged in → continue;
- ordinary OAuth button with an already-authorized session may be clicked automatically when no challenge appears;
- password/passcode fields are never filled by action JSON;
- CAPTCHA/Cloudflare/2FA/passkey/SMS/phone/security challenge → human handoff;
- do not create/store a plaintext password.

### 7. Build and execute an explicit action plan

Map the form to approved project/shared data.

Allowed ordinary actions include:

- text/textarea fill;
- select/dropdown choice;
- checkbox where the meaning is understood and ordinary;
- selected-project file upload;
- ordinary navigation/clicks;
- final submit when allowed below.

For file upload, files must resolve inside the selected project's private asset root. If a target requires resizing, compression, format conversion, padding, or cropping, create a derived copy inside that same project directory and preserve originals.

For comments/articles, read enough of the target content to write a genuinely relevant comment; do not manufacture generic spam or force exact-match anchors.

**Read the form back after filling.** The browser runtime must verify values/files/actions; never report a field as filled based only on planned values.

### 8. Final submit policy

**Final submit may be automatic** for an ordinary backlink/listing/profile submission when all are true:

- a free/non-payment path is being used;
- there is no security/human blocker;
- all required facts come from approved project/shared data;
- no unusual legal authorization or external site modification is required;
- the final action's result can be read back.

Do not stop merely because the next button is named Submit, Publish, Launch, Post, Create Listing, or Send for Review.

Do not make payments or accept unusual commitments autonomously.

### 9. Human handoff

The browser runtime returns `stopped_for_human` when it detects a high-signal blocker such as CAPTCHA/Cloudflare/2FA/passkey/security verification/payment-entry.

When `stopped_for_human` is true, or when reasoning identifies another genuinely human-only step:

1. save the checkpoint with only safe reversible state; never store credentials;
2. write the exact project row:
   - `状态 = 需人工`
   - `最近操作时间 = current timestamp`
   - concrete `原因/备注`
   - concise `证据摘要`;
3. verify the Sheet write by re-reading that row;
4. close the headless instance so the persistent profile is unlocked;
5. launch the detached visible-browser flow using `handoff-start` on the **same** persistent profile;
6. replay only safe reversible actions (`fill`, `select`, `check`, `upload`); never replay an arbitrary click or final submit;
7. stop the batch and tell the user only what they need to do in the visible browser.

Do not continue processing other rows while the same browser profile is held by an active human handoff.

When the user says the human step is complete:

1. read `handoff-status`;
2. request `handoff-finish`;
3. wait for the handoff state to become `FINISHED` and read its final page snapshot;
4. if a human blocker still exists, keep `需人工`;
5. otherwise classify the result, update the exact row, verify the write, and resume normal headless processing if more rows remain.

### 10. Classify outcome from evidence

Use the strongest browser evidence available:

- `已上线` — public/listing result is verified live;
- `已排期` — platform explicitly confirms a scheduled launch/publication date/state;
- `审核中` — platform explicitly says review/moderation/approval is pending;
- `已提交` — final submission is confirmed/received but no stronger review/live state is proven;
- `不适用` — observed eligibility/payment/product constraint makes this project ineligible under the run policy;
- `失败` — concrete non-human execution failure with no evidence of successful submission;
- `需人工` — a human-only blocker or ambiguous post-submit outcome that must not be auto-retried.

If the final Submit was clicked but the resulting state is ambiguous, prefer `需人工` with reason `已执行提交但结果不明确，避免重复提交` rather than retrying.

`证据摘要` should be short and factual, for example:

```text
Submission received; pending review
Listing page live at result URL
AI tools only; project is non-AI
Cloudflare human verification detected
```

### 11. Update the exact project row

Write only fields supported by the result, normally:

- `状态`
- `最近操作时间`
- `结果链接` when observed
- `原因/备注` when useful/required
- `证据摘要`

Then **Re-read the exact row after every Sheet mutation** and verify it.

Never mutate another project's row.

### 12. Enrich master facts only from direct observation

After a real execution/verification, update the matching `外链总表` row only with facts actually observed in this run:

- `实测免费`
- `实测需登录`
- `实测登录方式`
- `实测限制`
- `实测链接属性` only after real live-link/HTML evidence
- `最后验证时间`
- concise `平台备注` when needed

Do not fill unknowns.

If new direct evidence conflicts with an old verified value, do not silently pretend both are true. Use `混合` where that is semantically correct or update the newest verified fact and note the conflict/context in `平台备注`.

Project-specific submission status/result URL never propagates to another project's queue rows.

### 13. Save/refresh a domain recipe

After a verified stable flow, save reusable selectors/navigation/success indicators to the domain recipe. Never store:

- password/token/secret/session credentials;
- project-specific title/description/keywords;
- selected-project asset paths when they are not generic selector metadata.

If a recipe stops matching, fall back to fresh compact inspection and refresh it only after successful verification.

### 14. Finish or continue

Delete/close completed row checkpoints once the row is in a non-ambiguous terminal state. Keep the checkpoint for `需人工`/ambiguous interrupted work.

Continue until:

- selected batch rows are exhausted;
- the configured per-invocation maximum is reached;
- an active human handoff pauses the run;
- a control-plane/browser-level failure makes further execution unsafe.

## Truthfulness contract

Use these meanings consistently:

- `Planned`: no website mutation has happened.
- `Attempted`: an actual browser action was issued but its intended result was not verified.
- `Filled`: the actual field/file mutation was read back and verified.
- `Submitted`: the real final action occurred and the browser produced evidence of receipt/result.

Never upgrade one level based on intention, prior conversation, inferred browser state, or model narration.

## User-facing behavior

For ordinary fully automatic rows, do not open a visible browser and do not ask for per-row confirmation.

At the end of an uninterrupted run, report compact totals such as:

```text
处理 37：已上线 9，审核中 14，已提交 7，不适用 5，失败 2。
```

For `需人工`, immediately open the visible handoff browser and report only:

- platform/domain;
- what human action is required;
- that the batch is paused to avoid sharing/locking the same browser profile.

Do not dump all internal reasoning or every successfully filled field unless the user asks.
