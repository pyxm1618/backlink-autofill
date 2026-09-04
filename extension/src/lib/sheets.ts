import type { BacklinkTarget, ProductProfile } from './types'

const HEADER_ALIASES = {
  name: ['外链来源域名', '域名', '项目域名', 'name', 'domain'],
  submitUrl: ['提交/入口地址', '提交/发布入口', '提交入口', 'submit_url', 'url'],
  priority: ['优先级', 'priority'],
  type: ['机会类型', '获取方式', 'type'],
  confidence: ['置信度', 'confidence'],
  notes: ['核验说明', '条件/备注', '备注', 'notes'],
} as const

function findIndex(headers: string[], aliases: readonly string[]): number {
  const normalized = headers.map((value) => value.trim().toLowerCase())
  return aliases.reduce((found, alias) => {
    if (found >= 0) return found
    return normalized.indexOf(alias.trim().toLowerCase())
  }, -1)
}

export function parseSheetTargets(values: string[][]): BacklinkTarget[] {
  if (values.length < 2) return []
  const headers = values[0].map((value) => String(value ?? '').trim())
  const indexes = {
    name: findIndex(headers, HEADER_ALIASES.name),
    submitUrl: findIndex(headers, HEADER_ALIASES.submitUrl),
    priority: findIndex(headers, HEADER_ALIASES.priority),
    type: findIndex(headers, HEADER_ALIASES.type),
    confidence: findIndex(headers, HEADER_ALIASES.confidence),
    notes: findIndex(headers, HEADER_ALIASES.notes),
  }

  if (indexes.name < 0 || indexes.submitUrl < 0) {
    throw new Error(`Sheet must contain a domain/name column and a submit URL column. Found: ${headers.join(', ')}`)
  }

  const result: BacklinkTarget[] = []
  for (const row of values.slice(1)) {
    const name = String(row[indexes.name] ?? '').trim()
    const submitUrl = String(row[indexes.submitUrl] ?? '').trim()
    if (!name || !/^https?:\/\//i.test(submitUrl)) continue
    result.push({
      name,
      submitUrl,
      ...(indexes.priority >= 0 && row[indexes.priority] ? { priority: String(row[indexes.priority]).trim() } : {}),
      ...(indexes.type >= 0 && row[indexes.type] ? { type: String(row[indexes.type]).trim() } : {}),
      ...(indexes.confidence >= 0 && row[indexes.confidence] ? { confidence: String(row[indexes.confidence]).trim() } : {}),
      ...(indexes.notes >= 0 && row[indexes.notes] ? { notes: String(row[indexes.notes]).trim() } : {}),
    })
  }
  return result
}

export function parseGvizHtml(html: string): string[][] {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const rows = Array.from(doc.querySelectorAll('table tr')).map((row) =>
    Array.from(row.querySelectorAll('th,td')).map((cell) => (cell.textContent ?? '').replace(/\s+/g, ' ').trim()),
  ).filter((row) => row.length > 0)
  return rows
}

export async function loadSheetTargets(project: ProductProfile): Promise<BacklinkTarget[]> {
  if (!project.sheet?.spreadsheetId || !project.sheet.sheetName) return []
  const { spreadsheetId, sheetName } = project.sheet
  const url = `https://docs.google.com/spreadsheets/d/${encodeURIComponent(spreadsheetId)}/gviz/tq?tqx=out:html&sheet=${encodeURIComponent(sheetName)}`
  const response = await fetch(url, { credentials: 'include' })
  if (!response.ok) throw new Error(`Google Sheet request failed: HTTP ${response.status}`)
  const html = await response.text()
  const values = parseGvizHtml(html)
  if (values.length < 2) {
    throw new Error('Could not read Sheet rows. Open the Sheet in this Chrome profile and confirm the Google account has access, then retry.')
  }
  return parseSheetTargets(values)
}
