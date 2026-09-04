import type { ProductProfile } from './types'

export function buildProjectContext(project: ProductProfile): string {
  const lines = [
    '## Authoritative Project Submission Data',
    '',
    `Project: ${project.name}`,
    `Canonical URL: ${project.url}`,
    `Primary keyword: ${project.primaryKeyword}`,
    `Secondary keywords: ${project.secondaryKeywords.join(', ')}`,
    '',
    `Approved listing title: ${project.listingTitle}`,
    `Approved tagline: ${project.tagline}`,
    '',
    'Approved descriptions:',
    `- micro: ${project.descriptions.micro}`,
    `- short: ${project.descriptions.short}`,
    `- medium: ${project.descriptions.medium}`,
    `- long: ${project.descriptions.long}`,
    '',
    `Approved tags: ${project.approvedTags.join(', ')}`,
    `Category candidates: ${project.categoryCandidates.join(', ')}`,
    '',
    'Factual claims you MAY use:',
    ...project.factualClaims.map((claim) => `- ${claim}`),
    '',
    'Prohibited claims — do not use, imply, or invent these:',
    ...project.prohibitedClaims.map((claim) => `- ${claim}`),
  ]

  if (project.founderName) lines.push('', `Founder: ${project.founderName}`)
  if (project.founderEmail) lines.push(`Email: ${project.founderEmail}`)

  const socials = Object.entries(project.socialLinks).filter(([, value]) => value)
  if (socials.length) {
    lines.push('', 'Approved social links:')
    for (const [platform, url] of socials) lines.push(`- ${platform}: ${url}`)
  }

  const assets: string[] = []
  if (project.logoSquare) assets.push(`Logo square: ${project.logoSquare}`)
  if (project.logoBanner) assets.push(`Logo banner: ${project.logoBanner}`)
  project.screenshots.forEach((url, index) => assets.push(`Screenshot ${index + 1}: ${url}`))
  if (assets.length) lines.push('', 'Assets for manual upload:', ...assets.map((asset) => `- ${asset}`))

  lines.push(
    '',
    'Grounding rules:',
    '- Treat every value above as reviewed source-of-truth data.',
    '- Prefer exact approved values when they fit the field.',
    '- You may shorten, reorganize, or select among approved values only when the current field requires it.',
    '- Use keywords naturally; never keyword-stuff.',
    '- Never introduce a product feature, benefit, target audience, pricing fact, founder fact, or claim that is not supported above.',
  )

  return lines.join('\n')
}
