---
name: backlink-autofill
description: Use when submitting an explicitly selected project to an already-vetted directory, profile, listing, launch, community, or backlink opportunity with Codex or ChatGPT browser capabilities.
---

# Backlink Autofill

## Core principle

The AI is the current Codex/ChatGPT model. Do not call or require a separate LLM API, API key, model endpoint, OpenRouter account, or browser-side model client.

The job is narrow: use one explicitly selected project's reviewed submission data to fill one already-vetted backlink opportunity, then stop before the final submission action.

## Hard gates

1. **Project selection is explicit.** Read `../../references/project-registry.json`. The user must name/select a project. Never infer the current project from the target URL, previous task, open tabs, or the fact that only one project exists.
2. **Project isolation is strict.** Load only the selected project's profile. Never borrow missing facts, keywords, links, assets, or contact details from another project.
3. **Target is already vetted.** This skill does not discover new backlink targets. Use a target the user selected, a vetted queue the user opened, or an already-open submission page.
4. **Final submit is human-only.** Never click the final Submit, Publish, Launch, Create Listing, Send for Review, Post, or equivalent irreversible action.
5. **Security challenges are human-only.** Do not solve or bypass CAPTCHA, slider challenges, Cloudflare checks, 2FA, passkeys, phone verification, or similar security checks.

## Browser choice

Prefer the Codex Chrome extension when the task needs the user's existing Chrome profile, cookies, signed-in sessions, open tabs, or Chrome extensions. If only a current browser tab is available, work on that tab.

Never ask the user to paste passwords into chat. If normal Google/GitHub social login is visible, it is acceptable to click it and use the browser's existing signed-in session. If a security challenge appears, stop for human takeover and resume on the same tab afterward.

## Workflow

1. Resolve the explicit project ID/name from `../../references/project-registry.json` and load only its profile.
2. Resolve the target:
   - use a URL/site explicitly named by the user; otherwise
   - use the currently open submission page; otherwise
   - if the user has opened the configured vetted Google Sheet queue in Chrome, read the queue tab named in the project profile and use the row the user selected or clearly marked as next.
   - If the queue has no reliable status/next marker, do not guess what has already been submitted. Surface the best visible vetted candidate and wait for the user's go-ahead.
3. Open the target submission page if needed.
4. Handle normal existing-session login when possible. Hand security challenges to the user.
5. Inspect the whole visible form before filling fields.
6. Map fields to canonical project data:
   - exact reviewed values first;
   - shorten, reorganize, paraphrase, or select among approved values only when field length, format, category options, tag limits, or site context require it;
   - never invent a feature, pricing fact, metric, award, integration, founder fact, audience claim, AI capability, testimonial, or other product claim not present in the selected profile;
   - use approved keywords naturally; do not keyword-stuff.
7. For unusual free-text questions, answer only from approved facts. For blog/article comments, read the article first and write a genuinely relevant comment; do not force exact-match anchors.
8. Leave file uploads/manual fields alone when the approved asset or value is not configured.
9. Fill every safe applicable field, then stop before final submission.
10. Report briefly what was filled, what still needs manual attention, and that final submission was intentionally not clicked.

## Missing data

If a required field is absent from the selected project profile, flag it as missing. Do not search another project and do not invent a value.
