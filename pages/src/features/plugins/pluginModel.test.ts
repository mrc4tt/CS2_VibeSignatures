import { describe, expect, it } from 'vitest'
import type { SiteHistory } from '../../api/siteData'
import type { PluginFile } from '../gamedata/fileModel'
import { buildChanges, changedKeyCount, curlCommand, groupByPlugin, installPath, latestUrl, sortPlugins } from './pluginModel'

function file(plugin: string, id: string, numbers: Partial<Pick<PluginFile, 'covered' | 'total' | 'updated' | 'gap'>> = {}): PluginFile {
  const fileName = id.split('/').pop()!
  return {
    descriptor: { id, plugin, fileName, language: 'json', content: { url: id, sha256: '', size: 1 } },
    covered: numbers.covered ?? 1,
    total: numbers.total ?? 1,
    updated: numbers.updated ?? 0,
    gap: numbers.gap ?? 0,
    percent: 100,
  }
}

describe('plugin grouping', () => {
  it('shows a plugin with two files as one entry carrying both sets of numbers', () => {
    const groups = groupByPlugin([
      file('swiftlys2', 'swiftlys2/plugin_files/gamedata/cs2/core/offsets.jsonc', { covered: 19, total: 133, updated: 1, gap: 114 }),
      file('swiftlys2', 'swiftlys2/plugin_files/gamedata/cs2/core/signatures.jsonc', { covered: 38, total: 67, updated: 33, gap: 29 }),
      file('bot-hider', 'bot-hider/gamedata/bot-hider.json'),
    ])
    expect(groups).toHaveLength(2)
    const swiftly = groups.find((group) => group.plugin === 'swiftlys2')!
    expect(swiftly.files).toHaveLength(2)
    expect([swiftly.covered, swiftly.total, swiftly.gap]).toEqual([57, 200, 143])
  })

  it('puts starred plugins first, then the ones this build changed, then the rest by name', () => {
    const changed: Record<string, number> = { beta: 2, gamma: 9 }
    const groups = groupByPlugin([
      file('alpha', 'alpha/a.json'),
      file('beta', 'beta/b.json'),
      file('gamma', 'gamma/g.json'),
      file('zeta', 'zeta/z.json'),
    ]).map((group) => ({ ...group, updated: changed[group.plugin] ?? 0 }))
    expect(sortPlugins(groups, new Set(['zeta'])).map((group) => group.plugin)).toEqual(['zeta', 'gamma', 'beta', 'alpha'])
  })
})

describe('what changed in a build', () => {
  const history: SiteHistory = {
    schemaVersion: 1,
    gameVersion: '102',
    builds: [{ gameVersion: '100', keyChanges: 0 }, { gameVersion: '101', keyChanges: 1 }, { gameVersion: '102', keyChanges: 1 }],
    files: {
      'p/a.json': {
        Moved: { points: [['100', 1, 2], ['102', 1, 3]], changes: ['102'] },
        Old: { points: [['100', 5, 5], ['101', 6, 6]], changes: ['101'] },
      },
    },
    keyToSymbol: {},
    symbolToKeys: {},
  }

  it('counts movement between builds from history, one row per platform that moved', () => {
    expect(buildChanges(history, ['p/a.json'], '102')).toEqual([
      { file: 'p/a.json', key: 'Moved', platform: 'windows', before: 2, after: 3 },
    ])
    expect(changedKeyCount(history, ['p/a.json'], '102')).toBe(1)
    expect(changedKeyCount(history, ['p/a.json'], '101')).toBe(1)
    expect(buildChanges(history, ['p/a.json'], '100')).toEqual([])
  })
})

describe('where a file goes and how to fetch it', () => {
  it("maps CounterStrikeSharp's config/ tree onto the install layout", () => {
    const css = file('CounterStrikeSharp', 'CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json')
    expect(installPath(css)).toBe('addons/counterstrikesharp/gamedata/gamedata.json')
    expect(installPath(file('weaponpaints', 'weaponpaints/gamedata/weaponpaints.json'))).toBe('gamedata/weaponpaints.json')
  })

  it('points at the fixed latest/ copy, the same URL every build', () => {
    const css = file('CounterStrikeSharp', 'CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json')
    expect(latestUrl(css, 'https://sig.example', '/')).toBe('https://sig.example/latest/CounterStrikeSharp/gamedata.json')
    expect(curlCommand(css, 'https://sig.example', '/')).toBe(
      'curl -fsSL -o addons/counterstrikesharp/gamedata/gamedata.json https://sig.example/latest/CounterStrikeSharp/gamedata.json',
    )
  })
})
