import { PageController } from '@page-agent/page-controller'

export function initPageController() {
  let pageController: PageController | null = null
  let intervalId: number | null = null

  const myTabIdPromise = chrome.runtime.sendMessage({ type: 'PAGE_CONTROL', action: 'get_my_tab_id' })
    .then((response) => (response as { tabId: number | null }).tabId)
    .catch(() => null)

  const getController = () => {
    if (!pageController) pageController = new PageController({ enableMask: false, viewportExpansion: 400 })
    return pageController
  }

  intervalId = window.setInterval(async () => {
    try {
      const { agentHeartbeat, isAgentRunning, currentTabId } = await chrome.storage.local.get(['agentHeartbeat', 'isAgentRunning', 'currentTabId'])
      const agentInTouch = typeof agentHeartbeat === 'number' && Date.now() - agentHeartbeat < 2000
      const shouldShowMask = isAgentRunning && agentInTouch && currentTabId === (await myTabIdPromise)
      if (shouldShowMask) {
        const pc = getController()
        pc.initMask()
        await pc.showMask()
      } else if (pageController) {
        pageController.hideMask()
        pageController.cleanUpHighlights()
      }
      if (!isAgentRunning && agentInTouch && pageController) {
        pageController.dispose()
        pageController = null
      }
    } catch (error) {
      if (String(error).includes('Extension context invalidated') && intervalId) window.clearInterval(intervalId)
    }
  }, 500)

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse): true | undefined => {
    if (message.type !== 'PAGE_CONTROL') return
    const methodName = getMethodName(message.action)
    const pc = getController() as any
    const supported = new Set([
      'get_last_update_time', 'get_browser_state', 'update_tree', 'clean_up_highlights',
      'click_element', 'input_text', 'select_option', 'scroll', 'scroll_horizontally', 'execute_javascript',
    ])
    if (!supported.has(message.action)) {
      sendResponse({ success: false, error: `Unknown PAGE_CONTROL action: ${message.action}` })
      return
    }
    pc[methodName](...(message.payload || []))
      .then((result: any) => sendResponse(result))
      .catch((error: any) => sendResponse({ success: false, error: error instanceof Error ? error.message : String(error) }))
    return true
  })
}

function getMethodName(action: string): string {
  const map: Record<string, string> = {
    get_last_update_time: 'getLastUpdateTime',
    get_browser_state: 'getBrowserState',
    update_tree: 'updateTree',
    clean_up_highlights: 'cleanUpHighlights',
    click_element: 'clickElement',
    input_text: 'inputText',
    select_option: 'selectOption',
    scroll: 'scroll',
    scroll_horizontally: 'scrollHorizontally',
    execute_javascript: 'executeJavascript',
  }
  return map[action] ?? action
}
