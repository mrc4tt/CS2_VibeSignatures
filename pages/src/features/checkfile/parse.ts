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
      if (PLATFORM_KEYS.some((platform) => platform in value)) {
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
  return best
}
