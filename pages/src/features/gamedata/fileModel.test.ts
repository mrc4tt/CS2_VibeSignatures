import { describe, expect, it } from 'vitest'
import {
  buildLineModel, changedKeys, describeFiles, foldRanges, formatLabel, hiddenLines,
  notProducedKeys, tokenizeLine,
} from './fileModel'
import type { GameDataFileDescriptor, GameDataMetadata } from './types'

const metadata: GameDataMetadata = {
  schema_version: 2,
  gamever: '14181',
  file: 'CounterStrikeSharp/gamedata.json',
  summary: { total: 3, covered: 2, updated: 1 },
  entries: [
    { name: 'UTIL_ClientPrintAll', covered: true, covered_lines: [4, 5, 6], updated: false },
    {
      name: 'ClientPrint', covered: true, covered_lines: [11, 12, 13], updated: true,
      changes: [
        { path: ['ClientPrint', 'signatures', 'windows'], before: '40 53', after: '48 85 C9', line: 12 },
        { path: ['ClientPrint', 'signatures', 'linux'], before: '55 48 8D', after: '55 48 89', line: 13 },
        { path: ['ClientPrint', 'gone'], before: 'x', after: null, line: null },
      ],
    },
    { name: 'GameEventManager', covered: false, updated: false },
  ],
}

describe('reading a generated file', () => {
  it('maps metadata onto lines', () => {
    const model = buildLineModel(metadata)
    expect([...model.covered].sort((a, b) => a - b)).toEqual([4, 5, 6, 11, 12, 13])
    expect(model.changed.get(12)?.[0].before).toBe('40 53')
    expect(model.changed.get(13)).toHaveLength(1)
    expect(model.unanchored).toHaveLength(1)
  })

  it('is empty rather than broken without metadata', () => {
    const model = buildLineModel(undefined)
    expect(model.covered.size).toBe(0)
    expect(model.changed.size).toBe(0)
    expect(changedKeys(undefined)).toEqual([])
    expect(notProducedKeys(undefined)).toEqual([])
  })

  it('lists the keys that moved and the keys with no value', () => {
    expect(changedKeys(metadata).map((key) => key.name)).toEqual(['ClientPrint'])
    expect(changedKeys(metadata)[0].line).toBe(11)
    expect(notProducedKeys(metadata)).toEqual(['GameEventManager'])
  })
})

describe('folding', () => {
  const lines = [
    '{',
    '  "UTIL_ClientPrintAll": {',
    '    "signatures": {',
    '      "linux": "55"',
    '    }',
    '  },',
    '  "short": { "a": 1 }',
    '}',
  ]

  it('finds a block per opening brace that spans more than one line', () => {
    const ranges = foldRanges(lines)
    expect(ranges.get(2)).toBe(6)
    expect(ranges.get(3)).toBe(5)
    expect(ranges.has(7)).toBe(false)   // opens and closes on the same line
  })

  it('hides exactly the body of a folded block', () => {
    const ranges = foldRanges(lines)
    expect([...hiddenLines(new Set([3]), ranges)].sort((a, b) => a - b)).toEqual([4, 5])
    expect(hiddenLines(new Set([999]), ranges).size).toBe(0)
  })
})

describe('tokenizing', () => {
  it('separates a key from its value', () => {
    const tokens = tokenizeLine('  "library": "server",', 'json')
    expect(tokens.filter((token) => token.kind === 'key').map((token) => token.text)).toEqual(['"library"'])
    expect(tokens.filter((token) => token.kind === 'string').map((token) => token.text)).toEqual(['server'])
  })

  it('calls a byte pattern out as hex, not as a string', () => {
    const tokens = tokenizeLine('  "linux": "55 48 89 E5 41 57 ? ? ?",', 'json')
    expect(tokens.find((token) => token.kind === 'hex')?.text).toBe('55 48 89 E5 41 57 ? ? ?')
  })

  it('keeps numbers and comments apart', () => {
    expect(tokenizeLine('  "windows": 103,', 'jsonc').some((token) => token.kind === 'number')).toBe(true)
    expect(tokenizeLine('  // called from Host_Say', 'jsonc')[1]?.kind).toBe('comment')
  })

  it('treats the first string on a KeyValues line as the key', () => {
    const tokens = tokenizeLine('\t"CBaseEntity"\t"0xaf0"', 'vdf')
    expect(tokens.find((token) => token.kind === 'key')?.text).toBe('"CBaseEntity"')
  })

  it('loses nothing: the tokens rebuild the line', () => {
    const line = '  "linux": "55 48 89 E5",   // note'
    const rebuilt = tokenizeLine(line, 'jsonc')
      .map((token) => (token.kind === 'string' || token.kind === 'hex' ? token.text : token.text))
      .join('')
    expect(rebuilt).toBe(line)
  })
})

describe('describing the files of a build', () => {
  function file(plugin: string, fileName: string, summary?: { total: number; covered: number; updated: number }): GameDataFileDescriptor {
    return {
      id: `${plugin}/${fileName}`,
      plugin,
      fileName,
      language: 'json',
      content: { url: 'x', sha256: 'a'.repeat(64), size: 10 },
      metadata: summary
        ? { url: 'y', sha256: 'b'.repeat(64), size: 10, schemaVersion: 2, summary }
        : undefined,
    }
  }

  it('computes the gap and the percentage, and sorts by plugin', () => {
    const described = describeFiles([
      file('swiftlys2', 'offsets.jsonc', { total: 132, covered: 18, updated: 1 }),
      file('CS2Fixes', 'cs2fixes.jsonc', { total: 75, covered: 74, updated: 38 }),
    ])
    expect(described.map((item) => item.descriptor.plugin)).toEqual(['CS2Fixes', 'swiftlys2'])
    expect(described[1].gap).toBe(114)
    expect(described[1].percent).toBe(14)
  })

  it('treats a file with no metadata as zero of zero rather than dividing by it', () => {
    const [described] = describeFiles([file('modsharp-public', 'core.games.jsonc')])
    expect(described.total).toBe(0)
    expect(described.percent).toBe(0)
    expect(described.gap).toBe(0)
  })

  it('names the KeyValues formats by what they are', () => {
    expect(formatLabel('vdf')).toBe('KeyValues')
    expect(formatLabel('flat')).toBe('KeyValues')
    expect(formatLabel('jsonc')).toBe('JSONC')
  })
})
