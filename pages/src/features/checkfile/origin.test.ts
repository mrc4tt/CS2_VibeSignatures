import { describe, expect, it } from 'vitest'
import type { SiteHistory } from '../../api/siteData'
import type { GameDataFileDescriptor, GameDataIndex } from '../gamedata/types'
import { detectLayout, fileOrigin, pluginOrigin, publishedCopy, textHashes } from './origin'
import { parseGameData } from './parse'
import { identifyFile } from './verdict'

const CSS_FILE = 'CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json'
const MATCHZY = 'matchzy/gamedata/matchzy.json'
const MAM = 'multiaddonmanager/gamedata/multiaddonmanager.json'
const BANFIX = 'gamebanfix/gamedata/gamebanfix.games.txt'

function descriptor(id: string, sha = '0'.repeat(64)): GameDataFileDescriptor {
  const plugin = id.split('/')[0]!
  const fileName = id.split('/').pop()!
  const language = fileName.endsWith('.txt') ? 'vdf' : 'json'
  return { id, plugin, fileName, language, content: { url: `payloads/${sha}.json`, sha256: sha, size: 1 } }
}

const index = (files: GameDataFileDescriptor[], older: GameDataFileDescriptor[] = []): GameDataIndex => ({
  schemaVersion: 1,
  versions: [
    { gameVersion: '14196', fileCount: files.length, metadataFileCount: 0, files },
    { gameVersion: '14195', fileCount: older.length, metadataFileCount: 0, files: older },
  ],
})

const point = (linux: string, windows: string) => ({ points: [['14196', linux, windows] as [string, string, string]], changes: [] })

const history: SiteHistory = {
  schemaVersion: 1,
  gameVersion: '14196',
  builds: [{ gameVersion: '14196', keyChanges: 0 }],
  files: {
    [CSS_FILE]: { A: point('a', 'a'), B: point('b', 'b'), C: point('c', 'c'), D: point('d', 'd') },
    [MATCHZY]: { JoinTeam: point('j', 'j'), PostCleanUp: point('p', 'p'), SelectItem: point('s', 's') },
    'matchzy-original/gamedata/matchzy.json': { JoinTeam: point('j', 'j') },
    [MAM]: { 'CHostStateMgr::StartNewRequest': point('h', 'h'), 'CNetworkGameServer::ReplyConnection': point('r', 'r') },
    [BANFIX]: { Games: point('g', 'g') },
  },
  keyToSymbol: {},
  symbolToKeys: {},
}

const cssEntry = (linux: string) => ({ signatures: { library: 'server', linux, windows: 'w' } })

function originOf(text: string, name: string, extra: { hashes?: string[]; idx?: GameDataIndex; scanMatch?: string } = {}) {
  const parsed = parseGameData(text)
  return fileOrigin({
    name,
    text,
    format: parsed.format,
    hashes: extra.hashes,
    index: extra.idx ?? index([descriptor(CSS_FILE), descriptor(MATCHZY), descriptor(MAM), descriptor(BANFIX)]),
    historyFiles: Object.keys(history.files),
    identification: identifyFile(parsed.values, history),
    scanMatch: extra.scanMatch,
  })
}

const GAMES_TXT = `// comment first
"Games"
{
\t"csgo"
\t{
\t\t"Signatures"
\t\t{
\t\t\t"Thing"
\t\t\t{
\t\t\t\t"library"\t"server"
\t\t\t\t"windows"\t"\\x48\\x8B"
\t\t\t\t"linux"\t"\\x55\\x48"
\t\t\t}
\t\t}
\t}
}
`

describe('layout', () => {
  it('tells the layouts apart from the text alone', () => {
    const json = (value: unknown) => detectLayout(JSON.stringify(value), 'json')
    expect(json({ A: cssEntry('a'), B: { offsets: { linux: 1, windows: 2 } } })).toBe('cssharp')
    expect(detectLayout(GAMES_TXT, 'vdf')).toBe('games')
    expect(detectLayout('"Gamedata"\n{\n  "A"\n  {\n    "linux" "x"\n  }\n}', 'vdf')).toBe('keyvalues')
    expect(detectLayout('{\n\t"Signatures": {\n\t\t// note\n\t\t"A": { "library": "server", "linux": "55" }\n\t},\n\t"Offsets": {}\n}', 'jsonc')).toBe('cgameconfig')
    expect(json({ Offset: { GameEntitySystem: { windows: 88, linux: 80 } } })).toBe('cgameconfig')
    expect(json({ Addresses: { X: { library: 'tier0', linux: '55' } } })).toBe('modsharp')
    expect(json({ Addresses: {}, Offsets: {}, VFuncs: {} })).toBe('modsharp')
    expect(json({ Addresses: {}, Offsets: {} })).toBe('modsharp')
    // CS2Surf's CS2KZ-style file carries an Addresses block beside Signature / Offset
    expect(json({ Offset: {}, Addresses: {}, Signature: {} })).toBe('cgameconfig')
    expect(json({ $schema: 'https://example/plugify-plugin-s2sdk/schema.json', csgo: { Signatures: {} } })).toBe('plugify')
    expect(json({ 'CEntityInstance::AcceptInput': { lib: 'server', windows: '48', linux: '55' } })).toBe('flat')
    expect(json({ name: 'not gamedata' })).toBeUndefined()
  })
})

describe('whose file', () => {
  it("knows CounterStrikeSharp's own gamedata.json by its keys, and that the fork's updater replaces it", () => {
    const text = JSON.stringify({ A: cssEntry('a'), B: cssEntry('b'), C: cssEntry('c'), D: cssEntry('old') }, null, 2)
    const origin = originOf(text, 'gamedata.json')
    expect(origin).toMatchObject({
      plugin: 'CounterStrikeSharp',
      framework: 'cssharp',
      evidence: 'keys',
      install: 'addons/counterstrikesharp/gamedata/gamedata.json',
      coverage: 'core',
      feeds: [{ plugin: 'CounterStrikeSharp', fileName: 'gamedata.json' }],
      published: CSS_FILE,
    })
  })

  it("says a CounterStrikeSharp plugin's published file gets its signatures patched from the feed", () => {
    const text = JSON.stringify({ JoinTeam: cssEntry('j'), PostCleanUp: cssEntry('p'), SelectItem: cssEntry('s') })
    expect(originOf(text, 'matchzy.json')).toMatchObject({ plugin: 'matchzy', framework: 'cssharp', coverage: 'plugin' })
  })

  it('names a Metamod KeyValues file and says CounterStrikeSharp never updates it', () => {
    const origin = originOf(GAMES_TXT, 'gamebanfix.games.txt')
    expect(origin).toMatchObject({
      plugin: 'gamebanfix',
      framework: 'metamod',
      evidence: 'name',
      layout: 'games',
      install: 'addons/gamebanfix/bin/<platform>/gamedata/gamebanfix.games.txt',
      coverage: 'otherFramework',
      feeds: [{ plugin: 'gamebanfix', fileName: 'gamebanfix.games.txt' }],
    })
  })

  it("names CS2FOW's flat file and says CounterStrikeSharp never updates it", () => {
    const origin = originOf('// CS2FOW\nrecipient_slot_offset_linux=576\nrecipient_slot_offset_windows=576\n', 'cs2fow.games.txt')
    expect(origin).toMatchObject({ plugin: 'CS2FOW', framework: 'metamod', coverage: 'otherFramework' })
  })

  it('a renamed "Games" KeyValues file is still a Metamod file, by its layout', () => {
    expect(originOf(GAMES_TXT, 'mine.txt')).toMatchObject({ plugin: undefined, framework: 'metamod', evidence: 'layout', coverage: 'otherFramework' })
  })

  it("MultiAddonManager's file is in CounterStrikeSharp's layout, but the plugin compiles its signatures in", () => {
    const text = JSON.stringify({
      'CHostStateMgr::StartNewRequest': cssEntry('h'),
      'CNetworkGameServer::ReplyConnection': cssEntry('r'),
    })
    // two keys are too few for the key overlap; the published bytes and the name still say it
    const byName = originOf(text, 'multiaddonmanager.json')
    expect(byName).toMatchObject({ plugin: 'multiaddonmanager', framework: 'metamod', reads: 'source', coverage: 'compiled', published: MAM })
    expect(byName.sourceFile).toBe('src/multiaddonmanager.cpp')
    const renamed = originOf(text, 'mam.json')
    expect(renamed).toMatchObject({ plugin: undefined, framework: 'cssharp', evidence: 'layout', coverage: 'noFeed' })
  })

  it('an exact copy of a published file is named by its bytes, with the build it came from', async () => {
    const text = '{\n  "LogDirect": { "signatures": { "library": "tier0", "linux": "55", "windows": "4C" } }\n}\n'
    const hashes = await textHashes(text)
    expect(hashes).toHaveLength(2)
    const old = descriptor('cleanercs2/addons/cleanercs2/gamedata.json', hashes[0])
    const idx = index([descriptor(CSS_FILE)], [old])
    expect(publishedCopy(hashes, idx)).toEqual({ id: old.id, plugin: 'cleanercs2', build: '14195' })
    // gamedata.json is CounterStrikeSharp's name too, so only the bytes can tell
    expect(originOf(text, 'gamedata.json', { hashes, idx })).toMatchObject({
      plugin: 'cleanercs2',
      framework: 'metamod',
      evidence: 'copy',
      build: '14195',
      install: 'addons/cleanercs2/gamedata.json',
      coverage: 'otherFramework',
      // not in the newest build's index, so latest/ serves nothing for it
      feeds: [],
    })
  })

  it('a JSON file in CS2Fixes-style blocks is a Metamod file; with its name, CS2Fixes', () => {
    const text = '{\n\t"Signatures": {\n\t\t"UTIL_SayTextFilter": { "library": "server", "windows": "48", "linux": "55" }\n\t}\n}'
    expect(originOf(text, 'cs2fixes.jsonc')).toMatchObject({ plugin: 'CS2Fixes', framework: 'metamod', evidence: 'name', coverage: 'otherFramework', feeds: [] })
    expect(originOf(text, 'other.jsonc')).toMatchObject({ plugin: undefined, framework: 'metamod', evidence: 'layout' })
  })

  it('two forks writing one name leave the plugin open but the framework known', () => {
    const text = JSON.stringify({ Unrelated: cssEntry('x') })
    const origin = originOf(text, 'weaponpaints.json')
    expect(origin.plugin).toBeUndefined()
    expect(origin.candidates?.sort()).toEqual(['weaponpaints', 'weaponpaints-nereziel'])
    expect(origin).toMatchObject({ framework: 'cssharp', evidence: 'name', coverage: 'noFeed', published: undefined })
  })

  it('a name the layout contradicts is not taken: CounterStrikeSharp reads no KeyValues', () => {
    expect(originOf(GAMES_TXT, 'matchzy.json')).toMatchObject({ plugin: undefined, framework: 'metamod', evidence: 'layout' })
  })

  it('takes the scan server\'s match when the browser could not name the file', () => {
    const text = JSON.stringify({ Unrelated: cssEntry('x') })
    expect(originOf(text, 'mine.json', { scanMatch: 'TeleportFix' })).toMatchObject({ plugin: 'TeleportFix', evidence: 'keys', framework: 'cssharp' })
  })

  it('says unknown rather than guess', () => {
    const text = JSON.stringify({ Thing: { lib: 'server', linux: '55', windows: '48' } })
    expect(originOf(text, 'thing.json')).toMatchObject({ plugin: undefined, framework: undefined, evidence: undefined, layout: 'flat', coverage: 'unknown', feeds: [] })
  })
})

describe('a published file, for the plugin page', () => {
  const idx = index([descriptor(CSS_FILE), descriptor(MATCHZY), descriptor(MAM), descriptor(BANFIX)])

  it("answers for a CounterStrikeSharp plugin's file without anything to scan", () => {
    expect(pluginOrigin('matchzy', 'matchzy.json', idx)).toMatchObject({
      plugin: 'matchzy', framework: 'cssharp', coverage: 'plugin', install: 'addons/counterstrikesharp/gamedata/matchzy.json',
    })
  })

  it('says a Metamod file is not updated by CounterStrikeSharp', () => {
    expect(pluginOrigin('gamebanfix', 'gamebanfix.games.txt', idx)).toMatchObject({ framework: 'metamod', coverage: 'otherFramework' })
  })

  it('and that MultiAddonManager compiles its values in', () => {
    expect(pluginOrigin('multiaddonmanager', 'multiaddonmanager.json', idx)).toMatchObject({ coverage: 'compiled' })
  })
})
