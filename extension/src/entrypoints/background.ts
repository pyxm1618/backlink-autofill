import { handlePageControlMessage } from '@/agent/RemotePageController.background'
import { handleTabControlMessage, setupTabChangeEvents } from '@/agent/TabsController.background'

export default defineBackground(() => {
  setupTabChangeEvents()
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {})

  chrome.runtime.onMessage.addListener((message, sender, sendResponse): true | undefined => {
    if (message.type === 'TAB_CONTROL') return handleTabControlMessage(message, sender, sendResponse)
    if (message.type === 'PAGE_CONTROL') return handlePageControlMessage(message, sender, sendResponse)
    sendResponse({ error: `Unknown message type: ${message.type}` })
  })
})
