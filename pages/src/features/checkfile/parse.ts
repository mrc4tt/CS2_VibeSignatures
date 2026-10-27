/**
 * Reading a plugin's own gamedata file in the browser.
 *
 * Deliberately the same rule `publish_site_data.py` uses to build history.json,
 * because the keys produced here are compared against the keys in there: a node
 * that carries a platform field IS an entry, a segment that only names a kind
 * (`signatures`, `offsets`, `patches`, …) carries no identity and is dropped
 * from the key, and a Valve KeyValues file is read as blocks rather than JSON.
 * A different rule here would compare two different sets of names and report
 * every key as unknown.
 */

export type GameDataFormat = 'json' | 'jsonc' | 'vdf'

export interface FileValue {
  linux: string | number | null
  windows: string | number | null
}

export interface ParsedGameData {
  format: GameDataFormat
  values: Map<string, FileValue>
}

const PLATFORM_KEYS = ['linux', 'windows', 'linuxsteamrt64', 'win64'] as const

/**
 * A CounterStrikeSharp entry's `"vtable": {"class", "linux_index", "windows_index"}` block
 * has no platform keys on purpose, so publish_site_data.py publishes it as a key of its own,
 * `<entry>.vtable`, valued by the two indices. Read the same way here, or a file whose
 * signatures were patched would keep a slot index from an older build with nothing saying so.
 */
export const VTABLE_KEY_SUFFIX = '.vtable'

const KIND_WORDS = new Set([
  'signatures', 'signature', 'offsets', 'offset', 'patches', 'patch',
  'addresses', 'address', 'games', 'csgo', 'library', 'keys',
])

/** The innermost path segment that says WHICH entry this is. */
export function keyName(path: string[]): string {
  for (let index = path.length - 1; index >= 0; index -= 1) {
    if (!KIND_WORDS.has(path[index]!.toLowerCase())) return path[index]!
  }
  return path[path.length - 1] ?? ''
}

export function stripJsonc(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|\s)\/\/[^\n]*/g, '$1')
    .replace(/,(\s*[}\]])/g, '$1')
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function scalar(value: unknown): string | number | null {
  if (typeof value === 'string' || typeof value === 'number') return value
  return null
}

function flattenJson(document: unknown): Map<string, FileValue> {
  const out = new Map<string, FileValue>()
  const walk = (node: unknown, path: string[]): void => {
    if (!isPlainObject(node)) return
    for (const [key, value] of Object.entries(node)) {
      if (!isPlainObject(value)) continue
      const next = [...path, key]
      if (key === 'vtable' && path.length > 0 && typeof value.class === 'string') {
        out.set(keyName(path) + VTABLE_KEY_SUFFIX, {
          linux: scalar(value.linux_index ?? null),
          windows: scalar(value.windows_index ?? null),
        })
      } else if (PLATFORM_KEYS.some((platform) => platform in value)) {
        out.set(keyName(next), {
          linux: scalar(value.linux ?? value.linuxsteamrt64 ?? null),
          windows: scalar(value.windows ?? value.win64 ?? null),
        })
      } else {
        walk(value, next)
      }
    }
  }
  walk(document, [])
  return out
}

/**
 * Valve KeyValues, read as crudely as the pipeline reads it.
 *
 * The regex takes the first `"Name" { … }` block and the first platform lines
 * inside it, so for a nested file the OUTER block becomes the entry - a real
 * `.games.txt` ends up with a key literally called `Games`. That is wrong in
 * principle and right in practice: history.json was built by the same rule, so
 * matching it is what makes the keys line up. Improving it means changing
 * publish_site_data.py first.
 */
function flattenVdf(text: string): Map<string, FileValue> {
  const out = new Map<string, FileValue>()
  for (const match of text.matchAll(/"([^"]+)"\s*\{([\s\S]*?)\n\t*\}/g)) {
    const body = match[2] ?? ''
    const linux = /"(?:linux|linuxsteamrt64)"\s+"([^"]*)"/.exec(body)
    const windows = /"(?:windows|win64)"\s+"([^"]*)"/.exec(body)
    out.set(match[1]!, { linux: linux?.[1] ?? null, windows: windows?.[1] ?? null })
  }
  return out
}

export type JsonProblem = 'end' | 'comma' | 'colon' | 'key' | 'value' | 'string' | 'extra'

/** Where a JSON or JSONC text first stops being valid, 1-based like an editor. */
export class JsonSyntaxError extends Error {
  readonly line: number
  readonly column: number
  readonly problem: JsonProblem

  constructor(line: number, column: number, problem: JsonProblem) {
    super(`invalid JSON at ${line}:${column} (${problem})`)
    this.line = line
    this.column = column
    this.problem = problem
  }
}

/** True when the first thing that is not whitespace or a comment opens a JSON object or array. */
export function looksLikeJson(text: string): boolean {
  const start = text.replace(/^\uFEFF/, '').replace(/^(?:\s|\/\/[^\n]*|\/\*[\s\S]*?\*\/)*/, '')
  return start.startsWith('{') || start.startsWith('[')
}

/**
 * The first syntax error in a JSON text, read leniently as JSONC (comments and
 * trailing commas are fine), or null when it reads.
 *
 * JSON.parse knows where it failed, but every browser words and places that
 * differently (Safari gives no position at all), so the text is walked here and
 * the page can always point at a line.
 */
export function findJsonError(text: string): JsonSyntaxError | null {
  let at = text.charCodeAt(0) === 0xfeff ? 1 : 0
  const fail = (problem: JsonProblem, where = at): never => {
    const before = text.slice(0, where).split('\n')
    throw new JsonSyntaxError(before.length, before[before.length - 1]!.length + 1, problem)
  }
  const skip = () => {
    for (;;) {
      while (at < text.length && /\s/.test(text[at]!)) at += 1
      if (text.startsWith('//', at)) {
        const end = text.indexOf('\n', at)
        at = end < 0 ? text.length : end
      } else if (text.startsWith('/*', at)) {
        const end = text.indexOf('*/', at + 2)
        if (end < 0) fail('end', text.length)
        at = end + 2
      } else {
        return
      }
    }
  }
  const string = () => {
    const start = at
    at += 1
    while (at < text.length && text[at] !== '"') {
      if (text[at] === '\n') fail('string', start)
      at += text[at] === '\\' ? 2 : 1
    }
    if (at >= text.length) fail('string', start)
    at += 1
  }
  const value = (): void => {
    skip()
    if (at >= text.length) fail('end')
    const char = text[at]
    if (char === '{' || char === '[') {
      const close = char === '{' ? '}' : ']'
      at += 1
      skip()
      while (text[at] !== close) {
        if (at >= text.length) fail('end')
        if (close === '}') {
          if (text[at] !== '"') fail('key')
          string()
          skip()
          if (text[at] !== ':') fail(at >= text.length ? 'end' : 'colon')
          at += 1
        }
        value()
        skip()
        if (text[at] === ',') {
          at += 1
          skip()
        } else if (text[at] !== close) {
          fail(at >= text.length ? 'end' : 'comma')
        }
      }
      at += 1
    } else if (char === '"') {
      string()
    } else {
      const literal = /^(?:-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)/.exec(text.slice(at, at + 400))
      if (!literal) fail('value')
      at += literal![0].length
    }
  }
  try {
    value()
    skip()
    if (at < text.length) fail('extra')
    return null
  } catch (error) {
    if (error instanceof JsonSyntaxError) return error
    throw error
  }
}

/**
 * Parse without trusting the file name.
 *
 * People rename these files, so the format is decided by what actually reads:
 * strict JSON, then JSONC (comments and trailing commas), then KeyValues. The
 * parse that finds the most entries wins, so a JSONC file saved as `.json` is
 * still read, and a KeyValues file is never handed to a JSON parser. A parse
 * that succeeds but finds nothing is a real answer, not a failure — CS2FOW's
 * `games.txt` genuinely carries no platform entries — so only a file no parser
 * can read at all throws.
 *
 * A text that opens like JSON and that neither JSON reader takes is broken JSON,
 * not KeyValues: the KeyValues reader would find nothing in it and the page would
 * say "no entries" about a missing comma. That throws a JsonSyntaxError instead.
 */
export function parseGameData(text: string): ParsedGameData {
  const attempts: Array<[GameDataFormat, () => Map<string, FileValue>]> = [
    ['json', () => flattenJson(JSON.parse(text))],
    ['jsonc', () => flattenJson(JSON.parse(stripJsonc(text)))],
    ['vdf', () => flattenVdf(text)],
  ]
  let best: ParsedGameData | null = null
  for (const [format, read] of attempts) {
    try {
      const values = read()
      if (!best || values.size > best.values.size) best = { format, values }
    } catch {
      // a format that does not apply is not an error on its own
    }
  }
  if (!best) throw new Error('unreadable')
  if (best.format === 'vdf' && best.values.size === 0 && looksLikeJson(text)) {
    const broken = findJsonError(text)
    if (broken) throw broken
  }
  return best
}
