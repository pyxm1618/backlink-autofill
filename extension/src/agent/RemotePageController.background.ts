/** Upstream bridge: proxy Page Agent requests from extension UI to the active content script. */
export function handlePageControlMessage(
  message: { type: 'PAGE_CONTROL'; action: string; payload: any; targetTabId: number },
  sender: chrome.runtime.MessageSender,
  sendResponse: (response: unknown) => void,
): true | undefined {
  const { action, payload, targetTabId } = message
  if (action === 'get_my_tab_id') {
    sendResponse({ tabId: sender.tab?.id || null })
    return
  }

  chrome.tabs.sendMessage(targetTabId, { type: 'PAGE_CONTROL', action, payload })
    .then(sendResponse)
    .catch((error) => sendResponse({ success: false, error: error instanceof Error ? error.message : String(error) }))
  return true
}
