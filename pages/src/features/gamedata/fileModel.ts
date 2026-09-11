import type { GameDataChange, GameDataFileDescriptor, GameDataMetadata } from './types'

export interface FileLineModel {
  /** Lines whose value this build wrote. */
  covered: Set<number>
  /** Lines whose value changed, with what it was. */
  changed: Map<number, GameDataChange[]>
  /** Changes the generator could not anchor to a line in the final file. */
  unanchored: GameDataChange[]
}

export function buildLineModel(metadata?: GameDataMetadata): FileLineModel {
  const covered = new Set<number>()
  const changed = new Map<number, GameDataChange[]>()
  const unanchored: GameDataChange[] = []
  if (!metadata) return { covered, changed, unanchored }
  for (const entry of metadata.entries) {
    if (entry.covered) for (const line of entry.covered_lines ?? []) covered.add(line)
    for (const change of entry.changes ?? []) {
      if (change.line === null || change.line === undefined) {
        unanchored.push(change)
        continue
      }
      const existing = changed.get(change.line)
      if (existing) existing.push(change)
      else changed.set(change.line, [change])
    }
  }
  return { covered, changed, unanchored }
}

export interface ChangedKey {
  name: string
  changes: GameDataChange[]
  line?: number
}

/** One row per key that moved, newest generator metadata as the source. */
export function changedKeys(metadata?: GameDataMetadata): ChangedKey[] {
  if (!metadata) return []
  return metadata.entries
    .filter((entry) => (entry.changes ?? []).length > 0)
    .map((entry) => ({
      name: entry.name,
      changes: entry.changes ?? [],
      line: (entry.covered_lines ?? [])[0],
    }))
}

export function notProducedKeys(metadata?: GameDataMetadata): string[] {
  if (!metadata) return []
  return metadata.entries.filter((entry) => !entry.covered).map((entry) => entry.name)
}

/**
 * Which lines open a block that can be folded away, and where that block ends.
 * Brace depth is enough for all three formats the generators emit (JSON, JSONC
 * and KeyValues), and it needs no parser.
 */
export function foldRanges(lines: string[]): Map<number, number> {
  const ranges = new Map<number, number>()
  const stack: number[] = []
  lines.forEach((line, index) => {
    const lineNumber = index + 1
    const opens = (line.match(/[{[]/g) ?? []).length
    const closes = (line.match(/[}\]]/g) ?? []).length
    if (opens > closes) stack.push(lineNumber)
    else if (closes > opens) {
      const start = stack.pop()
      if (start !== undefined && lineNumber - start > 1) ranges.set(start, lineNumber)
    }
  })
  return ranges
}

export function hiddenLines(folded: Set<number>, ranges: Map<number, number>): Set<number> {
  const hidden = new Set<number>()
  for (const start of folded) {
    const end = ranges.get(start)
    if (end === undefined) continue
    for (let line = start + 1; line <= end; line += 1) hidden.add(line)
  }
  return hidden
}

export type TokenKind = 'key' | 'string' | 'number' | 'punct' | 'comment' | 'plain' | 'hex'

export interface Token {
  kind: TokenKind
  text: string
}

const HEX_VALUE = /^[0-9A-Fa-f?\s]{8,}$/

/**
 * A generated gamedata file has four kinds of thing on a line: a key, a value, a
 * comment and punctuation. A hex value is called out separately, because the
 * whole point of this page is reading byte patterns.
 */
export function tokenizeLine(line: string, format: GameDataFileDescriptor['language']): Token[] {
  const tokens: Token[] = []
  const pattern = /("(?:[^"\\]|\\.)*")(\s*:)?|(\/\/[^\n]*)|(-?\b\d+(?:\.\d+)?\b)|([{}[\],:])/g
  let last = 0
  let firstString = true
  let match: RegExpExecArray | null
  while ((match = pattern.exec(line)) !== null) {
    if (match.index > last) tokens.push({ kind: 'plain', text: line.slice(last, match.index) })
    last = pattern.lastIndex
    if (match[1] !== undefined) {
      const bare = match[1].slice(1, -1)
      const isKey = Boolean(match[2]) || ((format === 'vdf' || format === 'flat') && firstString)
      if (isKey) {
        tokens.push({ kind: 'key', text: match[1] })
        if (match[2]) tokens.push({ kind: 'punct', text: match[2] })
        firstString = false
      } else {
        tokens.push({ kind: 'punct', text: '"' })
        tokens.push({ kind: HEX_VALUE.test(bare) && bare.trim().length > 0 ? 'hex' : 'string', text: bare })
        tokens.push({ kind: 'punct', text: '"' })
      }
    } else if (match[3] !== undefined) tokens.push({ kind: 'comment', text: match[3] })
    else if (match[4] !== undefined) tokens.push({ kind: 'number', text: match[4] })
    else tokens.push({ kind: 'punct', text: match[5] })
  }
  if (last < line.length) tokens.push({ kind: 'plain', text: line.slice(last) })
  return tokens
}

export interface PluginFile {
  descriptor: GameDataFileDescriptor
  covered: number
  total: number
  updated: number
  gap: number
  percent: number
}

export function describeFiles(files: GameDataFileDescriptor[]): PluginFile[] {
  return files
    .map((descriptor) => {
      const summary = descriptor.metadata?.summary
      const total = summary?.total ?? 0
      const covered = summary?.covered ?? 0
      return {
        descriptor,
        covered,
        total,
        updated: summary?.updated ?? 0,
        gap: Math.max(0, total - covered),
        percent: total > 0 ? Math.round((100 * covered) / total) : 0,
      }
    })
    .sort((left, right) =>
      left.descriptor.plugin.localeCompare(right.descriptor.plugin)
      || left.descriptor.fileName.localeCompare(right.descriptor.fileName))
}

export function formatLabel(language: GameDataFileDescriptor['language']): string {
  if (language === 'vdf' || language === 'flat') return 'KeyValues'
  return language.toUpperCase()
}
