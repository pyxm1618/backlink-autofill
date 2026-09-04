import fs from 'node:fs'
import path from 'node:path'

const root = process.cwd()
const pluginRoot = path.join(root, 'plugins', 'backlink-autofill')

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'))
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const marketplace = readJson(path.join(root, '.agents', 'plugins', 'marketplace.json'))
const manifest = readJson(path.join(pluginRoot, '.codex-plugin', 'plugin.json'))
const skillPath = path.join(pluginRoot, 'skills', 'backlink-autofill', 'SKILL.md')
const skill = fs.readFileSync(skillPath, 'utf8')
const registry = readJson(path.join(pluginRoot, 'references', 'project-registry.json'))
const quickIChing = fs.readFileSync(path.join(pluginRoot, 'references', 'projects', 'quick-iching.md'), 'utf8')

assert(manifest.name === 'backlink-autofill', 'plugin manifest name mismatch')
assert(manifest.skills === './skills/', 'plugin manifest must expose ./skills/')
assert(!manifest.mcpServers && !manifest.apps, 'MVP must remain skill-only: no MCP/app dependency')
assert(marketplace.plugins.some((p) => p.name === manifest.name && p.source?.path === './plugins/backlink-autofill'), 'marketplace entry missing or wrong')

assert(skill.startsWith('---\nname: backlink-autofill\n'), 'SKILL.md frontmatter name missing')
assert(skill.includes('description: Use when'), 'SKILL.md description must start with Use when')
assert(skill.includes('Project selection is explicit'), 'explicit project selection hard gate missing')
assert(skill.includes('Project isolation is strict'), 'project isolation hard gate missing')
assert(skill.includes('Browser action evidence is mandatory'), 'browser evidence hard gate missing')
assert(skill.includes('Browser control not available; no fields changed.'), 'explicit no-browser failure wording missing')
assert(skill.includes('Read the form back after filling'), 'post-fill browser verification missing')
assert(skill.includes('~/.backlink-autofill/submitter-profile.json'), 'private reusable submitter profile missing')
assert(skill.includes('Passwords are different'), 'password handling boundary missing')
assert(skill.includes('Final submit is human-only'), 'final-submit hard gate missing')
assert(skill.includes('Do not call or require a separate LLM API'), 'no-separate-API rule missing')
assert(skill.includes('Codex Chrome extension'), 'Chrome-session workflow missing')

assert(registry.projects.length >= 1, 'project registry is empty')
assert(registry.projects.some((p) => p.id === 'quick-iching'), 'Quick I Ching missing from registry')
assert(quickIChing.includes('Primary keyword: `i ching online`'), 'Quick I Ching primary keyword missing')
assert(quickIChing.includes('AI-powered'), 'Quick I Ching forbidden-claim boundary missing')
assert(quickIChing.includes('Preferred vetted queue tab: `严格免费外链`'), 'preferred vetted queue tab missing')
assert(!/docs\.google\.com\/spreadsheets\/d\//i.test(quickIChing), 'private Google Sheet URL must not be committed')

const pluginFiles = []
function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full)
    else pluginFiles.push(full)
  }
}
walk(pluginRoot)
const all = pluginFiles.map((file) => fs.readFileSync(file, 'utf8')).join('\n')
assert(!/openrouter\.ai/i.test(all), 'plugin must not depend on OpenRouter')
assert(!/OPENAI_API_KEY\s*=|process\.env\.OPENAI_API_KEY|"apiKey"\s*:/i.test(all), 'plugin must not require an OpenAI API key')

console.log('plugin validation passed')
