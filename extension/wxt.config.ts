import { defineConfig } from 'wxt'

export default defineConfig({
  srcDir: 'src',
  modules: ['@wxt-dev/module-react'],
  manifest: {
    name: 'Backlink Autofill',
    description: 'Project-isolated, AI-assisted backlink form filling with human final submission.',
    permissions: ['tabs', 'tabGroups', 'sidePanel', 'storage', 'activeTab'],
    host_permissions: ['<all_urls>', 'https://docs.google.com/*'],
    action: { default_title: 'Backlink Autofill' },
    side_panel: { default_path: 'sidepanel/index.html' },
  },
})
