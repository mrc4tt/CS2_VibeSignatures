import { describe, expect, it } from 'vitest'
import { byteTokens, diffTokens, isByteString } from './tokenDiff'

const changed = (tokens: { token: string; changed: boolean }[]) =>
  tokens.filter((item) => item.changed).map((item) => item.token)

describe('diffTokens', () => {
  it('marks only the substituted byte', () => {
    const diff = diffTokens(byteTokens('48 8D 05 BD ? ? ? 48 8B 38'), byteTokens('48 8D 05 7D ? ? ? 48 8B 38'))
    expect(changed(diff.before)).toEqual(['BD'])
    expect(changed(diff.after)).toEqual(['7D'])
  })

  it('marks appended bytes on the new side only', () => {
    const diff = diffTokens(byteTokens('48 8B 38'), byteTokens('48 8B 38 48 8B 07'))
    expect(changed(diff.before)).toEqual([])
    expect(changed(diff.after)).toEqual(['48', '8B', '07'])
  })

  it('treats ? and ?? as the same wildcard, and ignores hex case', () => {
    const diff = diffTokens(byteTokens('E8 ?? ?? ?? ?? 84 c0'), byteTokens('E8 ? ? ? ? 84 C0'))
    expect(changed(diff.before)).toEqual([])
    expect(changed(diff.after)).toEqual([])
  })

  it('keeps every token, in order, on both sides', () => {
    const before = byteTokens('40 53 48 83 EC ? 48 8B D9')
    const after = byteTokens('40 55 56 48 83 EC ? 8B D9 90')
    const diff = diffTokens(before, after)
    expect(diff.before.map((item) => item.token)).toEqual(before)
    expect(diff.after.map((item) => item.token)).toEqual(after)
  })
})

describe('isByteString', () => {
  it('accepts signatures and short patch bytes, not other strings or numbers', () => {
    expect(isByteString('55 48 89 E5 ? ?')).toBe(true)
    expect(isByteString('EB')).toBe(true)
    expect(isByteString('11 43')).toBe(true)
    expect(isByteString('m_iTeamNum')).toBe(false)
    expect(isByteString(148)).toBe(false)
    expect(isByteString(null)).toBe(false)
  })
})
