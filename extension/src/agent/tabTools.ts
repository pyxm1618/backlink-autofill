import * as z from 'zod/v4'
import type { TabsController } from './TabsController'

interface TabTool {
  description: string
  inputSchema: z.ZodType
  execute: (input: unknown) => Promise<string>
}

export function createTabTools(tabsController: TabsController): Record<string, TabTool> {
  return {
    open_new_tab: {
      description: 'Open a new browser tab. The new tab becomes the current tab for later page operations.',
      inputSchema: z.object({ url: z.string() }),
      execute: async (input) => tabsController.openNewTab((input as { url: string }).url),
    },
    switch_to_tab: {
      description: 'Switch to a tracked browser tab by ID.',
      inputSchema: z.object({ tab_id: z.number().int() }),
      execute: async (input) => tabsController.switchToTab((input as { tab_id: number }).tab_id),
    },
    close_tab: {
      description: 'Close a tracked non-initial tab by ID.',
      inputSchema: z.object({ tab_id: z.number().int() }),
      execute: async (input) => tabsController.closeTab((input as { tab_id: number }).tab_id),
    },
  }
}
