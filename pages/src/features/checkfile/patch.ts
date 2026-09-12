/**
 * Rewriting the user's own file with the published values.
 *
 * Deliberately text surgery rather than parse-and-reserialise. A plugin's file
 * is hand-maintained: cs2fixes.jsonc carries comments explaining what each
 * patch does, KeyValues files carry their own layout, and handing someone back a
 * machine-formatted file with their comments stripped is a worse gift than the
 * problem it solves. So only the stale values are replaced, byte for byte, and
 * everything else in the file is left exactly as it was.
 *
 * A replacement that cannot be placed unambiguously is refused and reported, not
 * guessed: writing the right value into the wrong key would be worse than
 * leaving the file alone, and the whole point of the page is that a server owner
 * can trust what it says.
 */

import type { KeyVerdict } from './verdict'

export interface PatchResult {
  text: string
  applied: number
  /** Keys that had to be left to a human, with why. */
  skipped: Array<{ key: string; platform: 'linux' | 'windows'; reason: 'notFound' | 'ambiguous' }>
}

const PLATFORM_NAMES: Record<'linux' | 'windows', string[]> = {
  linux: ['linux', 'linuxsteamrt64'],
  windows: ['windows', 'win64'],
}

const escape = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * The slice of the file that belongs to one key, so a replacement cannot wander.
 *
 * Bounded by the key's own braces, counted. The first attempt stopped at the
 * next quoted key on a line of its own, which cut the window short at the
 * nested "signatures" wrapper every format uses and left the actual values
 * outside it - so nothing was ever replaced.
 */
function keyWindow(text: string, key: string): { from: number; to: number } | null {
  const at = text.indexOf(`"${key}"`)
  if (at < 0) return null
  const open = text.indexOf('{', at + key.length + 2)
  if (open < 0) return null
  let depth = 0
  for (let index = open; index < text.length; index += 1) {
    const character = text[index]
    if (character === '{') depth += 1
    else if (character === '}') {
      depth -= 1
      if (depth === 0) return { from: at, to: index + 1 }
    }
  }
  return { from: at, to: text.length }
}

function replaceInWindow(
  text: string,
  window: { from: number; to: number },
  platform: 'linux' | 'windows',
  oldValue: string | number,
  newValue: unknown,
): { text: string; outcome: 'applied' | 'notFound' | 'ambiguous' } {
  const slice = text.slice(window.from, window.to)
  const names = PLATFORM_NAMES[platform].map(escape).join('|')
  const quoted = typeof oldValue === 'string'
  const body = quoted ? `"${escape(String(oldValue))}"` : `${escape(String(oldValue))}\\b`
  // JSON and JSONC use `"linux": value`; KeyValues uses `"linux"  "value"`.
  const pattern = new RegExp(`("(?:${names})"\\s*(?::\\s*|\\s+))(${body})`, 'g')
  const hits = [...slice.matchAll(pattern)]
  if (hits.length === 0) return { text, outcome: 'notFound' }
  if (hits.length > 1) return { text, outcome: 'ambiguous' }
  const hit = hits[0]!
  const replacement = typeof newValue === 'string' ? `"${newValue}"` : String(newValue)
  const patchedSlice =
    slice.slice(0, hit.index! + hit[1]!.length) +
    replacement +
    slice.slice(hit.index! + hit[1]!.length + hit[2]!.length)
  return { text: text.slice(0, window.from) + patchedSlice + text.slice(window.to), outcome: 'applied' }
}

/**
 * Replace every stale value in `text` with the published one.
 *
 * Only keys the check marked outdated are touched, and only the platform that is
 * actually wrong: a key whose linux value moved keeps its windows value byte for
 * byte, which is the common case and the one a careless rewrite would break.
 */
export function patchFile(text: string, verdicts: KeyVerdict[]): PatchResult {
  let out = text
  let applied = 0
  const skipped: PatchResult['skipped'] = []

  for (const verdict of verdicts) {
    if (verdict.state !== 'outdated' || !verdict.mine || !verdict.expected) continue
    const window = keyWindow(out, verdict.key)
    if (!window) {
      for (const platform of ['linux', 'windows'] as const) {
        const ok = platform === 'linux' ? verdict.linuxOk : verdict.windowsOk
        if (ok === false) skipped.push({ key: verdict.key, platform, reason: 'notFound' })
      }
      continue
    }
    for (const [index, platform] of (['linux', 'windows'] as const).entries()) {
      const ok = platform === 'linux' ? verdict.linuxOk : verdict.windowsOk
      if (ok !== false) continue
      const mine = verdict.mine[platform]
      const theirs = verdict.expected[index]
      if (mine === null || theirs === null || theirs === undefined) continue
      // Re-find the window each time: an earlier replacement shifts offsets.
      const fresh = keyWindow(out, verdict.key)
      if (!fresh) {
        skipped.push({ key: verdict.key, platform, reason: 'notFound' })
        continue
      }
      const result = replaceInWindow(out, fresh, platform, mine, theirs)
      if (result.outcome === 'applied') {
        out = result.text
        applied += 1
      } else {
        skipped.push({ key: verdict.key, platform, reason: result.outcome })
      }
    }
  }
  return { text: out, applied, skipped }
}
