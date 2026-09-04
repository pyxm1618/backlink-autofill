import type { AppState, LLMSettings, ProductProfile } from './types'

const DEFAULT_LLM: LLMSettings = {
  baseUrl: 'https://openrouter.ai/api/v1',
  apiKey: '',
  model: '',
}

const QUICK_ICHING_SEED: ProductProfile = {
  id: 'quick-iching',
  name: 'Quick I Ching',
  url: 'https://quickiching.com/',
  primaryKeyword: 'i ching online',
  secondaryKeywords: [
    'i ching',
    'i ching reading',
    'three coin i ching',
    'yarrow stalk',
    'mei hua yi shu',
    'hexagram',
    'changing lines',
  ],
  listingTitle: 'I Ching Online — Free Hexagram Reading | Quick I Ching',
  tagline: 'Free I Ching online readings with traditional casting methods',
  descriptions: {
    micro: 'Free I Ching online casting and hexagram readings with traditional methods.',
    short: 'Use the I Ching online with Three-Coin, Yarrow Stalk, Mei Hua Yi Shu, or Manual Cast and get a grounded hexagram interpretation.',
    medium: 'Quick I Ching is a free online I Ching casting and hexagram reading tool. Cast with Three-Coin, Yarrow Stalk, Mei Hua Yi Shu, or Manual Cast, then see the primary hexagram, changing lines, relating hexagram, and a grounded interpretation.',
    long: 'Quick I Ching is a free online I Ching casting and hexagram reading tool built around traditional casting methods. It supports Three-Coin, Yarrow Stalk, Mei Hua Yi Shu, and Manual Cast. Results show the primary hexagram, changing lines, and relating hexagram together with a grounded interpretation, so users can understand the structure of a reading without reducing the I Ching to a generic fortune-telling experience.',
  },
  approvedTags: [
    'i ching',
    'i ching online',
    'i ching reading',
    'three coin i ching',
    'yarrow stalk',
    'mei hua yi shu',
    'hexagram',
    'changing lines',
  ],
  categoryCandidates: ['I Ching', 'Divination', 'Spirituality', 'Reference'],
  factualClaims: [
    'Free online I Ching casting and hexagram reading tool',
    'Supports Three-Coin casting',
    'Supports Yarrow Stalk casting',
    'Supports Mei Hua Yi Shu',
    'Supports Manual Cast',
    'Shows primary hexagram, changing lines, and relating hexagram',
    'Provides grounded interpretation',
  ],
  prohibitedClaims: [
    'AI-powered',
    'AI fortune teller',
    'medical, legal, or investment advice',
  ],
  founderName: '',
  founderEmail: '',
  socialLinks: {},
  screenshots: [],
  sheet: {
    spreadsheetId: '1gAia71b4ts_vghzLZaFvXkEkFbgS3NJv9uVEPmeyY68',
    sheetName: '严格免费外链',
  },
  createdAt: Date.now(),
  updatedAt: Date.now(),
}

export function resolveActiveProject(projects: ProductProfile[], activeProjectId: string | null): ProductProfile | null {
  if (!activeProjectId) return null
  return projects.find((project) => project.id === activeProjectId) ?? null
}

export async function getAppState(): Promise<AppState> {
  const stored = await chrome.storage.local.get(['projects', 'activeProjectId', 'llm'])
  const projects = Array.isArray(stored.projects) && stored.projects.length ? stored.projects as ProductProfile[] : [QUICK_ICHING_SEED]
  return {
    projects,
    activeProjectId: typeof stored.activeProjectId === 'string' ? stored.activeProjectId : null,
    llm: { ...DEFAULT_LLM, ...(stored.llm as Partial<LLMSettings> | undefined) },
  }
}

export async function saveProject(project: ProductProfile): Promise<void> {
  const state = await getAppState()
  const now = Date.now()
  const next = state.projects.some((item) => item.id === project.id)
    ? state.projects.map((item) => item.id === project.id ? { ...project, updatedAt: now } : item)
    : [...state.projects, { ...project, createdAt: now, updatedAt: now }]
  await chrome.storage.local.set({ projects: next })
}

export async function setActiveProjectId(activeProjectId: string | null): Promise<void> {
  await chrome.storage.local.set({ activeProjectId })
}

export async function saveLLMSettings(llm: LLMSettings): Promise<void> {
  await chrome.storage.local.set({ llm })
}

export async function getLLMSettings(): Promise<LLMSettings> {
  return (await getAppState()).llm
}
