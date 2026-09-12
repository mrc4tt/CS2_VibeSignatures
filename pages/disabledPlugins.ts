import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'

const MODULE_DISABLED = /^MODULE_ENABLED\s*=\s*False\b/m

/**
 * Plugins the pipeline no longer generates, read from the generators themselves.
 *
 * `MODULE_ENABLED = False` is the switch `update_gamedata.py` already honours,
 * so taking the list from there means the site cannot disagree with what the
 * pipeline produces — a hand-kept copy in TypeScript would drift the first time
 * a plugin is switched back on. The directories those plugins left behind under
 * `gamedata/<build>/` stay on disk, because they are history, but nothing the
 * site publishes reads them any more.
 *
 * A missing generator directory yields an empty set, which is what test
 * fixtures and any checkout without the generators should see.
 */
export async function disabledPlugins(generatorRoot: string): Promise<Set<string>> {
  let entries
  try {
    entries = await readdir(generatorRoot, { withFileTypes: true })
  } catch {
    return new Set()
  }
  const disabled = new Set<string>()
  for (const entry of entries) {
    if (!entry.isDirectory()) continue
    let source: string
    try {
      source = await readFile(join(generatorRoot, entry.name, 'gamedata.py'), 'utf8')
    } catch {
      continue
    }
    if (MODULE_DISABLED.test(source)) disabled.add(entry.name)
  }
  return disabled
}
