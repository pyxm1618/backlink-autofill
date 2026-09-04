import { type AgentConfig, PageAgentCore, type ExecutionResult } from '@page-agent/core'
import type { LLMSettings, ProductProfile } from '@/lib/types'
import { buildProjectContext } from '@/lib/project-context'
import { RemotePageController } from './RemotePageController'
import { TabsController } from './TabsController'
import { createTabTools } from './tabTools'
import SUBMIT_PROMPT from './submit-prompt.md?raw'

export interface SubmitAgentConfig extends AgentConfig {
  project: ProductProfile
  includeInitialTab?: boolean
}

export class SubmitAgent extends PageAgentCore {
  readonly project: ProductProfile

  constructor(config: SubmitAgentConfig) {
    const tabsController = new TabsController()
    const pageController = new RemotePageController(tabsController)
    let heartbeat: number | null = null

    super({
      ...config,
      pageController: pageController as any,
      customTools: createTabTools(tabsController) as any,
      customSystemPrompt: SUBMIT_PROMPT,
      maxSteps: config.maxSteps ?? 50,
      onBeforeTask: async () => {
        await tabsController.init(config.includeInitialTab ?? false)
        heartbeat = window.setInterval(() => chrome.storage.local.set({ agentHeartbeat: Date.now() }), 1000)
        await chrome.storage.local.set({ isAgentRunning: true })
      },
      onAfterTask: async () => {
        if (heartbeat) window.clearInterval(heartbeat)
        heartbeat = null
        await chrome.storage.local.set({ isAgentRunning: false })
      },
      onBeforeStep: async () => {
        if (tabsController.currentTabId) await tabsController.waitUntilTabLoaded(tabsController.currentTabId)
      },
      onDispose: () => {
        if (heartbeat) window.clearInterval(heartbeat)
        chrome.storage.local.set({ isAgentRunning: false }).catch(() => {})
        tabsController.dispose()
      },
    })

    this.project = config.project
  }
}

export interface RunAutofillInput {
  project: ProductProfile
  llm: LLMSettings
  siteName: string
  targetUrl?: string
  currentTab?: boolean
}

export async function runAutofill(input: RunAutofillInput): Promise<ExecutionResult> {
  if (!input.project?.id) throw new Error('An explicit active project is required.')
  if (!input.llm.baseUrl || !input.llm.model) throw new Error('Configure an LLM Base URL and model first.')

  const agent = new SubmitAgent({
    baseURL: input.llm.baseUrl.replace(/\/+$/, ''),
    apiKey: input.llm.apiKey || undefined,
    model: input.llm.model,
    project: input.project,
    includeInitialTab: input.currentTab ?? false,
    language: 'en-US',
  })

  const task = [
    `Fill the backlink/listing submission for the explicitly selected project "${input.project.name}" on ${input.siteName}.`,
    input.currentTab
      ? 'Work on the current browser tab.'
      : `Open the target submission URL first: ${input.targetUrl ?? ''}`,
    '',
    'Execution requirements:',
    '- Inspect the whole form before deciding field values.',
    '- Use the authoritative project data below as the only source of product facts.',
    '- Use exact canonical copy when it fits; adapt only for the current field constraints.',
    '- You may try normal Google/GitHub social login using the browser profile existing session.',
    '- Stop for human takeover on CAPTCHA, 2FA, slider, Cloudflare, passkey, phone confirmation, or other security verification.',
    '- Do NOT click the final Submit/Publish/Launch/Create Listing/Send for Review action.',
    '',
    buildProjectContext(input.project),
  ].join('\n')

  try {
    return await agent.execute(task)
  } finally {
    agent.dispose()
  }
}
