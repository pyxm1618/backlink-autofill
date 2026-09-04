---
name: backlink-autofill
description: Use when submitting an explicitly selected project to an already-vetted directory, profile, listing, launch, community, or backlink opportunity with Codex or ChatGPT browser capabilities.
---

# Backlink Autofill

## Core principle

The AI is the current Codex/ChatGPT model. Do not call or require a separate LLM API, API key, model endpoint, OpenRouter account, or browser-side model client.

The job is narrow: use one explicitly selected project's reviewed submission data plus the user's reusable private submitter profile to fill one already-vetted backlink opportunity, then stop before the final submission action.

## Hard gates

1. **Project selection is explicit.** Read `../../references/project-registry.json`. The user must name/select a project. Never infer the current project from the target URL, previous task, open tabs, or the fact that only one project exists.
2. **Project isolation is strict.** Load only the selected project's profile. Never borrow missing facts, keywords, links, assets, or project-specific claims from another project.
3. **Target is already vetted.** This skill does not discover new backlink targets. Use a target the user selected, a vetted queue the user opened, or an already-open submission page.
4. **Browser action evidence is mandatory.** Never claim a page was opened, a field was filled, a button was clicked, or a value was changed unless a real browser/computer-use action was executed in this task and the resulting page state was read back. If browser control is unavailable, not attached, read-only, or fails, say exactly that and state that no page changes were made. Narrative simulation is forbidden.
5. **Final submit is human-only.** Never click the final Submit, Publish, Launch, Create Listing, Send for Review, Post, or equivalent irreversible action.
6. **Security challenges are human-only.** Do not solve or bypass CAPTCHA, slider challenges, Cloudflare checks, 2FA, passkeys, phone verification, or similar security checks.

## Reusable submitter profile

Before filling any form, load the private user profile from `~/.backlink-autofill/submitter-profile.json` when it exists. This file is private local configuration and must never be committed to the repository.

Reusable fields belong here instead of being repeatedly requested per site:

- full name
- email
- company / organization
- country
- role / title
- phone, only if the user chooses to store it
- public personal/social URLs when relevant

If a required reusable field is missing, ask the user once, save the answer to the private profile if they approve, and reuse it on later submissions. Do not silently leave a required reusable field blank when it can be configured once.

Passwords are different: never store site passwords in the plugin, project profile, repository, or chat. Prefer existing Google/GitHub OAuth or the browser/password manager. If a site requires a new password that cannot be supplied through browser credentials, hand that field to the user in the browser.

Project-specific assets such as logo and screenshots belong in the selected project profile, not the submitter profile. Use only reviewed/configured assets or assets directly verified from the project's canonical site; never invent or substitute unrelated imagery.

## Browser handshake

Before saying that work has started on a target, prove browser control:

1. Use the actual browser/Chrome capability to inspect the active target tab.
2. Read back the current URL, page title, and visible form labels from the browser result.
3. If the task needs the user's existing Chrome profile/cookies, use the Codex Chrome extension rather than pretending the normal model context is Chrome.
4. If the browser capability is missing or cannot control the page, stop immediately. Report: `Browser control not available; no fields changed.` Do not continue with a hypothetical fill plan as if it were execution.

## Browser choice

Prefer the Codex Chrome extension when the task needs the user's existing Chrome profile, cookies, signed-in sessions, open tabs, or Chrome extensions. If only a current browser tab is available, work on that tab.

Never ask the user to paste passwords into chat. If normal Google/GitHub social login is visible, it is acceptable to click it and use the browser's existing signed-in session. If a security challenge appears, stop for human takeover and resume on the same tab afterward.

## Workflow

1. Resolve the explicit project ID/name from `../../references/project-registry.json` and load only its profile.
2. Load `~/.backlink-autofill/submitter-profile.json`; resolve reusable identity/contact fields before starting the form.
3. Resolve the target:
   - use a URL/site explicitly named by the user; otherwise
   - use the currently open submission page; otherwise
   - if the user has opened the configured vetted Google Sheet queue in Chrome, read the queue tab named in the project profile and use the row the user selected or clearly marked as next.
   - If the queue has no reliable status/next marker, do not guess what has already been submitted. Surface the best visible vetted candidate and wait for the user's go-ahead.
4. Complete the **Browser handshake**. Do not proceed without real browser control.
5. Open the target submission page if needed.
6. Handle normal existing-session login when possible. Hand security challenges to the user.
7. Inspect the whole visible form before filling fields.
8. Map fields to canonical project data and the reusable submitter profile:
   - exact reviewed values first;
   - shorten, reorganize, paraphrase, or select among approved values only when field length, format, category options, tag limits, or site context require it;
   - never invent a feature, pricing fact, metric, award, integration, founder fact, audience claim, AI capability, testimonial, or other product claim not present in the selected profile;
   - use approved keywords naturally; do not keyword-stuff.
9. For unusual free-text questions, answer only from approved facts. For blog/article comments, read the article first and write a genuinely relevant comment; do not force exact-match anchors.
10. Fill every safe applicable field. Do not ask for an extra conversational confirmation before ordinary reversible form filling unless the browser safety system itself requires approval or required data is missing.
11. **Read the form back after filling.** Verify the actual browser state contains the intended values. Only fields confirmed by this read-back may be reported as filled.
12. Stop before final submission.
13. Report briefly:
   - browser URL actually controlled;
   - fields confirmed filled by read-back;
   - fields still requiring manual attention;
   - whether a browser/security limitation occurred;
   - that final submission was intentionally not clicked.

## Truthfulness contract

Use these exact semantics:

- `Planned` means no browser mutation has happened.
- `Attempted` means a browser action was issued but success was not confirmed.
- `Filled` means the browser was mutated and a subsequent browser read confirmed the value.
- Never upgrade `Planned` or `Attempted` to `Filled` based on intention, page text, prior context, or inference.

## Missing data

If a project-specific required field is absent from the selected project profile, flag it as missing. Do not search another project and do not invent a value. If a reusable submitter field is missing, use the one-time private-profile flow instead of repeatedly leaving it blank.