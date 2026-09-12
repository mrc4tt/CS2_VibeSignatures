import { describe, expect, it } from 'vitest'
import { parseGameData } from './parse'
import { patchFile } from './patch'
import type { KeyVerdict } from './verdict'

const outdated = (
  key: string,
  mine: { linux?: string | number | null; windows?: string | number | null },
  expected: [unknown, unknown],
  ok: { linuxOk?: boolean; windowsOk?: boolean },
): KeyVerdict => ({
  key,
  state: 'outdated',
  mine: { linux: mine.linux ?? null, windows: mine.windows ?? null },
  expected,
  ...ok,
})

describe('rewriting a file with the published values', () => {
  it('replaces only the platform that is wrong and leaves the rest byte for byte', () => {
    const text = `{
  "ClientPrint": {
    "signatures": { "library": "server", "linux": "OLD-L", "windows": "KEEP-W" }
  }
}`
    const result = patchFile(text, [
      outdated('ClientPrint', { linux: 'OLD-L', windows: 'KEEP-W' }, ['NEW-L', 'KEEP-W'], { linuxOk: false, windowsOk: true }),
    ])
    expect(result.applied).toBe(1)
    expect(result.skipped).toEqual([])
    expect(result.text).toContain('"linux": "NEW-L"')
    expect(result.text).toContain('"windows": "KEEP-W"')
    // the library line, the indentation and the braces are untouched
    expect(result.text).toBe(text.replace('OLD-L', 'NEW-L'))
  })

  it('keeps comments, which is the whole reason it is text surgery', () => {
    const text = `{
  // CS2Fixes explains its patches in comments; a reserialised file loses them
  "Signatures": {
    "UTIL_Remove": { "linux": "AA BB", "windows": "CC DD" },
  }
}`
    const result = patchFile(text, [
      outdated('UTIL_Remove', { linux: 'AA BB', windows: 'CC DD' }, ['EE FF', 'CC DD'], { linuxOk: false, windowsOk: true }),
    ])
    expect(result.text).toContain('// CS2Fixes explains its patches in comments')
    expect(result.text).toContain('"linux": "EE FF"')
    // and the trailing comma JSONC allows survives
    expect(result.text).toContain('},\n  }')
  })

  it('replaces a numeric offset without touching the same number elsewhere', () => {
    const text = `{
  "First": { "offsets": { "linux": 29, "windows": 28 } },
  "Second": { "offsets": { "linux": 29, "windows": 29 } }
}`
    const result = patchFile(text, [
      outdated('Second', { linux: 29, windows: 29 }, [31, 29], { linuxOk: false, windowsOk: true }),
    ])
    expect(result.applied).toBe(1)
    expect(result.text).toContain('"First": { "offsets": { "linux": 29, "windows": 28 } }')
    expect(result.text).toContain('"Second": { "offsets": { "linux": 31, "windows": 29 } }')
  })

  it('rewrites KeyValues as well as JSON', () => {
    const text = `"Games"
{
\t"csgo"
\t{
\t\t"Signatures"
\t\t{
\t\t\t"Host_Say"
\t\t\t{
\t\t\t\t"library"  "server"
\t\t\t\t"linux"    "OLD"
\t\t\t\t"windows"  "W"
\t\t\t}
\t\t}
\t}
}`
    const result = patchFile(text, [
      outdated('Host_Say', { linux: 'OLD', windows: 'W' }, ['NEW', 'W'], { linuxOk: false, windowsOk: true }),
    ])
    expect(result.applied).toBe(1)
    expect(result.text).toContain('"linux"    "NEW"')
  })

  it('refuses rather than guesses when a value appears twice under one key', () => {
    const text = `{
  "Odd": { "signatures": { "linux": "SAME", "linuxsteamrt64": "SAME" }, "windows": "W" }
}`
    const result = patchFile(text, [
      outdated('Odd', { linux: 'SAME', windows: 'W' }, ['NEW', 'W'], { linuxOk: false, windowsOk: true }),
    ])
    expect(result.applied).toBe(0)
    expect(result.skipped).toEqual([{ key: 'Odd', platform: 'linux', reason: 'ambiguous' }])
    expect(result.text).toBe(text)
  })

  it('reports a key it cannot find instead of dropping it silently', () => {
    const result = patchFile('{}', [
      outdated('Missing', { linux: 'A' }, ['B', null], { linuxOk: false }),
    ])
    expect(result.applied).toBe(0)
    expect(result.skipped).toEqual([{ key: 'Missing', platform: 'linux', reason: 'notFound' }])
  })

  it('produces a file that parses to the published values', () => {
    const text = `{
  "A": { "signatures": { "linux": "OLD-A", "windows": "OLD-AW" } },
  "B": { "offsets": { "linux": 10, "windows": 11 } }
}`
    const result = patchFile(text, [
      outdated('A', { linux: 'OLD-A', windows: 'OLD-AW' }, ['NEW-A', 'NEW-AW'], { linuxOk: false, windowsOk: false }),
      outdated('B', { linux: 10, windows: 11 }, [20, 11], { linuxOk: false, windowsOk: true }),
    ])
    expect(result.applied).toBe(3)
    const { values } = parseGameData(result.text)
    expect(values.get('A')).toEqual({ linux: 'NEW-A', windows: 'NEW-AW' })
    expect(values.get('B')).toEqual({ linux: 20, windows: 11 })
  })
})
