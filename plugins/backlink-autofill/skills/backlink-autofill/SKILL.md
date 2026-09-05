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
4. **Browser and Control Plane are strictly separated.** Google Sheets is structured control data. Never use browser automation to read or edit Google Sheets. Browser runtime strictly forbids navigating to or mutating Google Sheets/Drive control plane URLs (`CONTROL_PLANE_URL_FORBIDDEN`). Use the official Google Drive/Sheets API/connector for bounded reads and exact writes. Every Sheet mutation must be verified by an immediate exact-row read-back.
5. **Security challenges are human-only.** Never solve or bypass CAPTCHA, Cloudflare/Turnstile, 2FA, passkeys, SMS/phone verification, or similar controls.
6. **Passwords are different.** Existing/primary account passwords, passcodes, tokens, secrets, API keys, session credentials, and security-challenge solutions must never be placed in chat, Google Sheets, project data, checkpoints, recipes, or browser action JSON. A confirmed **new backlink-platform account** may use an independently generated per-site password from the local credential store via `credential_fill`; the password value itself remains local and model-invisible.
7. **No cross-project assets.** **Never search sibling project directories** for a logo, screenshot, contact, social URL, copy, keyword, or other project-specific value.
8. **Evidence & State Contract (Universal Invariants):**
   - **Invariant 1: Prior research is discovery provenance, NOT observed facts.** Discovery sources, BacklinkOS tags, historical datasets, and manual research must NEVER populate `实测免费`, `实测需登录`, `实测登录方式`, `实测限制`, or `实测链接属性`. These fields require direct browser evidence from the current run.
   - **Invariant 2: Observed link attribute (`实测链接属性`) requires live public DOM evidence.** `Follow`, `Nofollow`, `UGC`, or `Sponsored` can ONLY be written after the listing is verified live and the target `<a>` tag's `rel` attribute is inspected in the public page DOM. If unverified or not yet live, it MUST remain blank.
   - **Invariant 3: Public result URL must be an accessible public page.** `项目外链管理.结果链接` must NEVER contain private URLs (dashboard, admin, account, edit, payment, queue, confirmation, auth). If no public listing URL is yet generated, `结果链接` MUST remain blank, and the private dashboard/queue URL may only be recorded in `证据摘要` as execution evidence.
   - **Invariant 4: Classify status by strongest verified evidence.** If an explicit future launch/publication/scheduled date exists, prioritize `已排期` over `Pending` or `审核中`. Never classify as `已上线` without a verified, accessible public listing page.
   - **Invariant 5: Browser runtime strictly rejects control plane URLs.** Navigating Playwright/CDP to `docs.google.com` or `sheets.google.com` is forbidden at runtime (`CONTROL_PLANE_URL_FORBIDDEN`).
   - **Invariant 6: Unknown facts remain blank.** Never guess or infer missing platform attributes.

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

Default to the persistent CDP Chrome session (`http://127.0.0.1:9222`, or `BACKLINK_BROWSER_CDP_URL`) using existing `browser.contexts[0]`.

Login priority for each platform:
1. **Existing session on target site** → reuse immediately.
2. **Target site supports Google OAuth** and persistent CDP Chrome has an active Google session → try Google OAuth first.
   - If Google displays an existing account chooser or standard consent screen → proceed automatically.
   - If Google prompts for the primary Google password, 2FA, passkey, or security challenge → **strictly forbid reading, generating, or filling Google credentials**; do not bypass security challenges; fall back to independent site registration or human handoff.
3. **Platform supports standard email/password registration** → use `credential_fill` with `mode = create_or_reuse` and the approved registration email from profile.
   - For an existing backlink-platform login form: use `credential_fill` with `mode = existing_only` only if a credential already exists for that current domain/account; do not invent a new password for an existing login form.
4. **Credential domain isolation (two-layer defense)**:
   - **Layer 1 (Target Domain Allow Rule)**: `credential_fill` may ONLY fill passwords when the current page domain matches the explicit `target_domain` of the backlink platform.
   - **Layer 2 (Third-party IdP blocklist)**: `credential_fill` is strictly forbidden on any third-party Identity Provider domain (such as `accounts.google.com`, `github.com`, `x.com`, `twitter.com`, `apple.com`, `microsoft.com`).
5. **Human blockers (e.g. EMAIL_OTP, CAPTCHA, 2FA, SMS)**:
   - `EMAIL_OTP` requires composite evidence: both verification code cues and explicit email/inbox context.
   - Enter `需人工`, retain the browser tab, persist `human_pending` record, and **continue the batch immediately without stopping**.

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

### 9. Human handoff and non-blocking batch execution

Core rule: **`NEEDS_HUMAN` pauses only the current row; it NEVER stops the batch.**

When encountering an email verification code, CAPTCHA, 2FA, passkey, payment, or other genuine human blocker:

1. Save credential-free row checkpoint;
2. Save durable `human_pending` record under `~/.backlink-autofill/runtime/human-pending/` including project ID, backlink ID, current URL, blocker type, and CDP `target_id`;
3. Write exact project Sheet row `需人工` + concrete `原因/备注` + concise `证据摘要` and verify by re-read;
4. In persistent CDP Chrome mode: keep the active browser Tab open in the external Chrome (do not close it); in headless standalone fallback mode: launch `handoff-start` on the profile to present the visible window;
5. Add the task to the current batch's human-pending collection;
6. **Immediately proceed to the next `待提交` row in the queue.**

Never pause or abort the batch because one task requires human intervention. Multiple `HUMAN_PENDING` tabs may coexist simultaneously without conflict.

### 9a. Human pending resume protocol

When the user completes the human step in the visible Chrome window and asks to resume (e.g. "FoundrList verification done"):

1. Attach to the persistent CDP Chrome session (`127.0.0.1:9222`);
2. Locate the durable `human_pending` record under `~/.backlink-autofill/runtime/human-pending/<project_id>/<backlink_id>.json` and locate the original Tab by persisted `target_id`;
3. Inspect current page state to confirm the human blocker has been resolved (e.g. verification code accepted, logged in, reached next form step);
4. Resume execution from the checkpoint;
5. Once a stable terminal status (`已提交`, `审核中`, `已上线`, `已排期`, `失败`, `不适用`) is verified and written to Sheet, call `human-pending-resolve` with `--project-id`, `--backlink-id`, and `--terminal-status` to cleanly resolve the pending record;
6. **Strict prohibition on `clear`**: Submission workflow MUST NEVER use `human-pending-clear` to restart tasks from scratch. `clear` is strictly an administrative command requiring `--admin-override`;
7. **Conservative recovery rule**: if the original `target_id` cannot be found or the tab was closed:
   - CLI returns `TARGET_TAB_LOST`;
   - **Never auto-re-register**;
   - **Never auto-re-submit**;
   - **Do NOT delete the pending record**;
   - Retain `需人工` status and inform the user.

### 10. Classify outcome from evidence

Classify status strictly according to the strongest verifiable browser evidence (Invariant 4):

- `已上线` — Target listing is verified live on a public page (`public_listing_url` is verified and accessible). A dashboard stating "Live" or "Active" without an accessible public listing page MUST NEVER be marked as `已上线`.
- `已排期` — An explicit future publication, launch, or scheduled date exists (e.g. `2027-03-25`, or "Scheduled for X date"). Explicit scheduled date ALWAYS takes precedence over generic "Pending", "Queue", or "Under review" status text.
- `审核中` — Formally submitted and awaiting review/moderation (status contains "Pending", "Review", "Moderation", "审核", "等待"), AND no specific future scheduled date has been assigned.
- `已提交` — Final submission action confirmed/received, but review, scheduling, or live status is undetermined.
- `不适用` — Observed eligibility, payment, product constraint, or policy incompatibility (e.g. non-free with no free path, AI-only constraint not met).
- `失败` — Concrete execution failure with verified evidence that no submission was accepted.
- `需人工` — Human-only blocker (Email OTP, CAPTCHA, 2FA, SMS, phone verification, payment) or ambiguous post-submit outcome.

If final Submit was clicked but outcome is ambiguous, use `需人工` with `已执行提交但结果不明确，避免重复提交`; never auto-retry.

`证据摘要` must be short, factual, and capture observable state.

### 11. Update exact project row

When updating `项目外链管理`:
- `状态`: Must match the classified status above.
- `最近操作时间`: Current ISO timestamp (`YYYY-MM-DDTHH:MM:SSZ`).
- `结果链接`: Must run through `sanitize_result_url`. ONLY public listing URLs accessible to external visitors and search engines may be written here. Dashboard, admin, account, edit, payment, queue, confirmation, and auth URLs must NEVER be written to `结果链接`. If no public listing URL has been generated, leave blank; any private dashboard/queue URL may only be appended to `证据摘要` as execution evidence (Invariant 3).
- `原因/备注`: Concise human-readable note explaining the status or blocker.
- `证据摘要`: Short factual evidence observed in browser.

**Always re-read the exact row immediately after every Sheet mutation** and verify values. Never mutate another project's row.

### 12. Enrich master facts from direct observation only

Update matching `外链总表` row ONLY with facts directly observed during the current execution (Invariant 1 & 6):
- `实测免费`: `免费` / `非免费` / `混合` (only if directly observed in pricing/form).
- `实测需登录`: `需要` / `不需要` (only if directly observed).
- `实测登录方式`: Directly observed login method (e.g. `Google OAuth`, `Email/Password`, `GitHub`).
- `实测限制`: Directly observed constraints (e.g. reciprocal backlink required, queue waiting time).
- `实测链接属性`: ONLY populated if the listing is verified live AND the target `<a>` tag's `rel` attribute in the live DOM is directly inspected (`Follow`, `Nofollow`, `UGC`, `Sponsored`). If listing is pending, queued, under review, scheduled, or unverified, this field MUST remain blank (Invariant 2).
- `最后验证时间`: Current ISO timestamp when facts were observed.
- `平台备注`: Concise factual notes on observed platform behavior.

Prior research, discovery provenance (e.g. `BacklinkOS/已确认免费Follow`), and historical notes must NEVER populate `实测*` fields. Unknown facts remain blank; never guess. Project-specific status or result URL must never leak to other projects.

### 13. Save/refresh domain recipe

After a verified stable flow, save selectors/navigation/success indicators. Never store password/token/secret/session credential, generated password, or project-specific copy inside a recipe.

### 14. Finish or continue

Delete completed-row checkpoints once the row reaches a non-ambiguous terminal state. Keep checkpoint and durable `human_pending` record for `需人工`/ambiguous interrupted work.

Continue processing rows until the batch is exhausted or the invocation limit is reached. Single-task human blockers (`需人工`) must never terminate the batch; record them and immediately proceed to subsequent rows.

## Truthfulness contract

- `Planned`: no website mutation happened.
- `Attempted`: an actual browser action was issued but intended result not verified.
- `Filled`: actual field/file mutation was read back and verified; for credentials, verification must not expose the secret.
- `Submitted`: real final action occurred and browser produced evidence of receipt/result.

Never upgrade state based on narration, prior conversation, or inference.

## User-facing behavior

Ordinary automatic rows require no visible confirmation during execution.

At batch end, report compact totals:
1. **Summary of completed rows**: counts of `已提交`, `审核中`, `已上线`, `不适用`, `失败`;
2. **Pending human tasks summary**: list of all rows that entered `需人工` during the batch, specifying:
   - Target site/domain;
   - Blocker type (e.g. Email verification code, CAPTCHA, 2FA);
   - Note that their tabs are preserved in the persistent Chrome window;
   - Prompt that the user can verify them anytime and simply tell the agent to resume.

Never print generated/stored passwords unless the user explicitly asks to retrieve one through an appropriate secure local workflow.