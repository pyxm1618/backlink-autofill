# backlink-autofill

**No separate LLM API.** This project is now a Codex plugin/Skill that uses the model included in the user's signed-in Codex/ChatGPT plan. Browser work should use Codex browser capabilities, preferably the Codex Chrome extension when the task needs the user's existing Chrome profile, cookies, logged-in sessions, or open tabs.

## What it does

`$backlink-autofill` handles one narrow workflow:

1. Require an explicit current project.
2. Load only that project's reviewed SEO/submission profile.
3. Use an already-vetted backlink target or queue opened by the user.
4. Work in the browser and try normal existing-session Google/GitHub login when appropriate.
5. Fill the form from reviewed project facts and keywords; only make necessary site/length adaptations.
6. Stop for CAPTCHA/2FA/security challenges.
7. **Never click the final Submit/Publish/Launch action.** The user reviews and submits manually.

Quick I Ching is included as the first reviewed project profile. The private Google Sheet URL/ID is intentionally not committed; for the MVP, open the vetted Sheet/target in the signed-in Chrome profile before invoking the skill.

## Install for personal Codex use

From this repository:

```bash
python3 scripts/install-personal.py
```

Following OpenAI's current personal plugin convention, the installer copies the plugin into `~/plugins/backlink-autofill` and safely adds/updates `./plugins/backlink-autofill` in `~/.agents/plugins/marketplace.json` without deleting other plugin entries.

Restart/reload Codex after installation.

## First real test

1. Sign in to Codex with your ChatGPT/Codex subscription.
2. Install/connect the official Codex Chrome extension if you want Codex to use your existing Chrome login state.
3. In that Chrome profile, open either:
   - one real vetted backlink submission page; or
   - your vetted BacklinkOS Google Sheet queue.
4. In Codex, send:

```text
$backlink-autofill
当前项目：Quick I Ching。
用我现在 Chrome 里打开的目标页面/外链表继续，填好所有能安全填写的内容，最终提交前停下让我检查。
```

If the Sheet does not have a reliable status/next marker, the skill will not guess what has already been submitted; select a row/target first for this initial test.

## Repository layout

```text
.agents/plugins/marketplace.json
plugins/backlink-autofill/
  .codex-plugin/plugin.json
  skills/backlink-autofill/SKILL.md
  references/project-registry.json
  references/projects/quick-iching.md
scripts/install-personal.py
scripts/validate-plugin.mjs
```

## Validation

```bash
node scripts/validate-plugin.mjs
```

GitHub Actions also runs the validator and tests the personal installer in an isolated HOME directory.

## ChatGPT web

The plugin uses the open plugin/Skill packaging model, but personal Skill availability in ChatGPT web depends on the user's plan and rollout. The first supported path for this repository is **Codex + Codex Chrome extension**, because it can use the user's subscription model and existing Chrome session without a separate model API key.
