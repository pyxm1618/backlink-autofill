import { describe, expect, it } from 'vitest'
import { resolveActiveProject } from './storage'

const projects = [
  { id: 'a', name: 'A' },
  { id: 'b', name: 'B' },
] as any[]

describe('resolveActiveProject', () => {
  it('does not silently fall back to the first project when activeProjectId is missing', () => {
    expect(resolveActiveProject(projects, null)).toBeNull()
  })

  it('returns only the explicitly selected project', () => {
    expect(resolveActiveProject(projects, 'b')?.id).toBe('b')
  })
})
