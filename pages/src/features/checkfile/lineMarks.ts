/**
 * Which line of the user's own file each verdict belongs to.
 *
 * Neither the deep scan nor the browser check knows about lines: both speak in
 * keys. The file view needs them on lines, so they are placed here with the
 * same key windows the patcher uses - a mark lands on exactly the value a fix
 * would rewrite, and nowhere a fix could not reach.
 */

import { platformTone, type DeepFix, type DeepScanResult, type Platform } from './deepScan'
import { PLATFORM_NAMES, VTABLE_INDEX_NAMES, verdictWindow } from './patch'
import { VTABLE_KEY_SUFFIX } from './parse'
import type { KeyVerdict } from './verdict'

export type MarkTone = 'bad' | 'warn' | 'ok'

export type MarkNote =
  | { kind: 'expected'; value: string | number }
  | { kind: 'hits'; count: number }
  | { kind: 'vtable'; state: string }
  | { kind: 'status'; status: string }

export interface LineMark {
  line: number
  key: string
  platform: Platform
  tone: MarkTone
  note?: MarkNote
}

const escape = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const lineAt = (text: string, offset: number): number => {
  let line = 1
  for (let index = 0; index < offset; index += 1) if (text.charCodeAt(index) === 10) line += 1
  return line
}

/**
 * The 1-based line holding `key`'s value for `platform`, or the key's own line
 * when the platform is not spelled out in its block (a KeyValues file that
 * nests it differently, a value the plugin inherits). Null when the key is not
 * in the file at all.
 */
export function locateValue(text: string, key: string, platform: Platform): number | null {
  const window = verdictWindow(text, key)
  if (!window) return null
  const names = (key.endsWith(VTABLE_KEY_SUFFIX) ? VTABLE_INDEX_NAMES : PLATFORM_NAMES)[platform]
  const pattern = new RegExp(`"(?:${names.map(escape).join('|')})"\\s*(?::|\\s)`)
  const hit = pattern.exec(text.slice(window.from, window.to))
  return lineAt(text, window.from + (hit ? hit.index : 0))
}

const fixKey = (key: string, platform: Platform): string => `${key}\u0000${platform}`

/**
 * Marks from the deep scan. Values nothing could judge get none: a grey line
 * says nothing a plain one does not. A bad value says what replaces it when the
 * scan knows, and a contradicted vtable also marks the index it disagrees with.
 */
export function scanMarks(text: string, result: DeepScanResult): LineMark[] {
  const fixes = new Map<string, DeepFix>()
  for (const fix of result.fixes ?? []) fixes.set(fixKey(fix.key, fix.platform), fix)
  const marks: LineMark[] = []
  for (const row of result.results) {
    for (const platform of ['linux', 'windows'] as const) {
      const info = row.platforms[platform]
      const tone = platformTone(info)
      if (!info || tone === 'neutral') continue
      const line = locateValue(text, row.name, platform)
      if (line === null) continue
      const fix = fixes.get(fixKey(row.name, platform))
      const note: MarkNote | undefined = tone === 'ok'
        ? undefined
        : fix
          ? { kind: 'expected', value: fix.to }
          : info.status === 'mismatch' && info.reference !== undefined
            ? { kind: 'expected', value: info.reference }
            : info.status === 'ambiguous' && info.count
              ? { kind: 'hits', count: info.count }
              : info.vtable && info.vtable !== 'ok'
                ? { kind: 'vtable', state: info.vtable }
                : { kind: 'status', status: info.status }
      marks.push({ line, key: row.name, platform, tone, note })

      if (tone === 'bad' && info.vtable && info.vtable !== 'ok') {
        const vtableKey = `${row.name}${VTABLE_KEY_SUFFIX}`
        const vtableLine = locateValue(text, vtableKey, platform)
        if (vtableLine !== null && vtableLine !== line) {
          const vtableFix = fixes.get(fixKey(vtableKey, platform))
          marks.push({
            line: vtableLine,
            key: vtableKey,
            platform,
            tone,
            note: vtableFix ? { kind: 'expected', value: vtableFix.to } : { kind: 'vtable', state: info.vtable },
          })
        }
      }
    }
  }
  return marks
}

/** Marks from the in-browser check: stale values in red with the published one, current ones in green. */
export function browserMarks(text: string, verdicts: KeyVerdict[]): LineMark[] {
  const marks: LineMark[] = []
  for (const verdict of verdicts) {
    if (verdict.state !== 'outdated' && verdict.state !== 'current') continue
    for (const [index, platform] of (['linux', 'windows'] as const).entries()) {
      const ok = platform === 'linux' ? verdict.linuxOk : verdict.windowsOk
      if (ok === undefined) continue
      const line = locateValue(text, verdict.key, platform)
      if (line === null) continue
      const expected = verdict.expected?.[index]
      marks.push({
        line,
        key: verdict.key,
        platform,
        tone: ok ? 'ok' : 'bad',
        note: !ok && (typeof expected === 'string' || typeof expected === 'number')
          ? { kind: 'expected', value: expected }
          : undefined,
      })
    }
  }
  return marks
}

const RANK: Record<MarkTone, number> = { bad: 0, warn: 1, ok: 2 }

/** Marks grouped per line, worst first, so a line shows the worst thing said about it. */
export function marksByLine(marks: LineMark[]): Map<number, LineMark[]> {
  const byLine = new Map<number, LineMark[]>()
  for (const mark of marks) byLine.set(mark.line, [...(byLine.get(mark.line) ?? []), mark])
  for (const list of byLine.values()) list.sort((left, right) => RANK[left.tone] - RANK[right.tone])
  return byLine
}

/** Lines worth jumping to: every line with something wrong on it, in file order. */
export function problemLines(marks: LineMark[]): number[] {
  return [...new Set(marks.filter((mark) => mark.tone !== 'ok').map((mark) => mark.line))].sort((a, b) => a - b)
}

/** Lines that differ between the file and its fixed copy; value surgery never adds or drops a line. */
export function changedLines(before: string, after: string): Set<number> {
  const left = before.split('\n')
  const right = after.split('\n')
  const changed = new Set<number>()
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    if (left[index] !== right[index]) changed.add(index + 1)
  }
  return changed
}
