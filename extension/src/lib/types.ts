export interface ProjectDescriptions {
  micro: string
  short: string
  medium: string
  long: string
}

export interface SheetConfig {
  spreadsheetId: string
  sheetName: string
}

export interface ProductProfile {
  id: string
  name: string
  url: string
  primaryKeyword: string
  secondaryKeywords: string[]
  listingTitle: string
  tagline: string
  descriptions: ProjectDescriptions
  approvedTags: string[]
  categoryCandidates: string[]
  factualClaims: string[]
  prohibitedClaims: string[]
  founderName: string
  founderEmail: string
  socialLinks: Record<string, string>
  logoSquare?: string
  logoBanner?: string
  screenshots: string[]
  sheet?: SheetConfig
  createdAt: number
  updatedAt: number
}

export interface BacklinkTarget {
  name: string
  submitUrl: string
  priority?: string
  type?: string
  confidence?: string
  notes?: string
}

export interface LLMSettings {
  baseUrl: string
  apiKey: string
  model: string
}

export interface AppState {
  projects: ProductProfile[]
  activeProjectId: string | null
  llm: LLMSettings
}
