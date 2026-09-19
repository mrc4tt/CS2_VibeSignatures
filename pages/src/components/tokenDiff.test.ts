import { describe, expect, it } from 'vitest'
import { byteTokens, diffTokens, isWildcard } from './tokenDiff'

const changed = (tokens: { token: string; changed: boolean }[]) =>
  tokens.filter((item) => item.changed).map((item) => item.token)
const tokens = (value: string) => byteTokens(value)!.tokens

describe('diffTokens', () => {
  it('marks only the substituted byte', () => {
    const diff = diffTokens(tokens('48 8D 05 BD ? ? ? 48 8B 38'), tokens('48 8D 05 7D ? ? ? 48 8B 38'))
    expect(changed(diff.before)).toEqual(['BD'])
    expect(changed(diff.after)).toEqual(['7D'])
  })

  it('marks appended bytes on the new side only', () => {
    const diff = diffTokens(tokens('48 8B 38'), tokens('48 8B 38 48 8B 07'))
    expect(changed(diff.before)).toEqual([])
    expect(changed(diff.after)).toEqual(['48', '8B', '07'])
  })

  it('treats ? and ?? as the same wildcard, and ignores hex case', () => {
    const diff = diffTokens(tokens('E8 ?? ?? ?? ?? 84 c0'), tokens('E8 ? ? ? ? 84 C0'))
    expect(changed(diff.before)).toEqual([])
    expect(changed(diff.after)).toEqual([])
  })

  it('keeps every token, in order, on both sides', () => {
    const before = tokens('40 53 48 83 EC ? 48 8B D9')
    const after = tokens('40 55 56 48 83 EC ? 8B D9 90')
    const diff = diffTokens(before, after)
    expect(diff.before.map((item) => item.token)).toEqual(before)
    expect(diff.after.map((item) => item.token)).toEqual(after)
  })

  it('diffs the escaped KeyValues spelling the same way', () => {
    const diff = diffTokens(tokens('\\x48\\x8B\\xC4\\x2A'), tokens('\\x48\\x8B\\xC5\\x2A'))
    expect(changed(diff.before)).toEqual(['\\xC4'])
    expect(changed(diff.after)).toEqual(['\\xC5'])
  })
})

describe('byteTokens', () => {
  it('reads both spellings of bytes, and nothing else', () => {
    expect(byteTokens('55 48 89 E5 ? ?')).toEqual({ tokens: ['55', '48', '89', 'E5', '?', '?'], separator: ' ' })
    expect(byteTokens('EB')?.tokens).toEqual(['EB'])
    expect(byteTokens('\\x55\\x2A')).toEqual({ tokens: ['\\x55', '\\x2A'], separator: '' })
    expect(byteTokens('m_iTeamNum')).toBeUndefined()
    expect(byteTokens(148)).toBeUndefined()
    expect(byteTokens(null)).toBeUndefined()
  })

  it('knows the wildcard in every spelling', () => {
    expect(['?', '??', '\\x2A', '\\x2a'].every(isWildcard)).toBe(true)
    expect(isWildcard('2A')).toBe(false)
  })
})
