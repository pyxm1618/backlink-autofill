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
const browserRuntime = fs.readFileSync(path.join(pluginRoot, 'scripts', 'browser_runtime.py'), 'utf8')
const readme = fs.readFileSync(path.join(root, 'README.md'), 'utf8')
const registry = readJson(path.join(pluginRoot, 'references', 'project-registry.json'))
const quickIChing = fs.readFileSync(path.join(pluginRoot, 'references', 'projects', 'quick-iching.md'), 'utf8')

const appBindingPath = path.join(pluginRoot, '.app.json')
assert(fs.existsSync(appBindingPath), 'Google Drive app binding missing')
const appBinding = readJson(appBindingPath)
const sheetContractPath = path.join(pluginRoot, 'references', 'project-sheet-contract.md')
assert(fs.existsSync(sheetContractPath), 'project Sheet contract missing')
const sheetContract = fs.readFileSync(sheetContractPath, 'utf8')

assert(manifest.name === 'backlink-autofill', 'plugin manifest name mismatch')
assert(manifest.version === '0.2.1', 'plugin version must be 0.2.1 for local site credentials')
assert(manifest.skills === './skills/', 'plugin manifest must expose ./skills/')
assert(manifest.apps === './.app.json', 'plugin manifest must expose ./.app.json')
assert(!manifest.mcpServers, 'plugin must not define a separate MCP server')
assert(
  appBinding.apps?.['google-drive']?.id === 'connector_5f3c8c41a1e54ad7a76272c89e2554fa',
  'official Google Drive connector binding missing'
)
assert(manifest.interface?.capabilities?.includes('Write'), 'plugin must declare Write capability for Sheet state updates')
assert(marketplace.plugins.some((p) => p.name === manifest.name && p.source?.path === './plugins/backlink-autofill'), 'marketplace entry missing or wrong')

assert(sheetContract.includes('`外链总表`'), 'master Sheet tab name missing')
assert(sheetContract.includes('`项目外链管理`'), 'project Sheet tab name missing')
assert(sheetContract.includes('外链ID | 平台域名 | 提交入口 | 发现来源 | 发现时间 | 基础状态 | 基础排除原因 | 实测免费 | 实测需登录 | 实测登录方式 | 实测限制 | 实测链接属性 | 最后验证时间 | 平台备注'), 'master Sheet headers mismatch')
assert(sheetContract.includes('项目ID | 外链ID | 平台域名 | 状态 | 尝试次数 | 最近操作时间 | 目标URL | 结果链接 | 原因/备注 | 证据摘要'), 'project Sheet headers mismatch')
assert(sheetContract.includes('候选 / 已排除 / 失效'), 'master Chinese status options missing')
assert(sheetContract.includes('待提交 / 处理中 / 已提交 / 审核中 / 已排期 / 已上线 / 需人工 / 失败 / 不适用'), 'project Chinese status options missing')
assert(sheetContract.includes('每次最多读取 100 条'), 'per-run batch contract missing')
assert(sheetContract.includes('所有项目共用同一个 Spreadsheet'), 'single-workbook topology missing')
assert(!/docs\.google\.com\/spreadsheets\/d\//i.test(sheetContract), 'private Google Sheet URL must not be committed in schema contract')

assert(skill.startsWith('---\nname: backlink-autofill\n'), 'SKILL.md frontmatter name missing')
assert(skill.includes('description: Use when'), 'SKILL.md description must start with Use when')
assert(skill.includes('Project selection is explicit'), 'explicit project selection hard gate missing')
assert(skill.includes('Project isolation is strict'), 'project isolation hard gate missing')
assert(skill.includes('Browser action evidence is mandatory'), 'browser evidence hard gate missing')
assert(skill.includes('Read `~/.backlink-autofill/control-plane.json`'), 'shared Sheet control-plane resolution missing')
assert(skill.includes('Never use browser automation to read or edit Google Sheets'), 'structured Sheet-only rule missing')
assert(skill.includes('项目ID == selected project ID'), 'exact project row isolation predicate missing')
assert(skill.includes('状态 == 待提交'), 'pending queue predicate missing')
assert(skill.includes('at most 100 rows per invocation'), 'per-run 100 row limit missing')
assert(skill.includes('Headless is default'), 'headless default missing')
assert(skill.includes('Final submit may be automatic'), 'automatic final-submit policy missing')
assert(!skill.includes('Final submit is human-only'), 'obsolete human-only final-submit rule must be removed')
assert(browserRuntime.includes('stopped_for_human'), 'browser runtime human-blocker signal missing')
assert(skill.includes('Human handoff'), 'headed browser human-handoff policy missing')
assert(skill.includes('handoff-start'), 'headed browser handoff command missing')
assert(skill.includes('Re-read the exact row after every Sheet mutation'), 'Sheet write verification gate missing')
assert(skill.includes('Read the form back after filling'), 'post-fill browser verification missing')
assert(skill.includes('~/.backlink-autofill/submitter-profile.json'), 'private reusable submitter profile missing')
assert(skill.includes('~/.backlink-autofill/projects/<project-id>/'), 'per-project private data root missing')
assert(skill.includes('~/.backlink-autofill/credentials/'), 'shared site credential store missing')
assert(skill.includes('credential_fill'), 'credential_fill action policy missing')
assert(skill.includes('create_or_reuse'), 'new-account credential generation policy missing')
assert(skill.includes('existing_only'), 'existing-login credential policy missing')
assert(skill.includes('Never search sibling project directories'), 'sibling-project asset isolation rule missing')
assert(skill.includes('Passwords are different'), 'password handling boundary missing')
assert(!skill.includes('password/passcode fields are never filled by action JSON'), 'obsolete password-human-only rule remains')
assert(!skill.includes('do not create/store a plaintext password'), 'obsolete no-site-password-storage rule remains')
assert(skill.includes('Do not call or require a separate LLM API'), 'no-separate-API rule missing')

assert(readme.includes('One shared submitter profile'), 'README must document one shared submitter profile')
assert(readme.includes('projects/<project-id>/'), 'README must document per-project private directories')
assert(readme.includes('must never borrow assets from a sibling project'), 'README must document cross-project asset prohibition')
assert(readme.includes('外链总表') && readme.includes('项目外链管理'), 'README must document the two-tab shared Sheet control plane')
assert(readme.includes('Final submit may be automatic'), 'README must document automatic final submit')
assert(readme.includes('Headless is the default'), 'README must document headless default')
assert(!readme.includes('Never click the final Submit'), 'README contains obsolete manual-final-submit rule')
assert(!readme.includes('preferably the Codex Chrome extension'), 'README contains obsolete Chrome-extension execution guidance')
assert(readme.includes('python3 -m pip install -r plugins/backlink-autofill/scripts/requirements.txt'), 'README must document Playwright dependency installation')
assert(readme.includes('scripts/configure-control-plane.py'), 'README must document shared control-plane configuration')
assert(readme.includes('~/.backlink-autofill/credentials/'), 'README must document local site credential store')
assert(readme.includes('credential_fill'), 'README must document credential_fill behavior')

assert(registry.projects.length >= 1, 'project registry is empty')
assert(registry.projects.some((p) => p.id === 'quick-iching'), 'Quick I Ching missing from registry')
assert(quickIChing.includes('Primary keyword: `i ching online`'), 'Quick I Ching primary keyword missing')
assert(quickIChing.includes('AI-powered'), 'Quick I Ching forbidden-claim boundary missing')
assert(!quickIChing.includes('Preferred vetted queue tab'), 'obsolete per-project vetted queue tab must be removed')
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