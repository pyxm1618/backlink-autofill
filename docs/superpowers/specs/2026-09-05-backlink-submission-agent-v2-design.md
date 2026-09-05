# Backlink Submission Agent v2 — Design

Date: 2026-09-05
Status: approved in chat with execution-scope revision; ready for implementation planning after user review

## Goal

Turn the current single-target autofill workflow into a project-isolated backlink submission agent that:

- starts from an already-existing selected project's task spreadsheet;
- submits eligible pending targets automatically;
- runs normal work headlessly;
- opens a visible browser only when human intervention is required;
- writes execution state back to the project sheet;
- writes only actually observed platform facts back to the master backlink sheet;
- reuses one shared submitter profile and strictly isolated per-project assets;
- keeps discovery analysis minimal and uses real submission as the main source of truth.

## Scope boundary for this implementation

This v2 implementation starts at **reading an existing project backlink-management spreadsheet**.

In scope now:

1. read the selected project's existing spreadsheet;
2. select pending rows;
3. execute submissions;
4. update project execution status;
5. propagate newly observed platform facts to the master sheet;
6. handle headless execution, human takeover, and recipe reuse.

Explicitly out of scope for this implementation:

- discovering new backlink opportunities;
- creating/populating a project spreadsheet from the master sheet;
- changing the discovery skill's write path;
- redesigning the discovery skill beyond documenting the desired minimal-analysis model.

Those discovery/write-side changes are a separate follow-up task.

## Core principles

1. **Discovery is minimal.** Discovery should find, normalize and deduplicate candidate backlink opportunities, reject only obvious junk/dead/malicious entries, and write them to the master sheet. It should not spend time pre-researching DR/DA, Semrush metrics, Follow/Nofollow, login method, price, AI-only status, approval time, etc.
2. **Unknown stays blank.** Platform facts are written only when directly observed during execution or later verification. Do not guess.
3. **Submit instead of over-screening.** Submission is the primary validation mechanism. If a target proves incompatible during execution, record the reason and move on.
4. **Project isolation is strict.** The agent reads one selected project's task sheet and one selected project's private asset directory. It never borrows state or assets from sibling projects.
5. **Shared identity, isolated project data.** `~/.backlink-autofill/submitter-profile.json` is shared across projects; project data/assets remain under `~/.backlink-autofill/projects/<project-id>/`.
6. **Autonomous by default.** Normal submissions may complete automatically, including the final submission action, when no human-only condition is present.
7. **Human only on exception.** CAPTCHA, 2FA, passkey, phone verification, manual payment/terms decisions, missing facts, or similar conditions move the task to `NEEDS_HUMAN` and open a visible browser.
8. **Evidence before status.** `SUBMITTED` or `LIVE` may only be written after browser evidence confirms the corresponding state.
9. **Run-based, not time-based.** The agent processes a bounded batch when invoked. v2 has no scheduler, cron, daily quota, or calendar-based task system.

## Google Sheets topology

Use two logical layers and keep project execution physically isolated by default:

1. **One global master backlink spreadsheet** — platform/opportunity fact base shared across projects.
2. **One independent project backlink-management spreadsheet per project** — execution queue and history for that project only.

Do not place every project's execution queue in one shared spreadsheet by default. The selected project's agent should normally need only its own project spreadsheet plus controlled write access to the global master for newly observed platform facts.

The two layers join through `backlink_id`.

## Data model

### 1. Master backlink sheet

Purpose: global platform/opportunity fact base shared across projects.

The discovery skill writes the minimal initial row. The submission agent enriches only fields it actually observes.

Required columns:

- `backlink_id` — stable unique ID
- `domain`
- `submit_url`
- `source`
- `discovered_at`
- `basic_status` — `ACTIVE`, `REJECTED`, `DEAD`
- `basic_reject_reason` — only for obvious junk/dead/malicious/redundant candidates

Observed fact columns, blank until verified:

- `observed_free` — `YES`, `NO`, `MIXED`, blank
- `observed_login_required` — `YES`, `NO`, blank
- `observed_login_method` — e.g. `GOOGLE`, `GITHUB`, `EMAIL_PASSWORD`, `OTHER`, blank
- `observed_constraint` — e.g. `AI_ONLY`, `SAAS_ONLY`, `RECIPROCAL_REQUIRED`, free text when actually observed
- `observed_follow` — `FOLLOW`, `NOFOLLOW`, `UGC`, `SPONSORED`, `MIXED`, blank; only after live-link verification
- `last_verified_at`
- `platform_notes`

The master sheet never stores project-specific execution status such as "Quick I Ching submitted".

### 2. Project backlink management sheet

Each project has its own spreadsheet. The submission agent reads only the explicitly selected project's spreadsheet.

Required columns:

- `backlink_id` — foreign key to master sheet
- `domain`
- `submit_url`
- `status`
- `attempt_count`
- `last_attempt_at`
- `submitted_at`
- `live_at`
- `result_url`
- `failure_reason`
- `human_reason`
- `project_notes`

Optional cached platform columns may be copied from the master sheet for convenience, but they are read-only snapshots and must not be treated as authoritative if stale.

## Project status machine

Allowed statuses:

- `PENDING` — ready for an attempt
- `IN_PROGRESS` — currently being processed
- `SUBMITTED` — final submission completed and success/receipt state observed
- `UNDER_REVIEW` — platform explicitly says pending review/approval
- `LIVE` — public listing/page verified live
- `NEEDS_HUMAN` — execution blocked on a human-only step
- `FAILED` — attempt failed and is not immediately retryable
- `NOT_APPLICABLE` — target is incompatible with this project, e.g. AI-only target for a non-AI product

Transitions:

- `PENDING -> IN_PROGRESS`
- `IN_PROGRESS -> SUBMITTED | UNDER_REVIEW | LIVE | NEEDS_HUMAN | FAILED | NOT_APPLICABLE`
- `NEEDS_HUMAN -> IN_PROGRESS` after human takeover is completed
- `SUBMITTED | UNDER_REVIEW -> LIVE` after later verification
- `FAILED -> PENDING` only by explicit retry policy or user action

Queue recovery rule: an `IN_PROGRESS` row with no active execution checkpoint from the current run must be recovered to `PENDING` or `FAILED` according to the last recorded evidence; never leave abandoned rows permanently locked.

## Discovery and deduplication

Discovery owns deduplication before writing to the master sheet.

Dedup keys, in order:

1. canonicalized exact submit URL when available;
2. canonical domain + normalized submit path;
3. canonical domain when only one known submission endpoint exists.

The discovery skill should not run Semrush or other authority scoring as a submission gate. It may reject only obvious junk/dead/malicious/link-farm entries using cheap evidence.

This section defines the desired contract only. Implementing or changing the discovery skill is not part of the current v2 execution work.

## Execution loop

For the selected project:

1. Read only that project's existing task spreadsheet.
2. Select up to the configured run batch size from rows with `PENDING`.
3. Mark the current row `IN_PROGRESS`.
4. Load the shared submitter profile and selected project profile/assets.
5. Start or reuse the automation browser profile.
6. Execute the target in headless mode by default.
7. Discover target constraints during execution instead of pre-researching them.
8. If incompatible with the project, write `NOT_APPLICABLE`, update any observed platform fact in the master sheet, then continue.
9. If a human-only condition appears, checkpoint the task, write `NEEDS_HUMAN`, and open a visible browser using the same persistent browser profile when technically possible.
10. Otherwise finish the normal submission automatically, including the final submit action.
11. Read the resulting browser state and classify the outcome.
12. Update the project task row.
13. Write newly observed platform facts to the master sheet.
14. Continue until the per-run batch limit, queue exhaustion, or an agent-level stop condition is reached.

Default run batch size: `100` pending rows, configurable per invocation.

There is no default daily limit and no scheduler/timed execution requirement in v2.

## Headless and human takeover

### Normal path

Use a persistent automation browser profile in headless mode. Preserve cookies, local storage, and account sessions across runs.

### Human takeover conditions

Examples:

- CAPTCHA / slider / Cloudflare challenge
- 2FA / passkey / SMS / phone verification
- manual email verification that cannot be completed automatically
- payment or paid-plan selection
- terms/authorization that require human judgment
- missing required factual information
- browser security block

When one occurs:

1. checkpoint current target and form state;
2. mark `NEEDS_HUMAN` with a concise `human_reason`;
3. open/reopen the same persistent profile in headed/visible mode;
4. navigate back to the blocked target and restore reversible form state if needed;
5. tell the user exactly what must be completed;
6. after takeover, resume from `IN_PROGRESS` and continue automation.

If the browser backend cannot switch one running browser from headless to headed, close and reopen the same persistent profile and restore from checkpoint.

## Final submission policy

The old universal "human must click final Submit" rule is removed.

The agent may click the final submit/publish/review button automatically when:

- the target is an ordinary backlink/listing/profile submission;
- no payment is required;
- no human-only security challenge is present;
- required content is sourced from approved project/shared data;
- no unusual authorization or destructive side effect is detected.

If any of those conditions fail, move to `NEEDS_HUMAN` instead of submitting.

## Fact propagation rules

Project execution may enrich the master sheet only with platform-level facts directly observed during the task.

Examples:

- "Google login supported" -> master sheet
- "Free submission accepted" -> master sheet
- "AI-only products" -> master sheet
- "Quick I Ching was submitted" -> project sheet only
- "Quick I Ching listing URL" -> project sheet only
- "Live link has rel=nofollow" -> master sheet as observed follow behavior, and project sheet may also record the result URL

No project execution status propagates to another project's task sheet.

## Recipe cache

After a successful first run on a domain, save a local domain recipe describing stable form/navigation mappings.

Suggested location:

`~/.backlink-autofill/recipes/<domain>.json`

A recipe may contain:

- known entry URL
- login path/method
- field mapping selectors
- category navigation hints
- upload selectors
- success-state indicators
- last verified timestamp

Recipes contain no passwords and no project-specific content.

Execution policy:

- use a valid recipe first;
- if selectors/state no longer match, fall back to DOM inspection + model reasoning;
- refresh the recipe after a verified successful run.

This reduces model/token usage over time.

## Token strategy

Headless vs headed mode is not the primary token lever. Token savings come from:

1. extracting only relevant interactive DOM/form structure instead of sending full page content;
2. reusing domain recipes;
3. sending the model only changed/ambiguous portions of a familiar flow;
4. using deeper model reasoning only for new or abnormal sites.

## Safety and integrity constraints

- Never invent project or submitter facts.
- Never solve or bypass CAPTCHA/security controls.
- Never store passwords in repository, project profile, recipe, or chat.
- Never borrow assets/data from another project.
- Never mark `SUBMITTED`, `UNDER_REVIEW`, or `LIVE` without observed browser evidence.
- Never write unverified Follow/Nofollow/free/login facts to the master sheet.
- Apply per-domain backoff/rate limiting when a site shows throttling or abuse controls; do not introduce calendar-based scheduling or daily quotas.

## Implementation impact

Existing components retained:

- project registry and strict project selection
- shared private submitter profile
- per-project private assets
- browser-action truthfulness/read-back rules
- Codex/ChatGPT reasoning model without a separate LLM API

New components required for the current execution scope:

1. existing project task-sheet reader/writer
2. master-sheet observed-fact writer
3. queue/state-machine executor
4. headless persistent browser execution path
5. headed human-takeover path/checkpoint
6. domain recipe cache
7. configurable per-run batch size and per-domain backoff

Not part of this implementation:

- discovery-skill refactor;
- master-to-project task generation;
- project-sheet creation/population.

This is an evolution of the existing plugin, not a replacement of the project/profile/asset model.
