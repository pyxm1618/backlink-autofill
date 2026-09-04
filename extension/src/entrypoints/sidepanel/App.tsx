import { useEffect, useMemo, useState } from 'react'
import { ProjectEditor } from '@/components/ProjectEditor'
import { runAutofill } from '@/agent/SubmitAgent'
import { getAppState, resolveActiveProject, saveLLMSettings, saveProject, setActiveProjectId } from '@/lib/storage'
import { loadSheetTargets } from '@/lib/sheets'
import type { AppState, BacklinkTarget, ProductProfile } from '@/lib/types'

function blankProject(): ProductProfile {
  const now = Date.now()
  return {
    id: crypto.randomUUID(),
    name: '',
    url: '',
    primaryKeyword: '',
    secondaryKeywords: [],
    listingTitle: '',
    tagline: '',
    descriptions: { micro: '', short: '', medium: '', long: '' },
    approvedTags: [],
    categoryCandidates: [],
    factualClaims: [],
    prohibitedClaims: [],
    founderName: '',
    founderEmail: '',
    socialLinks: {},
    screenshots: [],
    sheet: { spreadsheetId: '', sheetName: '' },
    createdAt: now,
    updatedAt: now,
  }
}

export default function App() {
  const [state, setState] = useState<AppState | null>(null)
  const [editing, setEditing] = useState<ProductProfile | null>(null)
  const [targets, setTargets] = useState<BacklinkTarget[]>([])
  const [loadingTargets, setLoadingTargets] = useState(false)
  const [running, setRunning] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function refresh() { setState(await getAppState()) }
  useEffect(() => { void refresh() }, [])

  const activeProject = useMemo(() => state ? resolveActiveProject(state.projects, state.activeProjectId) : null, [state])

  if (!state) return <div className="app">Loading…</div>

  if (editing) {
    return <div className="app"><ProjectEditor project={editing} onSave={async (project) => {
      await saveProject(project)
      setEditing(null)
      await refresh()
    }} onCancel={() => setEditing(null)} /></div>
  }

  async function chooseProject(id: string) {
    await setActiveProjectId(id || null)
    setTargets([])
    setMessage('')
    setError('')
    await refresh()
  }

  async function loadTargets() {
    if (!activeProject) return
    setLoadingTargets(true); setError(''); setMessage('')
    try {
      const rows = await loadSheetTargets(activeProject)
      setTargets(rows)
      setMessage(`Loaded ${rows.length} target(s) from ${activeProject.sheet?.sheetName}.`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setLoadingTargets(false) }
  }

  async function execute(target?: BacklinkTarget, currentTab = false) {
    if (!activeProject || !state) {
      setError('Select a project first. The agent will not guess or fall back to another project.')
      return
    }
    setRunning(true); setError(''); setMessage('')
    try {
      const result = await runAutofill({
        project: activeProject,
        llm: state.llm,
        siteName: target?.name ?? 'current site',
        targetUrl: target?.submitUrl,
        currentTab,
      })
      const fallback = result.success
        ? 'Form filling completed. Review the page and submit manually.'
        : 'Agent stopped before completion. Resolve the blocker manually, then use Fill current tab.'
      setMessage(result.data || fallback)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setRunning(false) }
  }

  return <div className="app">
    <div className="row" style={{ justifyContent: 'space-between' }}>
      <h1>Backlink Autofill</h1>
      <button className="secondary" onClick={() => setEditing(blankProject())}>New project</button>
    </div>

    <div className="card stack">
      <h2>1. Select project</h2>
      <select value={state.activeProjectId ?? ''} onChange={(e) => void chooseProject(e.target.value)}>
        <option value="">— Select explicitly —</option>
        {state.projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
      </select>
      {!activeProject && <div className="warning">No project selected. Autofill is blocked until you explicitly choose one.</div>}
      {activeProject && <div className="row">
        <div style={{ flex: 1 }}>
          <strong>{activeProject.name}</strong>
          <div className="small">Primary keyword: {activeProject.primaryKeyword}</div>
        </div>
        <button className="secondary" onClick={() => setEditing(activeProject)}>Edit data</button>
      </div>}
    </div>

    <div className="card stack">
      <h2>2. LLM</h2>
      <label>Base URL<input value={state.llm.baseUrl} onChange={(e) => setState({ ...state, llm: { ...state.llm, baseUrl: e.target.value } })} /></label>
      <label>Model<input placeholder="model name" value={state.llm.model} onChange={(e) => setState({ ...state, llm: { ...state.llm, model: e.target.value } })} /></label>
      <label>API key<input type="password" value={state.llm.apiKey} onChange={(e) => setState({ ...state, llm: { ...state.llm, apiKey: e.target.value } })} /></label>
      <button className="secondary" onClick={async () => { await saveLLMSettings(state.llm); setMessage('LLM settings saved.') }}>Save LLM settings</button>
    </div>

    <div className="card stack">
      <h2>3. Backlink targets</h2>
      <div className="small">Uses the selected project's Google Sheet. The first MVP tries the private Sheet through this Chrome profile's existing Google session.</div>
      <div className="row">
        <button disabled={!activeProject || loadingTargets} onClick={() => void loadTargets()}>{loadingTargets ? 'Loading…' : 'Load from Sheet'}</button>
        <button className="secondary" disabled={!activeProject || running} onClick={() => void execute(undefined, true)}>Fill current tab</button>
      </div>
      {targets.slice(0, 100).map((target) => <div className="target" key={`${target.name}-${target.submitUrl}`}>
        <div>
          <strong>{target.name}</strong>
          <div className="small">{target.submitUrl}</div>
          <div>{target.priority && <span className="badge">{target.priority}</span>}{target.type && <span className="badge">{target.type}</span>}{target.confidence && <span className="badge">{target.confidence}</span>}</div>
        </div>
        <button disabled={running} onClick={() => void execute(target, false)}>Open & fill</button>
      </div>)}
    </div>

    <div className="warning"><strong>Human boundary:</strong> CAPTCHA / 2FA / security checks are manual. The agent must stop before the final Submit / Publish / Launch action.</div>
    {error && <div className="error">{error}</div>}
    {message && <div className="success">{message}</div>}
    {running && <div className="small">Agent is working in the browser…</div>}
  </div>
}
