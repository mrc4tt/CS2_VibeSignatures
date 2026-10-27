import { describe, expect, it } from 'vitest'
import type { DeepScanResult } from './deepScan'
import { browserMarks, changedLines, locateValue, marksByLine, misnamedKeys, problemLines, renameMarks, scanMarks } from './lineMarks'
import type { KeyVerdict } from './verdict'

const FILE = [
  '{',
  '  // offsets',
  '  "SelectItem": {',
  '    "offsets": {',
  '      "linux": 31,',
  '      "windows": 30',
  '    }',
  '  },',
  '  "Touch": {',
  '    "signatures": { "linux": "55 48", "windows": "40 53" },',
  '    "vtable": { "linux_index": 7, "windows_index": 8 }',
  '  }',
  '}',
].join('\n')

describe('placing a verdict on a line', () => {
  it('finds the platform value inside the key block', () => {
    expect(locateValue(FILE, 'SelectItem', 'linux')).toBe(5)
    expect(locateValue(FILE, 'SelectItem', 'windows')).toBe(6)
  })

  it('finds a vtable index in the vtable block, not the signatures', () => {
    expect(locateValue(FILE, 'Touch', 'linux')).toBe(10)
    expect(locateValue(FILE, 'Touch.vtable', 'windows')).toBe(11)
  })

  it('falls back to the key line, and to nothing for a key that is not there', () => {
    const vdf = '"Games"\n{\n  "Odd"\n  {\n    "lin"  "1"\n  }\n}'
    expect(locateValue(vdf, 'Odd', 'linux')).toBe(3)
    expect(locateValue(FILE, 'Missing', 'linux')).toBeNull()
  })
})

describe('deep scan marks', () => {
  const result: DeepScanResult = {
    build: '14192',
    results: [
      { name: 'SelectItem', platforms: {
        linux: { status: 'mismatch', reference: 32, verification: 'contradicted' },
        windows: { status: 'match', verification: 'verified' } } },
      { name: 'Touch', platforms: {
        linux: { status: 'ok', vtable: 'mismatch', verification: 'contradicted' },
        windows: { status: 'no-binary' } } },
    ],
    fixes: [
      { key: 'SelectItem', platform: 'linux', from: 31, to: 33, source: 'record' },
      { key: 'Touch.vtable', platform: 'linux', from: 7, to: 9, source: 'shipped' },
    ],
  }

  it('says what replaces a bad value, preferring the fix over the reference', () => {
    const marks = scanMarks(FILE, result)
    expect(marks.find((m) => m.line === 5)).toMatchObject({ tone: 'bad', note: { kind: 'expected', value: 33 } })
    expect(marks.find((m) => m.line === 6)).toMatchObject({ tone: 'ok' })
  })

  it('marks the vtable index a contradicted entry disagrees with', () => {
    const marks = scanMarks(FILE, result)
    expect(marks.find((m) => m.key === 'Touch.vtable')).toMatchObject({ line: 11, note: { kind: 'expected', value: 9 } })
    // nothing could judge windows, so it says nothing
    expect(marks.some((m) => m.key === 'Touch' && m.platform === 'windows')).toBe(false)
    expect(problemLines(marks)).toEqual([5, 10, 11])
  })

  it('carries the confirmed fix on the line it replaces, and no fix the scan withheld', () => {
    const marks = scanMarks(FILE, result)
    expect(marks.find((m) => m.line === 5)?.fix).toMatchObject({ key: 'SelectItem', from: 31, to: 33 })
    expect(marks.find((m) => m.key === 'Touch.vtable')?.fix).toMatchObject({ from: 7, to: 9 })
    // contradicted, but nothing confirmed replaces the signature itself
    expect(marks.find((m) => m.key === 'Touch' && m.platform === 'linux')?.fix).toBeUndefined()
    expect(marks.find((m) => m.line === 6)?.fix).toBeUndefined()
  })
})

describe('browser check marks', () => {
  it('marks stale values with the published one and current values green', () => {
    const verdicts: KeyVerdict[] = [
      { key: 'SelectItem', state: 'outdated', mine: { linux: 31, windows: 30 } as never, expected: [32, 30], linuxOk: false, windowsOk: true },
      { key: 'Touch', state: 'unknown' },
    ]
    const byLine = marksByLine(browserMarks(FILE, verdicts))
    expect(byLine.get(5)?.[0]).toMatchObject({ tone: 'bad', note: { kind: 'expected', value: 32 } })
    expect(byLine.get(6)?.[0]?.tone).toBe('ok')
    expect(byLine.has(10)).toBe(false)
    expect(byLine.get(5)?.[0]?.fix).toEqual({ key: 'SelectItem', platform: 'linux', from: 31, to: 32, source: 'shipped' })
    expect(byLine.get(6)?.[0]?.fix).toBeUndefined()
  })
})

describe('the fixed copy', () => {
  it('lists the lines a fix rewrote', () => {
    expect([...changedLines(FILE, FILE.replace('"linux": 31', '"linux": 32'))]).toEqual([5])
  })

  it('puts the worst mark first when two share a line', () => {
    const byLine = marksByLine([
      { line: 1, key: 'A', platform: 'linux', tone: 'ok' },
      { line: 1, key: 'A', platform: 'windows', tone: 'bad' },
    ])
    expect(byLine.get(1)?.map((m) => m.tone)).toEqual(['bad', 'ok'])
  })
})

describe('misnamedKeys', () => {
  const v = (key: string, state: KeyVerdict['state']): KeyVerdict => ({ key, state })

  it('pairs a misspelled key with the published key the file is missing', () => {
    const verdicts = [v('CSmokeGrenadeProjectile_Create', 'absent'), v('CSmokerenadeProjectile_Create', 'unknown')]
    expect(misnamedKeys(verdicts)).toEqual([{ from: 'CSmokerenadeProjectile_Create', to: 'CSmokeGrenadeProjectile_Create' }])
  })

  it('leaves the file\'s own keys alone', () => {
    // nothing missing: an extra key is the user's own
    expect(misnamedKeys([v('CSmokeGrenadeProjectile_Create', 'current'), v('CSmokerenadeProjectile_Create', 'unknown')])).toEqual([])
    // too far from the missing key to be a typo
    expect(misnamedKeys([v('CSmokeGrenadeProjectile_Create', 'absent'), v('MyOwnHook', 'unknown')])).toEqual([])
    // two missing keys equally near: no guessing which
    expect(misnamedKeys([v('Hook_A1', 'absent'), v('Hook_A2', 'absent'), v('Hook_A3', 'unknown')])).toEqual([])
  })

  it('marks the key line with the rename', () => {
    const text = '{\n  "CSmokerenadeProjectile_Create": {\n    "linux": "55"\n  }\n}'
    const rename = { from: 'CSmokerenadeProjectile_Create', to: 'CSmokeGrenadeProjectile_Create' }
    expect(renameMarks(text, [rename])).toEqual([
      { line: 2, key: rename.from, tone: 'bad', note: { kind: 'name', to: rename.to }, rename },
    ])
  })
})
