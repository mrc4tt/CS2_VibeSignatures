/**
 * Which bytes of a signature actually moved.
 *
 * A signature that changed usually changed in two or three bytes - a
 * displacement, a register, a few bytes appended - and printing the old and new
 * lines one above the other hides that behind forty identical ones. This aligns
 * the two token lists on their longest common subsequence, so everything off
 * that subsequence is what was removed (old side) or added (new side).
 */

export interface DiffToken {
  token: string
  changed: boolean
}

export interface TokenDiff {
  before: DiffToken[]
  after: DiffToken[]
}

/** Bytes split into tokens, and what to put back between them when shown. */
export interface ByteTokens {
  tokens: string[]
  separator: string
}

const SPACED = /^[0-9A-Fa-f?]{1,2}(\s+[0-9A-Fa-f?]{1,2})*$/
/** SourceMod/Metamod KeyValues spelling: \x55\x48\x2A, with \x2A as the wildcard. */
const ESCAPED = /^(\\x[0-9A-Fa-f]{2})+$/

/**
 * A value read as bytes - a signature or a patch's replacement bytes, in either
 * spelling plugins use - or undefined when it is something else (an offset, a
 * slot index, a name).
 */
export function byteTokens(value: unknown): ByteTokens | undefined {
  if (typeof value !== 'string') return undefined
  const text = value.trim()
  if (SPACED.test(text)) return { tokens: text.split(/\s+/), separator: ' ' }
  if (ESCAPED.test(text)) return { tokens: text.match(/\\x[0-9A-Fa-f]{2}/g)!, separator: '' }
  return undefined
}

export function isWildcard(token: string): boolean {
  return token === '?' || token === '??' || token.toLowerCase() === '\\x2a'
}

/** `?` and `??` are the same wildcard written two ways; plugins use both. */
function same(left: string, right: string): boolean {
  const norm = (token: string) => (token === '??' ? '?' : token.toUpperCase())
  return norm(left) === norm(right)
}

export function diffTokens(before: string[], after: string[]): TokenDiff {
  const rows = before.length
  const cols = after.length
  // lcs[i][j] = length of the LCS of before[i..] and after[j..]. Signatures
  // are at most a few hundred tokens, so the quadratic table is cheap.
  const lcs: number[][] = Array.from({ length: rows + 1 }, () => new Array<number>(cols + 1).fill(0))
  for (let i = rows - 1; i >= 0; i--) {
    for (let j = cols - 1; j >= 0; j--) {
      lcs[i][j] = same(before[i], after[j]) ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const out: TokenDiff = { before: [], after: [] }
  let i = 0
  let j = 0
  while (i < rows && j < cols) {
    if (same(before[i], after[j])) {
      out.before.push({ token: before[i++], changed: false })
      out.after.push({ token: after[j++], changed: false })
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.before.push({ token: before[i++], changed: true })
    } else {
      out.after.push({ token: after[j++], changed: true })
    }
  }
  while (i < rows) out.before.push({ token: before[i++], changed: true })
  while (j < cols) out.after.push({ token: after[j++], changed: true })
  return out
}
