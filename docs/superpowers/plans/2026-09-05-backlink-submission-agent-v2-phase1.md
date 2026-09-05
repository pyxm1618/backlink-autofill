# Backlink Submission Agent v2 Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a real project-isolated submission loop that reads the existing multi-project Google Sheet queue, processes up to 100 pending rows per invocation, executes ordinary submissions headlessly, opens a visible browser only for human-only blockers, and writes evidence-backed outcomes back to the exact project rows.

**Architecture:** Google Sheets is a structured control plane accessed through the official Google Drive connector; browser automation never clicks spreadsheet cells. A local Playwright runtime uses one persistent Chrome profile for headless execution and headed human takeover, while Codex remains the reasoning/orchestration layer and never calls a separate LLM API. The first phase deliberately does not redesign discovery or synchronize platform facts into the legacy master table.

**Tech Stack:** Codex plugin/Skill, official Google Drive connector, Python 3.11+, Playwright Python 1.62.0, Google Chrome stable channel with Chromium fallback for CI, Node.js 22 validator, GitHub Actions Ubuntu runner.

**Spec:** `docs/superpowers/specs/2026-09-05-backlink-submission-agent-v2-design.md`

## Global Constraints

- Explicit project selection is mandatory.
- Current queue source remains the existing `外链管理总控表` / `多项目外链进度与排期表` compatibility schema.
- Select only exact current-project rows with `当前状态 = 1-待提交 (To Submit)`.
- Default maximum is 100 eligible rows **per invocation**, not per day.
- No cron, scheduler, Automations dependency, daily quota, or calendar logic.
- Do not change backlink discovery or project-row creation/population in this plan.
- Do not write execution-observed platform facts into the legacy master/channel table in this plan.
- Google Sheet reads/writes use the Google Drive connector; browser automation must not manipulate Sheet UI.
- Browser execution is headless by default; human-only blockers reopen the same persistent profile visibly.
- Final Submit may be automatic only for ordinary free/non-sensitive flows with no human-only blocker.
- Never solve/bypass CAPTCHA, Cloudflare, 2FA, passkeys, SMS/phone verification, or similar security controls.
- Never store passwords in repo, private profile, runtime checkpoint, or recipe.
- Shared personal data comes only from `~/.backlink-autofill/submitter-profile.json`.
- Project data/assets come only from the selected project's public profile and `~/.backlink-autofill/projects/<project-id>/`; no sibling fallback.
- No `SUBMITTED`, `UNDER_REVIEW`, `SCHEDULED`, or `LIVE` state without real browser evidence.
- Every Sheet mutation must target the original row number and be verified by a re-read.

---

## File Structure

Create/modify these focused units:

```text
plugins/backlink-autofill/
├── .app.json                                      # official Google Drive connector binding
├── .codex-plugin/plugin.json                      # apps binding + v0.2.0 metadata
├── references/
│   ├── project-sheet-contract.md                  # exact current Sheet schema/status/write contract
│   └── projects/quick-iching.md                   # remove obsolete Chrome-opened-queue assumptions
├── skills/backlink-autofill/SKILL.md              # queue orchestration and autonomous-submit policy
├── scripts/
│   ├── browser_cli.py                             # CLI entrypoint; JSON in/out only
│   ├── browser_runtime.py                         # Playwright persistent context + safe actions
│   ├── execution_state.py                         # status mapping/checkpoints/recipes
│   └── requirements.txt                           # playwright==1.62.0
└── tests/
    ├── fixtures/
    │   ├── form.html                              # local form with text/select/file/final submit
    │   └── challenge.html                         # local human-takeover simulation
    ├── test_execution_state.py
    └── test_browser_runtime.py
scripts/
├── configure-project-execution.py                 # writes private execution.json safely
├── install-personal.py                            # preserve runtime/project config + runtime directories
└── validate-plugin.mjs                            # structural hard gates
.github/workflows/plugin-ci.yml                    # unit + real local-browser E2E
README.md
docs/private-data-model.md
```

Private runtime layout after installation/configuration:

```text
~/.backlink-autofill/
├── submitter-profile.json
├── browser-profile/
├── runtime/<project-id>/
├── recipes/
└── projects/<project-id>/
    ├── execution.json
    ├── assets.json
    └── assets/...
```

---

### Task 1: Bind Google Drive and lock the live Sheet compatibility contract

**Files:**
- Create: `plugins/backlink-autofill/.app.json`
- Create: `plugins/backlink-autofill/references/project-sheet-contract.md`
- Modify: `plugins/backlink-autofill/.codex-plugin/plugin.json`
- Modify: `scripts/validate-plugin.mjs`

**Interfaces:**
- Consumes: official portable Google Drive connector ID `connector_5f3c8c41a1e54ad7a76272c89e2554fa`.
- Produces: plugin app binding `google-drive`; canonical legacy Sheet contract used by later Skill tasks.

- [ ] **Step 1: Write validator assertions first**

Add failing assertions to `scripts/validate-plugin.mjs` before creating `.app.json`:

```js
const appBindingPath = path.join(pluginRoot, '.app.json')
assert(fs.existsSync(appBindingPath), 'Google Drive app binding missing')
const appBinding = readJson(appBindingPath)
assert(manifest.apps === './.app.json', 'plugin manifest must expose ./.app.json')
assert(
  appBinding.apps?.['google-drive']?.id === 'connector_5f3c8c41a1e54ad7a76272c89e2554fa',
  'official Google Drive connector binding missing'
)

const sheetContract = fs.readFileSync(
  path.join(pluginRoot, 'references', 'project-sheet-contract.md'),
  'utf8'
)
assert(sheetContract.includes('多项目外链进度与排期表'), 'live project sheet name missing')
assert(sheetContract.includes('1-待提交 (To Submit)'), 'pending compatibility status missing')
assert(sheetContract.includes('maximum 100'), 'per-run batch contract missing')
```

Remove the old assertion that the MVP must have no `manifest.apps`.

- [ ] **Step 2: Run validator and verify RED**

Run:

```bash
node scripts/validate-plugin.mjs
```

Expected: FAIL because `.app.json` / manifest apps / contract do not exist yet.

- [ ] **Step 3: Add the minimal app binding**

Create `plugins/backlink-autofill/.app.json`:

```json
{
  "apps": {
    "google-drive": {
      "id": "connector_5f3c8c41a1e54ad7a76272c89e2554fa"
    }
  }
}
```

Modify `plugin.json`:

```json
"version": "0.2.0",
"skills": "./skills/",
"apps": "./.app.json"
```

Change capabilities to include `Write` because the plugin now writes execution state to Sheets.

- [ ] **Step 4: Write the exact compatibility reference**

`project-sheet-contract.md` must define:

```text
Spreadsheet role: existing execution queue
Tab: 多项目外链进度与排期表
Project filter: exact 项目名称
Pending value: 1-待提交 (To Submit)
Default run maximum: 100
Columns:
A 项目名称
B 外链平台
C 当前状态
D 提交日期
E 预计上线 / 计划 Launch 日期
F 履约/要求配合状态
G 实际落地链接 (Live URL)
H 实际是否 DoFollow
I Google 收录
J 被推广目标页 (Target URL)
K 锚文本 / 关键词
L 账号 / 备注
```

Include 0-based Google Sheets column indexes for write requests: `C=2`, `D=3`, `G=6`, `L=11`.

Define compatibility statuses exactly as in the spec and explicitly forbid mutation of rows whose `项目名称` differs from the selected project.

- [ ] **Step 5: Run validator and verify GREEN**

Run:

```bash
node scripts/validate-plugin.mjs
```

Expected: `plugin validation passed`.

- [ ] **Step 6: Commit**

```bash
git add plugins/backlink-autofill/.app.json \
  plugins/backlink-autofill/.codex-plugin/plugin.json \
  plugins/backlink-autofill/references/project-sheet-contract.md \
  scripts/validate-plugin.mjs
git commit -m "feat: bind Google Drive project queue"
```

---

### Task 2: Add private per-project execution configuration without touching sibling projects

**Files:**
- Create: `scripts/configure-project-execution.py`
- Modify: `scripts/install-personal.py`
- Modify: `docs/private-data-model.md`
- Modify: `.github/workflows/plugin-ci.yml`

**Interfaces:**
- Consumes: project ID from plugin registry; private spreadsheet ID/name supplied at setup time.
- Produces: `~/.backlink-autofill/projects/<project-id>/execution.json` with `queue.spreadsheet_id`, `queue.sheet_name`, `queue.project_name`, `default_batch_size`.

- [ ] **Step 1: Add an installer/configuration regression test first**

Extend the isolated-HOME CI block so it precreates:

```text
~/.backlink-autofill/projects/project-b/marker.txt = KEEP
~/.backlink-autofill/projects/quick-iching/execution.json = existing custom config
```

Then rerun `install-personal.py` and assert both files remain byte-for-byte unchanged.

Add a separate invocation of the future configuration script:

```bash
python3 scripts/configure-project-execution.py \
  --project-id quick-iching \
  --spreadsheet-id TEST_SHEET_ID \
  --sheet-name '多项目外链进度与排期表' \
  --project-name 'Quick I Ching' \
  --home "$HOME"
```

Assert:

```python
payload == {
    'schema_version': 1,
    'project_id': 'quick-iching',
    'queue': {
        'spreadsheet_id': 'TEST_SHEET_ID',
        'sheet_name': '多项目外链进度与排期表',
        'project_name': 'Quick I Ching',
    },
    'default_batch_size': 100,
}
```

and `project-b/marker.txt` still equals `KEEP`.

- [ ] **Step 2: Run CI-equivalent block and verify RED**

Run the relevant shell/Python block locally or in Actions.

Expected: FAIL because `configure-project-execution.py` does not exist and runtime directories are not yet ensured.

- [ ] **Step 3: Implement `configure-project-execution.py` minimally**

Required CLI:

```python
parser.add_argument('--project-id', required=True)
parser.add_argument('--spreadsheet-id', required=True)
parser.add_argument('--sheet-name', required=True)
parser.add_argument('--project-name', required=True)
parser.add_argument('--batch-size', type=int, default=100)
parser.add_argument('--home', default=str(Path.home()))
```

Validate:

```python
if not 1 <= args.batch_size <= 100:
    raise SystemExit('batch-size must be between 1 and 100')
```

Write only:

```text
<home>/.backlink-autofill/projects/<project-id>/execution.json
```

Use atomic replacement (`tempfile.NamedTemporaryFile` in same directory + `Path.replace`) so an interrupted write cannot corrupt the config.

- [ ] **Step 4: Ensure runtime directories without replacing content**

Extend `ensure_private_data_root()` to `mkdir(..., exist_ok=True)` only for:

```text
browser-profile/
runtime/
recipes/
```

Do not delete or recreate their contents during reinstall.

- [ ] **Step 5: Document the private schema**

Add to `docs/private-data-model.md` the exact `execution.json` schema and state that spreadsheet IDs are private local configuration and must not enter Git.

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```bash
node scripts/validate-plugin.mjs
# plus the isolated HOME installer/config test used by plugin-ci.yml
```

Expected: all assertions pass; sibling project marker and existing profile/config survive reinstall.

- [ ] **Step 7: Commit**

```bash
git add scripts/configure-project-execution.py scripts/install-personal.py \
  docs/private-data-model.md .github/workflows/plugin-ci.yml
git commit -m "feat: add private project queue config"
```

---

### Task 3: Build deterministic status/checkpoint/recipe storage before browser automation

**Files:**
- Create: `plugins/backlink-autofill/scripts/execution_state.py`
- Create: `plugins/backlink-autofill/tests/test_execution_state.py`

**Interfaces:**
- Produces:
  - `sheet_status_to_internal(value: str) -> str | None`
  - `internal_to_sheet_status(value: str) -> str`
  - `save_checkpoint(root: Path, checkpoint: dict) -> Path`
  - `load_checkpoint(root: Path, project_id: str, row_number: int) -> dict | None`
  - `delete_checkpoint(...) -> None`
  - `save_recipe(root: Path, domain: str, recipe: dict) -> Path`
  - `load_recipe(root: Path, domain: str) -> dict | None`

- [ ] **Step 1: Write failing unit tests**

Test exact status mappings:

```python
self.assertEqual(sheet_status_to_internal('1-待提交 (To Submit)'), 'PENDING')
self.assertEqual(sheet_status_to_internal('2-排队审核中 (In Review)'), 'UNDER_REVIEW')
self.assertEqual(sheet_status_to_internal('3-已排期待Launch (Scheduled)'), 'SCHEDULED')
self.assertEqual(sheet_status_to_internal('4-已成功上线 (Live)'), 'LIVE')
self.assertEqual(internal_to_sheet_status('NEEDS_HUMAN'), '需人工 (Needs Human)')
self.assertEqual(internal_to_sheet_status('NOT_APPLICABLE'), '不适用 (Not Applicable)')
```

Test checkpoint path isolation:

```python
checkpoint = {
    'schema_version': 1,
    'project_id': 'quick-iching',
    'row_number': 17,
    'domain': 'example.com',
    'url': 'https://example.com/submit',
    'state': 'IN_PROGRESS',
    'replay_actions': [],
    'evidence': {},
}
path = save_checkpoint(root, checkpoint)
self.assertTrue(path.is_file())
self.assertNotIn('project-b', str(path))
self.assertEqual(load_checkpoint(root, 'quick-iching', 17)['domain'], 'example.com')
```

Test recipes reject password-like keys recursively (`password`, `passwd`, `secret`, `token`).

- [ ] **Step 2: Run test and verify RED**

```bash
python3 -m unittest plugins.backlink-autofill.tests.test_execution_state -v
```

If package path layout makes dotted import awkward, run:

```bash
python3 plugins/backlink-autofill/tests/test_execution_state.py
```

Expected: import/module failure because implementation is absent.

- [ ] **Step 3: Implement minimal pure-Python state module**

Use only the standard library. Canonical mappings:

```python
SHEET_TO_INTERNAL = {
    '1-待提交 (To Submit)': 'PENDING',
    '2-排队审核中 (In Review)': 'UNDER_REVIEW',
    '3-已排期待Launch (Scheduled)': 'SCHEDULED',
    '4-已成功上线 (Live)': 'LIVE',
    '处理中 (In Progress)': 'IN_PROGRESS',
    '已提交待确认 (Submitted)': 'SUBMITTED',
    '需人工 (Needs Human)': 'NEEDS_HUMAN',
    '失败 (Failed)': 'FAILED',
    '不适用 (Not Applicable)': 'NOT_APPLICABLE',
}
```

Store checkpoints at:

```text
<root>/runtime/<project-id>/row-<row_number>.json
```

Store recipes at:

```text
<root>/recipes/<canonical-domain>.json
```

Writes must be atomic and recipes must contain no project-specific content or credential-like keys.

- [ ] **Step 4: Run tests and verify GREEN**

Run the same unittest command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/backlink-autofill/scripts/execution_state.py \
  plugins/backlink-autofill/tests/test_execution_state.py
git commit -m "feat: add execution checkpoints and recipes"
```

---

### Task 4: Implement a real headless Playwright browser runtime with compact JSON evidence

**Files:**
- Create: `plugins/backlink-autofill/scripts/requirements.txt`
- Create: `plugins/backlink-autofill/scripts/browser_runtime.py`
- Create: `plugins/backlink-autofill/scripts/browser_cli.py`
- Create: `plugins/backlink-autofill/tests/fixtures/form.html`
- Create: `plugins/backlink-autofill/tests/test_browser_runtime.py`

**Interfaces:**
- `BrowserRuntime(profile_dir: Path, headless: bool, channel: str | None = 'chrome')`
- `inspect(url: str) -> dict`
- `apply(url: str, actions: list[dict]) -> dict`
- CLI emits exactly one JSON document to stdout; operational logs go to stderr.

Action schema for Phase 1:

```json
{"type":"fill","locator":{"by":"label","value":"Your Name"},"value":"Tachyon Wang"}
{"type":"select","locator":{"by":"label","value":"Country"},"value":"China"}
{"type":"check","locator":{"by":"label","value":"Terms"},"checked":true}
{"type":"upload","locator":{"by":"label","value":"Logo"},"path":"/absolute/project/path/logo.png"}
{"type":"click","locator":{"by":"role","role":"button","name":"Continue"},"final":false}
{"type":"click","locator":{"by":"role","role":"button","name":"Submit"},"final":true}
```

- [ ] **Step 1: Add dependency pin**

`requirements.txt`:

```text
playwright==1.62.0
```

Do not add any model/API SDK.

- [ ] **Step 2: Write local-form E2E test first**

Create `form.html` with:

- labeled name/email/product fields;
- country select;
- file input;
- non-final `Continue` button;
- final `Submit` button;
- JavaScript that writes submitted values to a visible `#result` element after final submit instead of doing network I/O.

Test:

```python
runtime = BrowserRuntime(profile_dir, headless=True, channel=None)
snapshot = runtime.inspect(form_uri)
self.assertIn('Your Name', [f['label'] for f in snapshot['fields']])

result = runtime.apply(form_uri, [
    {'type': 'fill', 'locator': {'by': 'label', 'value': 'Your Name'}, 'value': 'Tachyon Wang'},
    {'type': 'fill', 'locator': {'by': 'label', 'value': 'Product'}, 'value': 'Quick I Ching'},
    {'type': 'select', 'locator': {'by': 'label', 'value': 'Country'}, 'value': 'China'},
    {'type': 'click', 'locator': {'by': 'role', 'role': 'button', 'name': 'Submit'}, 'final': True},
])
self.assertTrue(result['final_action_executed'])
self.assertIn('Quick I Ching', result['page_text'])
```

- [ ] **Step 3: Install Playwright and verify RED**

```bash
python3 -m pip install -r plugins/backlink-autofill/scripts/requirements.txt
python3 -m playwright install chromium
python3 plugins/backlink-autofill/tests/test_browser_runtime.py
```

Expected: FAIL because `BrowserRuntime` is absent.

- [ ] **Step 4: Implement compact inspection**

The snapshot must return only useful state, not full HTML by default:

```json
{
  "url": "...",
  "title": "...",
  "fields": [
    {"tag":"input","type":"text","label":"Your Name","name":"name","required":true,"value":""}
  ],
  "buttons": [
    {"role":"button","name":"Submit","disabled":false}
  ],
  "page_text_excerpt": "..."
}
```

Use label/role/name/placeholder locators before CSS selectors. Bound `page_text_excerpt` to a small size (e.g. 4,000 characters) to avoid token-heavy full-page dumps.

- [ ] **Step 5: Implement allowlisted actions and read-back evidence**

Reject unknown action types. `upload` must require an absolute existing file path. `final=true` is recorded explicitly in the result. After the action list, inspect the page again and return actual state.

Do not add CAPTCHA solving, arbitrary JavaScript execution, raw CDP command execution, credential extraction, or password storage.

- [ ] **Step 6: Run E2E and verify GREEN**

```bash
python3 plugins/backlink-autofill/tests/test_browser_runtime.py
```

Expected: local form is filled and final submit is observed in real headless Chromium.

- [ ] **Step 7: Commit**

```bash
git add plugins/backlink-autofill/scripts/requirements.txt \
  plugins/backlink-autofill/scripts/browser_runtime.py \
  plugins/backlink-autofill/scripts/browser_cli.py \
  plugins/backlink-autofill/tests/fixtures/form.html \
  plugins/backlink-autofill/tests/test_browser_runtime.py
git commit -m "feat: add headless browser execution runtime"
```

---

### Task 5: Add safe headed human takeover and replay using the same persistent profile

**Files:**
- Modify: `plugins/backlink-autofill/scripts/browser_runtime.py`
- Modify: `plugins/backlink-autofill/scripts/browser_cli.py`
- Create: `plugins/backlink-autofill/tests/fixtures/challenge.html`
- Modify: `plugins/backlink-autofill/tests/test_browser_runtime.py`

**Interfaces:**
- CLI command: `handoff --checkpoint <path>`
- `replay_actions` contains only reversible actions: fill/select/check/upload/non-final navigation where explicitly marked replay-safe.
- Final-submit actions are never replayed automatically during handoff restoration.

- [ ] **Step 1: Write failing persistent-profile/handoff tests**

Test persistence:

1. launch headless with profile dir;
2. set a cookie/localStorage marker on fixture;
3. close;
4. reopen headed with the same profile dir under Xvfb;
5. verify the marker is present.

Test replay filtering:

```python
safe = filter_replay_actions([
    {'type':'fill', ...},
    {'type':'click', 'final':False, 'replay_safe':True, ...},
    {'type':'click', 'final':True, ...},
])
self.assertEqual(len(safe), 2)
self.assertFalse(any(a.get('final') for a in safe))
```

- [ ] **Step 2: Run headed test and verify RED**

On Linux CI/local:

```bash
xvfb-run -a python3 plugins/backlink-autofill/tests/test_browser_runtime.py
```

Expected: FAIL because headed handoff/replay is not implemented.

- [ ] **Step 3: Implement handoff**

`handoff --checkpoint` must:

1. load checkpoint;
2. launch `headless=False` with the same profile dir;
3. navigate to checkpoint URL;
4. replay only safe reversible actions;
5. leave the visible browser open for the user;
6. never auto-resolve a security challenge;
7. after the human closes the browser window, emit a JSON result showing the final URL/title so Codex can inspect/resume in the next headless step.

- [ ] **Step 4: Add challenge fixture**

`challenge.html` should simulate a blocker with a visible `Human verification required` marker and a manually clickable `I completed verification` button that sets localStorage/cookie state.

Verify headless detects the blocker only as page evidence, headed user simulation toggles it, then a subsequent headless reopen sees the persisted completion state.

- [ ] **Step 5: Run tests and verify GREEN**

```bash
xvfb-run -a python3 plugins/backlink-autofill/tests/test_browser_runtime.py
```

Expected: headless → headed → headless profile continuity passes; final action is never replayed.

- [ ] **Step 6: Commit**

```bash
git add plugins/backlink-autofill/scripts/browser_runtime.py \
  plugins/backlink-autofill/scripts/browser_cli.py \
  plugins/backlink-autofill/tests/fixtures/challenge.html \
  plugins/backlink-autofill/tests/test_browser_runtime.py
git commit -m "feat: add visible human browser handoff"
```

---

### Task 6: Rewrite the Skill from single-form autofill to the 100-row project queue executor

**Files:**
- Modify: `plugins/backlink-autofill/skills/backlink-autofill/SKILL.md`
- Modify: `plugins/backlink-autofill/references/projects/quick-iching.md`
- Modify: `scripts/validate-plugin.mjs`

**Interfaces:**
- Consumes: Google Drive app actions, `execution.json`, shared profile, selected project assets, `browser_cli.py`, `execution_state.py`.
- Produces: deterministic orchestration protocol for one invocation.

- [ ] **Step 1: Add failing Skill hard-gate assertions first**

Validator must require phrases/sections covering:

```js
assert(skill.includes('Default run maximum: 100'), 'per-run queue maximum missing')
assert(skill.includes('Google Drive connector'), 'structured Sheet access boundary missing')
assert(skill.includes('exact project name'), 'project-row isolation missing')
assert(skill.includes('1-待提交 (To Submit)'), 'legacy pending status missing')
assert(skill.includes('headless by default'), 'headless default missing')
assert(skill.includes('automatic final submission'), 'autonomous final-submit policy missing')
assert(skill.includes('visible human takeover'), 'headed handoff rule missing')
assert(skill.includes('master fact synchronization is out of scope'), 'legacy master write prohibition missing')
```

Remove the old validator assertion requiring `Final submit is human-only`.

- [ ] **Step 2: Run validator and verify RED**

```bash
node scripts/validate-plugin.mjs
```

Expected: FAIL against the old Skill.

- [ ] **Step 3: Replace the old queue/browser workflow**

The Skill must execute this sequence:

```text
A. Resolve explicit project ID.
B. Load ~/.backlink-autofill/projects/<id>/execution.json.
C. Use Google Drive connector metadata to confirm spreadsheet/tab.
D. Read/search bounded chunks of A:L and collect exact-project rows only.
E. Select at most N pending rows, N default 100 and <=100.
F. For each selected row:
   1. re-read exact row before mutation;
   2. verify project name and pending status are unchanged;
   3. write 处理中 (In Progress), verify write;
   4. create local checkpoint;
   5. execute website through browser_cli headlessly;
   6. use selected-project facts/profile/assets only;
   7. if ordinary safe flow, allow automatic final Submit;
   8. if human blocker, write 需人工, append concise reason, verify, open headed handoff;
   9. classify resulting evidence;
   10. write exact final status/date/result URL/note fields that are actually supported by evidence;
   11. verify Sheet write;
   12. delete checkpoint only after durable final-state write.
G. Stop after N attempted queue items or queue exhaustion.
```

Important: count a row against the invocation maximum once it transitions from `PENDING` to `IN_PROGRESS`, even if it ends in `NEEDS_HUMAN`, `FAILED`, or `NOT_APPLICABLE`. This prevents one invocation from scanning unlimited bad targets.

- [ ] **Step 4: Define exact Google Sheets write semantics in the Skill/reference**

Before write, re-read target row with cell metadata. Use `batch_update_spreadsheet` `updateCells` requests against the actual `sheetId` returned by metadata.

For row number `r`, Sheet API row indexes are:

```text
startRowIndex = r - 1
endRowIndex   = r
```

Write only cells that need changing. For example status C:

```json
{
  "updateCells": {
    "range": {
      "sheetId": 2139391078,
      "startRowIndex": 16,
      "endRowIndex": 17,
      "startColumnIndex": 2,
      "endColumnIndex": 3
    },
    "rows": [
      {"values": [{"userEnteredValue": {"stringValue": "处理中 (In Progress)"}}]}
    ],
    "fields": "userEnteredValue"
  }
}
```

The numeric `sheetId` above is an example from the current live workbook metadata; runtime must always use freshly read metadata rather than hardcoding it.

For notes, read existing L first, append rather than overwrite:

```text
[2026-09-05T10:30:00+08:00][backlink-agent] NEEDS_HUMAN: CAPTCHA
```

- [ ] **Step 5: Remove obsolete assumptions**

From Quick I Ching public profile remove/replace the old `Preferred vetted queue tab: 严格免费外链` execution instruction. That tab belongs to the old candidate flow, not v2 execution.

Public project profile should only name project facts; private execution Sheet ID stays in `execution.json`.

- [ ] **Step 6: Run validator and verify GREEN**

```bash
node scripts/validate-plugin.mjs
```

Expected: pass with new queue/handoff/final-submit boundaries.

- [ ] **Step 7: Commit**

```bash
git add plugins/backlink-autofill/skills/backlink-autofill/SKILL.md \
  plugins/backlink-autofill/references/projects/quick-iching.md \
  scripts/validate-plugin.mjs
git commit -m "feat: execute project backlink queue"
```

---

### Task 7: CI, installation docs, and staged real acceptance

**Files:**
- Modify: `.github/workflows/plugin-ci.yml`
- Modify: `README.md`
- Modify: `scripts/install-personal.py` only if dependency/runtime checks are still missing after Task 2.

**Interfaces:**
- Produces: reproducible structural tests, Python unit tests, real local headless browser E2E, virtual-display headed handoff test, and manual live-queue acceptance procedure.

- [ ] **Step 1: Make CI fail until browser tests are wired**

Add CI steps after existing installer validation:

```yaml
- name: Install browser runtime test dependency
  run: |
    python3 -m pip install -r plugins/backlink-autofill/scripts/requirements.txt
    python3 -m playwright install --with-deps chromium

- name: Run execution-state tests
  run: python3 plugins/backlink-autofill/tests/test_execution_state.py

- name: Run headless browser E2E
  run: python3 plugins/backlink-autofill/tests/test_browser_runtime.py

- name: Run headed handoff E2E
  run: xvfb-run -a python3 plugins/backlink-autofill/tests/test_browser_runtime.py
```

Initially ensure this fails before browser tests/runtime are complete if implementing tasks out of order.

- [ ] **Step 2: Update README to the new runtime model**

Document only the current supported flow:

```text
Codex = reasoning/orchestration
Google Drive connector = project queue reads/writes
Playwright persistent browser = website execution
Headless = normal path
Headed = human exception path
```

Remove README language saying final Submit is always human-only.

Document one-time private queue setup using `configure-project-execution.py`; do not publish real spreadsheet IDs.

- [ ] **Step 3: Run full local verification**

```bash
node scripts/validate-plugin.mjs
python3 plugins/backlink-autofill/tests/test_execution_state.py
python3 plugins/backlink-autofill/tests/test_browser_runtime.py
xvfb-run -a python3 plugins/backlink-autofill/tests/test_browser_runtime.py  # Linux only
```

Expected: all green.

- [ ] **Step 4: Verify GitHub Actions fresh run**

Push the branch and wait for `Plugin CI`. Require every step to finish `success`; do not infer success from local tests.

- [ ] **Step 5: Perform Sheet read-only live acceptance before any real submission**

Using the installed plugin and connected Google Drive:

1. configure Quick I Ching `execution.json` to the existing execution workbook/tab;
2. ask the agent for a **read-only queue preview**;
3. verify it returns only Quick I Ching rows and at most 100 `1-待提交` rows;
4. verify it reports zero rows cleanly if Quick I Ching has not yet been populated;
5. verify no Sheet cell changed.

The current live inspection on 2026-09-05 found zero Quick I Ching rows, so this zero-queue behavior is an expected first acceptance result until the discovery/write workflow adds rows.

- [ ] **Step 6: Perform first real one-row submission acceptance only after a Quick I Ching pending row exists**

Invoke with batch size `1` first, regardless of the default 100:

```text
$backlink-autofill
当前项目：Quick I Ching。
这次只处理 1 条待提交记录，真实执行并按规则回写状态。
```

Acceptance requires evidence of all of the following:

- only the selected Quick I Ching row was touched;
- row moved from pending to in-progress before website mutation;
- website was actually controlled by the local Playwright runtime;
- normal flow ran headlessly;
- final Submit was automatic if no blocker existed;
- resulting browser state was read back;
- exact Sheet row was updated to an evidence-supported outcome;
- Sheet write was re-read and verified;
- no other project's row changed;
- if a human blocker occurred, a visible browser using the persistent profile opened and the row became `需人工` rather than being falsely marked submitted.

Do not test batch size 100 until the one-row acceptance is proven.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/plugin-ci.yml README.md scripts/install-personal.py
git commit -m "test: verify v2 submission agent runtime"
```

---

## Final Verification Gate Before Calling Phase 1 Complete

Run and record fresh evidence for:

```bash
node scripts/validate-plugin.mjs
python3 plugins/backlink-autofill/tests/test_execution_state.py
python3 plugins/backlink-autofill/tests/test_browser_runtime.py
```

On Linux CI also require:

```bash
xvfb-run -a python3 plugins/backlink-autofill/tests/test_browser_runtime.py
```

Then verify the latest GitHub Actions run is `success`.

Finally, perform the live acceptance in two gates:

1. read-only Quick I Ching queue preview;
2. exactly one real pending target submission.

Only after both pass may the default multi-row run be considered usable. The existing PR should remain draft until the first real one-row browser + Sheet writeback flow is verified end-to-end.