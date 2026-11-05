/**
 * The numbers the side panel shows for a file before anything is scanned: how
 * many signatures, offsets and vtable indices it carries, and which game
 * libraries it reaches into. Read from the parsed values and the text alone.
 */

import { VTABLE_KEY_SUFFIX, type FileValue } from './parse'

export interface FileDetails {
  signatures: number
  offsets: number
  vtables: number
  libraries: string[]
}

export function fileDetails(text: string, values: Map<string, FileValue>): FileDetails {
  let signatures = 0
  let offsets = 0
  let vtables = 0
  for (const [key, value] of values) {
    if (key.endsWith(VTABLE_KEY_SUFFIX)) vtables += 1
    else if (typeof (value.linux ?? value.windows) === 'number') offsets += 1
    else signatures += 1
  }
  // CounterStrikeSharp says "library", CS2Fixes and KeyValues files say "module"
  // or "library"; both forms, JSON (`"k": "v"`) and KeyValues (`"k"  "v"`).
  const libraries = new Set<string>()
  for (const hit of text.matchAll(/"(?:library|module)"\s*(?::\s*|\s+)"([\w.-]+)"/g)) libraries.add(hit[1]!)
  return { signatures, offsets, vtables, libraries: [...libraries].sort() }
}

/**
 * Which plugin's layout a file is written in, for the status line, when the
 * file is not one we publish. Only the shapes that say so unambiguously: a
 * CounterStrikeSharp entry is `"Name": { "signatures": { "library": ... } }`
 * (or `"offsets"`), a KeyValues file opens with `"Games"`.
 */
export function guessLayout(text: string, format: 'json' | 'jsonc' | 'vdf'): string | undefined {
  if (format === 'vdf') return /^\s*(?:\/\/[^\n]*\n\s*)*"Games"/.test(text) ? 'KeyValues' : undefined
  if (/"\w+"\s*:\s*\{\s*"(?:signatures|offsets)"\s*:\s*\{\s*"(?:library|windows|linux)"/.test(text)) return 'CounterStrikeSharp'
  return undefined
}
