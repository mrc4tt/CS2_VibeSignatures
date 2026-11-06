import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { PLUGIN_CATALOG, pluginsNamed } from './pluginCatalog'

const GENERATORS = resolve(__dirname, '../../../../gamedata-generators')

/** Base names of the files a generator writes: the string literals of its *_PATH / OUTPUT_PATHS lines. */
function outputNames(source: string): string[] {
  const head = source.split('\n').slice(0, 80)
  const names = new Set<string>()
  let inTuple = false
  for (const line of head) {
    if (/^OUTPUT_PATHS\s*=\s*\($/.test(line)) inTuple = true
    else if (inTuple && line.startsWith(')')) inTuple = false
    if (!inTuple && !/^[A-Z_]*PATH[A-Z_]*\s*=/.test(line)) continue
    for (const hit of line.matchAll(/f?"([^"]+\.(?:jsonc?|txt))"/g)) names.add(hit[1]!.split('/').pop()!)
  }
  return [...names]
}

describe('plugin catalog', () => {
  const generators = existsSync(GENERATORS)
    ? readdirSync(GENERATORS, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && existsSync(join(GENERATORS, entry.name, 'gamedata.py')))
      .map((entry) => entry.name)
    : []

  it('has an entry for every generator, and only for generators', () => {
    expect(generators.length).toBeGreaterThan(10)
    expect(Object.keys(PLUGIN_CATALOG).sort()).toEqual([...generators].sort())
  })

  it("lists every file each generator writes", () => {
    for (const plugin of generators) {
      const written = outputNames(readFileSync(join(GENERATORS, plugin, 'gamedata.py'), 'utf8'))
      expect(written.length, plugin).toBeGreaterThan(0)
      expect([...PLUGIN_CATALOG[plugin]!.files].sort(), plugin).toEqual(written.sort())
    }
  })

  it('names plugins by distinctive file names only', () => {
    expect(pluginsNamed('gamebanfix.games.txt')).toEqual(['gamebanfix'])
    expect(pluginsNamed('C:\\server\\addons\\cs2fixes\\gamedata\\CS2Fixes.jsonc')).toEqual(['CS2Fixes'])
    expect(pluginsNamed('matchzy.json').sort()).toEqual(['matchzy', 'matchzy-original'])
    // CounterStrikeSharp and CleanerCS2 both read a gamedata.json
    expect(pluginsNamed('gamedata.json')).toEqual([])
    expect(pluginsNamed('mine.json')).toEqual([])
  })
})
