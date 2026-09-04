import { describe, expect, it } from 'vitest'
import { buildProjectContext } from './project-context'

const project = {
  id: 'quick-iching',
  name: 'Quick I Ching',
  url: 'https://quickiching.com/',
  primaryKeyword: 'i ching online',
  secondaryKeywords: ['i ching reading', 'three coin i ching', 'changing lines'],
  listingTitle: 'I Ching Online — Free Hexagram Reading | Quick I Ching',
  tagline: 'Free I Ching online readings with traditional casting methods',
  descriptions: {
    micro: 'Free I Ching online casting and hexagram readings.',
    short: 'Use the I Ching online with traditional casting methods and grounded hexagram interpretation.',
    medium: 'Use the I Ching online with Three-Coin, Yarrow Stalk, Mei Hua Yi Shu, or Manual Cast. See changing lines and primary and relating hexagrams.',
    long: 'Quick I Ching is a free online I Ching casting and hexagram reading tool with traditional casting methods.',
  },
  approvedTags: ['i ching', 'i ching online', 'hexagram', 'changing lines'],
  categoryCandidates: ['Divination', 'Spirituality'],
  factualClaims: ['Supports Three-Coin casting', 'Supports Yarrow Stalk casting'],
  prohibitedClaims: ['AI-powered fortune teller'],
  founderName: '',
  founderEmail: '',
  socialLinks: {},
  screenshots: [],
  createdAt: 1,
  updatedAt: 1,
} as const

describe('buildProjectContext', () => {
  it('includes reviewed SEO keywords and reusable copy', () => {
    const context = buildProjectContext(project as any)
    expect(context).toContain('i ching online')
    expect(context).toContain('three coin i ching')
    expect(context).toContain(project.listingTitle)
    expect(context).toContain(project.descriptions.short)
  })

  it('marks factual claims and prohibited claims as hard boundaries', () => {
    const context = buildProjectContext(project as any)
    expect(context).toContain('Supports Three-Coin casting')
    expect(context).toContain('AI-powered fortune teller')
    expect(context).toMatch(/do not|never|禁止/i)
  })
})
