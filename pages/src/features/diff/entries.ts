import { keyWindow } from '../checkfile/patch'

export interface ChangedEntries {
  /** The entries' blocks, cut verbatim out of the file and separated by a blank line. */
  text: string
  found: string[]
  /** Keys with no block in the file - typically removed in that build. */
  missing: string[]
}

/**
 * The entries for `keys`, exactly as one published file spells them.
 *
 * Cut out of the file rather than rebuilt from the values, so each block comes
 * in the plugin's own format - JSON, CS2Fixes' JSONC with its comments,
 * KeyValues - and can be pasted over the same block in a server's copy. Uses the
 * same brace-counted window as Check my file's patcher, so a block never runs
 * into its neighbour.
 */
export function changedEntries(fileText: string, keys: string[]): ChangedEntries {
  const blocks: string[] = []
  const found: string[] = []
  const missing: string[] = []
  for (const key of keys) {
    const window = keyWindow(fileText, key)
    if (!window) {
      missing.push(key)
      continue
    }
    blocks.push(fileText.slice(window.from, window.to))
    found.push(key)
  }
  return { text: blocks.join('\n\n'), found, missing }
}
