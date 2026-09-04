import { isContentScriptAllowed } from './RemotePageController'

function sendMessage(message: { type: 'TAB_CONTROL'; action: TabAction; payload?: any }): Promise<any> {
  return chrome.runtime.sendMessage(message).catch((error) => {
    console.error('[TabsController]', message.action, error)
    return null
  })
}

export class TabsController extends EventTarget {
  currentTabId: number | null = null
  private tabs: TabMeta[] = []
  private initialTabId: number | null = null

  async init(includeInitialTab = true) {
    this.tabs = []
    this.currentTabId = null
    this.initialTabId = null
    const result = await sendMessage({ type: 'TAB_CONTROL', action: 'get_active_tab' })
    this.initialTabId = result?.tabId ?? null
    if (!this.initialTabId) throw new Error('Failed to get initial tab ID')

    if (includeInitialTab) {
      const info = await sendMessage({ type: 'TAB_CONTROL', action: 'get_tab_info', payload: { tabId: this.initialTabId } })
      if (isContentScriptAllowed(info?.url)) {
        this.currentTabId = this.initialTabId
        this.tabs.push({ id: this.initialTabId, isInitial: true, url: info.url, title: info.title, status: info.status })
      }
    }
    await this.updateCurrentTabId(this.currentTabId)

    const handler = (message: any) => {
      if (message.type !== 'TAB_CHANGE') return
      if (message.action === 'removed') {
        const tabId = message.payload.tabId as number
        this.tabs = this.tabs.filter((t) => t.id !== tabId)
        if (this.currentTabId === tabId) void this.updateCurrentTabId(this.tabs.at(-1)?.id ?? null)
      } else if (message.action === 'updated') {
        const tabId = message.payload.tabId as number
        const meta = this.tabs.find((t) => t.id === tabId)
        if (meta) Object.assign(meta, { url: message.payload.tab.url, title: message.payload.tab.title, status: message.payload.tab.status })
      }
    }
    chrome.runtime.onMessage.addListener(handler)
    this.addEventListener('dispose', () => chrome.runtime.onMessage.removeListener(handler))
  }

  async openNewTab(url: string): Promise<string> {
    const result = await sendMessage({ type: 'TAB_CONTROL', action: 'open_new_tab', payload: { url } })
    if (!result?.success) throw new Error(`Failed to open new tab: ${result?.error ?? 'unknown error'}`)
    const tabId = result.tabId as number
    this.tabs.push({ id: tabId, isInitial: false })
    await this.switchToTab(tabId)
    await this.waitUntilTabLoaded(tabId)
    return `Opened tab ${tabId}: ${url}`
  }

  async switchToTab(tabId: number): Promise<string> {
    if (!this.tabs.find((t) => t.id === tabId)) throw new Error(`Tab ID ${tabId} not found`)
    await this.updateCurrentTabId(tabId)
    return `Switched to tab ${tabId}`
  }

  async closeTab(tabId: number): Promise<string> {
    const target = this.tabs.find((t) => t.id === tabId)
    if (!target) throw new Error(`Tab ID ${tabId} not found`)
    if (target.isInitial) throw new Error(`Cannot close initial tab ${tabId}`)
    const result = await sendMessage({ type: 'TAB_CONTROL', action: 'close_tab', payload: { tabId } })
    if (!result?.success) throw new Error(result?.error ?? 'Failed to close tab')
    this.tabs = this.tabs.filter((t) => t.id !== tabId)
    if (this.currentTabId === tabId) await this.updateCurrentTabId(this.tabs.at(-1)?.id ?? null)
    return `Closed tab ${tabId}`
  }

  async updateCurrentTabId(tabId: number | null) {
    this.currentTabId = tabId
    await chrome.storage.local.set({ currentTabId: tabId })
  }

  async getTabInfo(tabId: number): Promise<{ title: string; url: string }> {
    const cached = this.tabs.find((t) => t.id === tabId)
    if (cached?.url && cached.title) return { url: cached.url, title: cached.title }
    const result = await sendMessage({ type: 'TAB_CONTROL', action: 'get_tab_info', payload: { tabId } })
    if (cached) Object.assign(cached, { url: result.url, title: result.title, status: result.status })
    return result
  }

  async summarizeTabs(): Promise<string> {
    const lines = ['| Tab ID | URL | Title | Current |', '|---|---|---|---|']
    for (const tab of this.tabs) {
      const info = await this.getTabInfo(tab.id)
      lines.push(`| ${tab.id} | ${info.url} | ${info.title} | ${this.currentTabId === tab.id ? 'yes' : ''} |`)
    }
    return lines.join('\n')
  }

  async waitUntilTabLoaded(tabId: number): Promise<void> {
    const tab = this.tabs.find((t) => t.id === tabId)
    if (!tab) throw new Error(`Tab ID ${tabId} not found`)
    if (tab.status === 'complete') return
    await waitUntil(() => tab.status === 'complete', 10_000)
  }

  dispose() { this.dispatchEvent(new Event('dispose')) }
}

export type TabAction = 'get_active_tab' | 'get_tab_info' | 'open_new_tab' | 'close_tab'
interface TabMeta { id: number; isInitial: boolean; url?: string; title?: string; status?: 'loading' | 'unloaded' | 'complete' }

export async function waitUntil(check: () => boolean | Promise<boolean>, timeoutMs = 60_000): Promise<boolean> {
  if (await check()) return true
  return new Promise((resolve) => {
    const start = Date.now()
    const poll = async () => {
      if (await check()) return resolve(true)
      if (Date.now() - start > timeoutMs) return resolve(false)
      setTimeout(poll, 100)
    }
    setTimeout(poll, 100)
  })
}
