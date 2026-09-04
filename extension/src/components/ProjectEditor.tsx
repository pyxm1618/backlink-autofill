import { useMemo, useState } from 'react'
import type { ProductProfile } from '@/lib/types'

function joinList(values: string[]) { return values.join('\n') }
function splitList(value: string) { return value.split(/[\n,]+/).map((item) => item.trim()).filter(Boolean) }

export function ProjectEditor({ project, onSave, onCancel }: {
  project: ProductProfile
  onSave: (project: ProductProfile) => Promise<void>
  onCancel: () => void
}) {
  const [draft, setDraft] = useState<ProductProfile>(() => structuredClone(project))
  const [saving, setSaving] = useState(false)
  const isValid = useMemo(() => Boolean(draft.name.trim() && /^https?:\/\//i.test(draft.url) && draft.primaryKeyword.trim()), [draft])

  const set = <K extends keyof ProductProfile>(key: K, value: ProductProfile[K]) => setDraft((current) => ({ ...current, [key]: value }))
  const setDescription = (key: keyof ProductProfile['descriptions'], value: string) => setDraft((current) => ({ ...current, descriptions: { ...current.descriptions, [key]: value } }))

  async function save() {
    if (!isValid) return
    setSaving(true)
    try { await onSave(draft) } finally { setSaving(false) }
  }

  return <div className="stack card">
    <h2>Project submission data</h2>
    <div className="small">These reviewed values are the source of truth. The agent may adapt them to a site's field constraints, but must not invent product facts.</div>

    <label>Project name<input value={draft.name} onChange={(e) => set('name', e.target.value)} /></label>
    <label>Canonical URL<input value={draft.url} onChange={(e) => set('url', e.target.value)} /></label>
    <label>Primary keyword<input value={draft.primaryKeyword} onChange={(e) => set('primaryKeyword', e.target.value)} /></label>
    <label>Secondary keywords<textarea value={joinList(draft.secondaryKeywords)} onChange={(e) => set('secondaryKeywords', splitList(e.target.value))} /></label>
    <label>Approved listing title<input value={draft.listingTitle} onChange={(e) => set('listingTitle', e.target.value)} /></label>
    <label>Approved tagline<textarea value={draft.tagline} onChange={(e) => set('tagline', e.target.value)} /></label>

    <label>Micro description<textarea value={draft.descriptions.micro} onChange={(e) => setDescription('micro', e.target.value)} /></label>
    <label>Short description<textarea value={draft.descriptions.short} onChange={(e) => setDescription('short', e.target.value)} /></label>
    <label>Medium description<textarea value={draft.descriptions.medium} onChange={(e) => setDescription('medium', e.target.value)} /></label>
    <label>Long description<textarea rows={7} value={draft.descriptions.long} onChange={(e) => setDescription('long', e.target.value)} /></label>

    <label>Approved tags<textarea value={joinList(draft.approvedTags)} onChange={(e) => set('approvedTags', splitList(e.target.value))} /></label>
    <label>Category candidates<textarea value={joinList(draft.categoryCandidates)} onChange={(e) => set('categoryCandidates', splitList(e.target.value))} /></label>
    <label>Factual claims<textarea rows={6} value={joinList(draft.factualClaims)} onChange={(e) => set('factualClaims', splitList(e.target.value))} /></label>
    <label>Prohibited claims<textarea value={joinList(draft.prohibitedClaims)} onChange={(e) => set('prohibitedClaims', splitList(e.target.value))} /></label>

    <label>Founder / submitter name<input value={draft.founderName} onChange={(e) => set('founderName', e.target.value)} /></label>
    <label>Contact email<input type="email" value={draft.founderEmail} onChange={(e) => set('founderEmail', e.target.value)} /></label>
    <label>Social links (one per line: platform=url)<textarea value={Object.entries(draft.socialLinks).map(([key, value]) => `${key}=${value}`).join('\n')} onChange={(e) => {
      const links: Record<string, string> = {}
      for (const line of e.target.value.split('\n')) {
        const [key, ...rest] = line.split('=')
        if (key?.trim() && rest.join('=').trim()) links[key.trim()] = rest.join('=').trim()
      }
      set('socialLinks', links)
    }} /></label>

    <h2>Backlink Sheet</h2>
    <label>Spreadsheet ID<input value={draft.sheet?.spreadsheetId ?? ''} onChange={(e) => set('sheet', { spreadsheetId: e.target.value, sheetName: draft.sheet?.sheetName ?? '' })} /></label>
    <label>Sheet tab name<input value={draft.sheet?.sheetName ?? ''} onChange={(e) => set('sheet', { spreadsheetId: draft.sheet?.spreadsheetId ?? '', sheetName: e.target.value })} /></label>

    <div className="row">
      <button disabled={!isValid || saving} onClick={save}>{saving ? 'Saving…' : 'Save project'}</button>
      <button className="secondary" onClick={onCancel}>Cancel</button>
    </div>
  </div>
}
