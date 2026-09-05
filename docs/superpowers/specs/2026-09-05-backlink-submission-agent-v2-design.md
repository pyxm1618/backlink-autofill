# Backlink Submission Agent v2 — Design

Date: 2026-09-05  
Status: implemented; external-site acceptance still in progress

## Goal

Turn Backlink Autofill into a project-isolated Codex submission agent that reads a shared Google Sheets queue, processes at most 100 pending rows per invocation, executes ordinary website flows headlessly, submits safe/free flows automatically, and asks the user only for genuine human-only steps.

## Scope

Current implementation starts from an already-populated control Spreadsheet. Discovery, de-duplication, and creation/population of new project rows remain separate work for the backlink-discovery Skill.

In scope:

- explicit project selection;
- exact project-row isolation;
- structured Google Sheets reads/writes;
- up to 100 rows per invocation;
- shared submitter identity and selected-project-only assets;
- persistent headless browser execution;
- automatic ordinary final Submit;
- independently generated passwords for new backlink-platform accounts;
- visible human takeover for CAPTCHA/2FA/payment/primary credentials and similar blockers;
- evidence-backed status updates;
- direct-observation enrichment of the master platform table;
- domain recipe reuse.

Out of scope:

- scheduled/daily execution;
- Semrush/DR/DA gating;
- pre-researching Follow/Nofollow, price, login method, or AI-only status when the execution flow can discover it;
- importing or automating the user's primary Google/email/GitHub passwords;
- bypassing security controls.

## Core principles

1. **Submit instead of over-screening.** Discovery does only minimal junk/dead/malicious filtering; real execution is the main validator.
2. **Unknown stays blank.** Platform facts are written only when observed.
3. **One control plane, strict project isolation.** All projects share one Spreadsheet; a run may touch only the explicitly selected `项目ID`.
4. **Shared identity, isolated project content.** Human submitter identity is global; project facts/assets are per project.
5. **Autonomous by default.** Ordinary safe/free flows may include final Submit.
6. **Human only on exception.** Security challenges, payment, unusual authorization, missing facts, and unmanaged primary credentials require takeover.
7. **Evidence before status.** Model narration alone never proves a browser action or submission outcome.
8. **Run-based, not time-based.** Default maximum is 100 per invocation; no daily quota or scheduler.

## Google Sheets topology

One private Spreadsheet is the shared control plane. Its ID lives only in:

```text
~/.backlink-autofill/control-plane.json
```

### `外链总表`

Exact headers:

```text
外链ID | 平台域名 | 提交入口 | 发现来源 | 发现时间 | 基础状态 | 基础排除原因 |
实测免费 | 实测需登录 | 实测登录方式 | 实测限制 | 实测链接属性 | 最后验证时间 | 平台备注
```

Discovery-stage status:

```text
候选 | 已排除 | 失效
```

Observed fields remain blank until directly verified. `发现来源` is provenance only and never a submission gate.

### `项目外链管理`

Exact headers:

```text
项目ID | 外链ID | 平台域名 | 状态 | 尝试次数 | 最近操作时间 |
目标URL | 结果链接 | 原因/备注 | 证据摘要
```

Statuses:

```text
待提交 | 处理中 | 已提交 | 审核中 | 已排期 | 已上线 | 需人工 | 失败 | 不适用
```

Normal queue predicate:

```text
项目ID == <selected-project-id>
AND 状态 == 待提交
```

Read at most 100 matching rows per invocation by default.

## Shared private data

```text
~/.backlink-autofill/
├── submitter-profile.json
├── control-plane.json
├── credentials/
├── browser-profile/
├── runtime/
├── recipes/
└── projects/<project-id>/
```

### Submitter profile

One reusable human/operator identity. Passwords never belong here.

### Project data

Only `projects/<selected-project-id>/` may be read for project-specific assets/facts. Sibling project directories are never fallback sources.

### Local site credential store

`credentials/` is the **only** intentional password persistence surface.

Purpose: passwords generated specifically for backlink-platform accounts.

Rules:

- a confirmed new backlink-platform registration may use `create_or_reuse`;
- a later login may use `existing_only` only if a stored credential already exists;
- missing credential on an existing login never triggers password invention;
- Google/email/GitHub/primary passwords are never imported;
- each stored password is independently generated with a cryptographic RNG;
- credential directory uses `0700` and credential files use `0600` where supported;
- raw passwords never enter chat, Sheets, project data, checkpoints, recipes, action JSON, or browser evidence output;
- `credential_fill` resolves a password from the current page domain inside the browser runtime;
- `credential_fill` is restricted to actual `type=password` inputs, never API key/token/secret text fields.

This is an explicit product trade-off: these generated backlink-platform credentials may be stored locally in plaintext protected by filesystem permissions because the user prioritizes unattended execution and they are not primary accounts.

## Browser execution

The website executor is a real local Playwright component, not narrative prompting.

- persistent profile: `~/.backlink-autofill/browser-profile/`;
- headless by default;
- compact interactive DOM/form extraction;
- actions: non-sensitive fill, `credential_fill`, select, check, upload, ordinary click, final submit;
- upload restricted to the selected project's private asset root;
- every meaningful action returns read-back evidence;
- passive text such as “protected by reCAPTCHA” is not enough to trigger human takeover; challenge-specific evidence is required.

## Final submit

The old universal human-final-click boundary is removed.

Automatic final Submit is allowed when:

- a free/non-payment path is being used;
- no security/human blocker is present;
- required product facts come from approved data;
- no unusual legal authorization or project-site modification is required;
- result state can be inspected afterward.

If Submit happened but the outcome is ambiguous, do **not** retry automatically. Record `需人工` to avoid duplicate listings.

## Human takeover

Human-only examples:

- CAPTCHA / Cloudflare / slider verification;
- 2FA / passkey / SMS / phone verification;
- primary/existing account password not owned by the local site credential store;
- payment;
- unusual authorization/terms requiring judgment;
- required factual data that cannot be verified;
- browser/security access block.

Handoff lifecycle:

1. save a secret-free project/row checkpoint;
2. write and verify `需人工` with concrete reason/evidence;
3. close headless browser to release the persistent profile;
4. reopen the same profile visibly;
5. replay only safe reversible actions: fill/select/check/upload and secret-free `credential_fill` metadata;
6. never replay final Submit;
7. human performs the required step;
8. read final page state and resume or keep `需人工`.

`credential_fill` may be replayed because the handoff request contains no password value; the visible browser resolves it again from the local store.

## Resume semantics

A `需人工` row can resume without becoming a new attempt when:

- the user explicitly asks to continue;
- evidence proves the previous final Submit did not happen;
- the continuation belongs to the same interrupted attempt.

This is required for the current eBool acceptance case: the first attempt stopped only because old v2 behavior treated new-account Password/Confirm Password as human-only. Under v0.2.1, that same attempt can continue after the old headed handoff is closed.

If final-submit state is uncertain, never use this shortcut.

## Status evidence

Use strongest observed state:

- `已上线`: actual listing/result verified live;
- `已排期`: platform explicitly confirms a scheduled publication;
- `审核中`: moderation/review explicitly pending;
- `已提交`: submission receipt confirmed, with no stronger state;
- `不适用`: platform eligibility/payment constraint makes the selected project ineligible under policy;
- `失败`: concrete execution failure with no submission evidence;
- `需人工`: genuine human-only blocker or ambiguous post-submit state.

Every Sheet write is re-read and verified against the exact original row.

## Master-fact enrichment

Execution may update `外链总表` only with directly observed platform facts:

- free/paid/mixed;
- login required/not required;
- observed login method;
- eligibility/reciprocal/review constraints;
- link attribute only after a real live link/HTML verification;
- last verification timestamp;
- concise platform note.

Unknown stays blank.

## Domain recipes

Stable verified flows may be cached under:

```text
~/.backlink-autofill/recipes/<domain>.json
```

Recipes contain navigation/selectors/success indicators, never passwords, credentials, or project-specific marketing copy.

## Acceptance criteria before merge

PR #2 remains Draft until one real external target completes this loop:

1. read the correct selected-project queue row;
2. execute the real website flow;
3. if new-account password is required, generate/store/fill it without exposing the secret;
4. execute final Submit unless a genuine human blocker appears;
5. obtain real result evidence;
6. write and re-read the exact project row;
7. write only directly observed master facts;
8. verify no sibling project row/data was changed.

The current staged external target is eBool for `quick-iching`.