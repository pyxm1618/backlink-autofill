# Backlink Autofill MVP Design

## Goal

Build a Chrome extension that helps one selected project submit to already-vetted backlink opportunities. The extension may open the target URL, attempt normal existing-session Google/GitHub OAuth, understand the current form, fill it with project-approved canonical submission data, and stop before the final Submit/Publish action for human review.

## Non-goals

- No CAPTCHA or security-challenge bypass.
- No password vault or credential automation.
- No mass auto-submit.
- No new backlink discovery engine.
- No adapter compiler, proxy system, or complex workflow engine.
- No AI invention of product facts.

## Core workflow

1. User selects the active project explicitly.
2. Extension loads only that project's canonical submission profile.
3. Extension reads backlink targets from the configured Google Sheet (initial target: BacklinkOS main database).
4. User opens a target, or the extension opens the chosen submit URL.
5. If login is required, the agent may click standard social OAuth (prefer Google/GitHub) using the browser profile's existing login state. CAPTCHA/2FA/security checks pause for human takeover.
6. Agent reads the whole form and maps each field to canonical project data.
7. Existing canonical values are used as-is when they fit. AI may only shorten, reorganize, or select among approved values when the site's field constraints require it.
8. Agent must not add product facts that are absent from the canonical profile.
9. Agent fills the form and stops before final Submit/Publish.
10. User reviews and submits manually.

## Project isolation

A project is the hard execution boundary. Every run has one `activeProjectId`; project profile, keywords, assets, Sheet config, and submission records are keyed by that project ID. The agent must refuse to run if no active project exists. It must never merge data from multiple projects.

## Canonical submission profile

Each project stores reviewed facts and reusable copy:

- name, canonical URL
- primary keyword
- secondary keywords
- listing title
- tagline
- descriptions: micro, short, medium, long
- approved tags
- approved category candidates
- factual features / claims
- prohibited claims
- founder/contact/social data
- logo/screenshots
- optional Google Sheet config

AI is a constrained adapter, not the source of truth.

## Backlink source

The existing Google Sheet remains the resource database. The extension should support a project-level Sheet ID/tab and map rows into a minimal target record containing domain/name, submit URL, priority/type and optional notes. The first implementation may use an explicitly configured tab/range rather than trying to auto-discover every sheet layout.

## Browser/login model

The extension runs inside a dedicated Chrome profile, so it naturally inherits its cookies and Google login state. Existing-session OAuth is allowed. Login failures, CAPTCHA, slider, Cloudflare, 2FA, phone confirmation, or other security checks become human handoff points.

## Validation

MVP acceptance is one real end-to-end path:

- select Quick I Ching;
- load one real target from the user's BacklinkOS Sheet;
- open its submission page;
- pass login automatically when existing-session OAuth works, otherwise human takeover;
- fill every applicable text/select field from reviewed Quick I Ching data;
- introduce no unapproved product claims;
- stop before final submit.
