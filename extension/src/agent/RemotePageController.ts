import type { BrowserState } from '@page-agent/page-controller'
import type { TabsController } from './TabsController'

function sendMessage(message: { type: 'PAGE_CONTROL'; action: string; targetTabId: number; payload?: any }): Promise<any> {
  return chrome.runtime.sendMessage(message).catch((error) => {
    console.error('[RemotePageController]', message.action, error)
    return null
  })
}

export class RemotePageController {
  tabsController: TabsController

  constructor(tabsController: TabsController) {
    this.tabsController = tabsController
  }

  get currentTabId(): number | null {
    return this.tabsController.currentTabId
  }

  private async getCurrentUrl(): Promise<string> {
    if (!this.currentTabId) return ''
    return (await this.tabsController.getTabInfo(this.currentTabId)).url || ''
  }

  private async getCurrentTitle(): Promise<string> {
    if (!this.currentTabId) return ''
    return (await this.tabsController.getTabInfo(this.currentTabId)).title || ''
  }

  async getLastUpdateTime(): Promise<number> {
    if (!this.currentTabId) throw new Error('tabsController not initialized.')
    return sendMessage({ type: 'PAGE_CONTROL', action: 'get_last_update_time', targetTabId: this.currentTabId })
  }

  async getBrowserState(): Promise<BrowserState> {
    const currentUrl = await this.getCurrentUrl()
    const currentTitle = await this.getCurrentTitle()
    const fallback: BrowserState = {
      url: currentUrl,
      title: currentTitle,
      header: '',
      content: '(empty page. either current page is not readable or content script not loaded yet.)',
      footer: '',
    }

    let browserState = fallback
    if (this.currentTabId && isContentScriptAllowed(currentUrl)) {
      browserState = (await sendMessage({ type: 'PAGE_CONTROL', action: 'get_browser_state', targetTabId: this.currentTabId })) ?? fallback
    }
    browserState.header = `${await this.tabsController.summarizeTabs()}\n\n${browserState.header || ''}`
    return browserState
  }

  async updateTree(): Promise<void> {
    if (!this.currentTabId || !isContentScriptAllowed(await this.getCurrentUrl())) return
    await sendMessage({ type: 'PAGE_CONTROL', action: 'update_tree', targetTabId: this.currentTabId })
  }

  async cleanUpHighlights(): Promise<void> {
    if (!this.currentTabId || !isContentScriptAllowed(await this.getCurrentUrl())) return
    await sendMessage({ type: 'PAGE_CONTROL', action: 'clean_up_highlights', targetTabId: this.currentTabId })
  }

  async clickElement(...args: any[]): Promise<DomActionReturn> {
    const result = await this.remoteCallDomAction('click_element', args)
    await new Promise((resolve) => setTimeout(resolve, 1000))
    return result
  }

  async inputText(...args: any[]): Promise<DomActionReturn> { return this.remoteCallDomAction('input_text', args) }
  async selectOption(...args: any[]): Promise<DomActionReturn> { return this.remoteCallDomAction('select_option', args) }
  async scroll(...args: any[]): Promise<DomActionReturn> { return this.remoteCallDomAction('scroll', args) }
  async scrollHorizontally(...args: any[]): Promise<DomActionReturn> { return this.remoteCallDomAction('scroll_horizontally', args) }
  async executeJavascript(...args: any[]): Promise<DomActionReturn> { return this.remoteCallDomAction('execute_javascript', args) }
  async showMask(): Promise<void> {}
  async hideMask(): Promise<void> {}
  dispose(): void {}

  private async remoteCallDomAction(action: string, payload: any[]): Promise<DomActionReturn> {
    if (!this.currentTabId) return { success: false, message: 'RemotePageController not initialized.' }
    if (!isContentScriptAllowed(await this.getCurrentUrl())) {
      return { success: false, message: 'Operation not allowed on this page. Open a normal web page first.' }
    }
    return sendMessage({ type: 'PAGE_CONTROL', action, targetTabId: this.currentTabId, payload })
  }
}

interface DomActionReturn { success: boolean; message: string }

export function isContentScriptAllowed(url: string | undefined): boolean {
  if (!url) return false
  const restricted = [/^chrome:\/\//, /^chrome-extension:\/\//, /^about:/, /^edge:\/\//, /^brave:\/\//, /^opera:\/\//, /^vivaldi:\/\//, /^file:\/\//, /^view-source:/, /^devtools:\/\//]
  return !restricted.some((pattern) => pattern.test(url))
}
