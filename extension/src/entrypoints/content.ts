import { initPageController } from '@/agent/RemotePageController.content'

export default defineContentScript({
  matches: ['<all_urls>'],
  runAt: 'document_end',
  main() {
    initPageController()
  },
})
