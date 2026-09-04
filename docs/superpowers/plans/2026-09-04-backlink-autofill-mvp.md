# Backlink Autofill MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt the upstream Chrome submission extension into a project-isolated, canonical-data-grounded backlink autofill tool driven by the user's existing Google Sheet.

**Architecture:** Keep the upstream WXT + React + Page Agent browser execution model. Replace free-form product generation with reviewed canonical project profiles, add a narrow Sheet target source, and constrain the agent prompt so canonical facts are authoritative and final submit remains human-only.

**Tech Stack:** TypeScript, React 19, WXT, Chrome Extension APIs, IndexedDB (`idb`), Alibaba Page Agent 1.7.x, Google Sheets API.

**Spec:** `docs/superpowers/specs/2026-09-04-backlink-autofill-mvp-design.md`

## Global Constraints

- Final Submit/Publish is never clicked by the agent.
- No CAPTCHA/security challenge bypass.
- One explicit active project per run; no cross-project data mixing.
- AI may adapt reviewed copy to field constraints but may not invent product facts.
- Keep Page Agent on the upstream-compatible 1.7.x line during MVP.
- Reuse the user's existing BacklinkOS Google Sheet instead of building a new backlink database.

---

### Task 1: Import a clean upstream extension baseline

**Files:**
- Create: `extension/**` from upstream excluding demo media and `.DS_Store`
- Create: `LICENSE`

**Interfaces:**
- Consumes: upstream `subodhkc/AI-Directory-Autofill-Chrome-Extension`
- Produces: a buildable WXT extension baseline on `feat/mvp-autofill`

- [ ] Copy required extension source/config files and MIT license.
- [ ] Preserve upstream dependency versions initially.
- [ ] Verify `npm install` and `npm run build` when a runnable checkout is available.

### Task 2: Add test harness and canonical profile behavior

**Files:**
- Modify: `extension/package.json`
- Modify: `extension/src/lib/types.ts`
- Create: `extension/src/lib/project-context.ts`
- Test: `extension/src/lib/project-context.test.ts`

**Interfaces:**
- Produces: `buildProjectContext(project: ProductProfile): string` and canonical profile fields.

- [ ] Write failing tests proving primary/secondary keywords, approved descriptions, claims and prohibited claims appear in context.
- [ ] Run tests and confirm failure because the canonical fields/context builder do not exist.
- [ ] Add minimal profile fields and context builder.
- [ ] Run tests and confirm pass.

### Task 3: Constrain agent generation to reviewed project data

**Files:**
- Modify: `extension/src/agent/SubmitAgent.ts`
- Modify: `extension/src/agent/submit-prompt.md`
- Modify: `extension/src/hooks/useSubmitAgent.ts`
- Test: `extension/src/lib/project-context.test.ts`

**Interfaces:**
- Consumes: `buildProjectContext`
- Produces: prompt rules enforcing canonical-data priority and no fact invention.

- [ ] Extend tests with required grounding rules in generated context/instructions.
- [ ] Verify tests fail first.
- [ ] Replace generic `buildProductContext` usage with the canonical project context.
- [ ] Update prompt: exact values first; adaptation only for field constraints; approved keyword pool only; no invented claims; stop before final submit.
- [ ] Run tests/build.

### Task 4: Make project selection a hard gate

**Files:**
- Modify: `extension/src/hooks/useProduct.ts`
- Modify: `extension/src/entrypoints/sidepanel/App.tsx`
- Modify: `extension/src/lib/storage.ts`
- Test: `extension/src/lib/active-project.test.ts`

**Interfaces:**
- Produces: no implicit fallback from missing active project to the first stored project.

- [ ] Write failing test for explicit active-project resolution.
- [ ] Verify failure.
- [ ] Remove implicit `products[0]` fallback; require stored active ID.
- [ ] Keep UI project selector and block agent start when no project is selected.
- [ ] Run tests/build.

### Task 5: Add Google Sheet target source

**Files:**
- Modify: `extension/src/lib/types.ts`
- Create: `extension/src/lib/sheets.ts`
- Modify: `extension/src/lib/sites.ts`
- Modify: `extension/wxt.config.ts`
- Test: `extension/src/lib/sheets.test.ts`

**Interfaces:**
- Produces: `parseSheetTargets(values)` and `loadSheetTargets(project)` returning minimal `SiteData[]`.

- [ ] Write failing parser tests using a representative BacklinkOS header/row shape (`优先级`, `外链来源域名`, `机会类型`, `提交/入口地址`, `核验说明`).
- [ ] Verify failure.
- [ ] Implement deterministic header-based mapping and skip rows without submit URLs.
- [ ] Add Google OAuth/Sheets read capability using the extension identity API or explicit access-token setup, keeping scope read-only.
- [ ] Use Sheet targets when project Sheet config exists; keep local sites only as fallback during migration.
- [ ] Run tests/build.

### Task 6: Update project editor for reviewed canonical data

**Files:**
- Modify: `extension/src/components/ProductForm.tsx`
- Modify: `extension/src/components/QuickCreate.tsx`
- Modify: `extension/src/entrypoints/options/App.tsx`
- Remove/disable: free-form AI profile generation entry path

**Interfaces:**
- Consumes/edits all canonical project profile fields.

- [ ] Add explicit inputs for primary keyword, secondary keywords, listing title, description variants, approved tags/categories, factual claims, prohibited claims, and Sheet configuration.
- [ ] Disable automatic profile creation as a source of truth; optional webpage extraction may only prefill a draft that requires review before save.
- [ ] Build and manually inspect compiled extension UI when runtime is available.

### Task 7: Verification

**Files:**
- No new production files unless fixing discovered defects.

- [ ] Run unit tests.
- [ ] Run `npm run build`.
- [ ] Confirm manifest still includes required tabs/storage/sidePanel/host access and adds only the minimum Google identity permission if used.
- [ ] Perform one real Quick I Ching + BacklinkOS target run in a Chrome environment when available.
- [ ] Confirm agent stops before final Submit and produces no claims outside the reviewed profile.
