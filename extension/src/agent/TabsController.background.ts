import type { TabAction } from './TabsController'

export function handleTabControlMessage(
  message: { type: 'TAB_CONTROL'; action: TabAction; payload?: any },
  _sender: chrome.runtime.MessageSender,
  sendResponse: (response: unknown) => void,
): true | undefined {
  const { action, payload } = message
  if (action === 'get_active_tab') {
    chrome.tabs.query({ active: true, currentWindow: true })
      .then((tabs) => sendResponse({ success: true, tabId: tabs[0]?.id ?? null }))
      .catch((error) => sendResponse({ error: String(error) }))
    return true
  }
  if (action === 'get_tab_info') {
    chrome.tabs.get(payload.tabId).then(sendResponse).catch((error) => sendResponse({ error: String(error) }))
    return true
  }
  if (action === 'open_new_tab') {
    chrome.tabs.create({ url: payload.url, active: true })
      .then((tab) => sendResponse({ success: true, tabId: tab.id }))
      .catch((error) => sendResponse({ error: String(error) }))
    return true
  }
  if (action === 'close_tab') {
    chrome.tabs.remove(payload.tabId)
      .then(() => sendResponse({ success: true }))
      .catch((error) => sendResponse({ error: String(error) }))
    return true
  }
  sendResponse({ error: `Unknown action: ${action}` })
}

export function setupTabChangeEvents() {
  chrome.tabs.onRemoved.addListener((tabId, removeInfo) => {
    chrome.runtime.sendMessage({ type: 'TAB_CHANGE', action: 'removed', payload: { tabId, removeInfo } }).catch(() => {})
  })
  chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    chrome.runtime.sendMessage({ type: 'TAB_CHANGE', action: 'updated', payload: { tabId, changeInfo, tab } }).catch(() => {})
  })
}
