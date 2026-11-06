/**
 * What each plugin this pipeline generates for runs on, and where it reads its gamedata.
 *
 * Keyed by the generator directory (`gamedata-generators/<id>/`), which is also the
 * plugin id under `gamedata/<build>/` and in index.json. The facts come from each
 * generator's own docstring; pluginCatalog.test.ts fails when a generator directory
 * has no entry here or ships a file name this table does not list, so a new generator
 * cannot reach the site without someone saying what it is.
 *
 * `install` is only set where the generator records where the plugin reads its file
 * on a server (relative to `game/csgo/`). Elsewhere the page says it does not know
 * rather than guess a folder name.
 */

/** The framework a plugin is loaded by. CounterStrikeSharp itself is `cssharp` too. */
export type Framework = 'cssharp' | 'metamod' | 'swiftlys2' | 'modsharp' | 'plugify'

export interface PluginInfo {
  framework: Framework
  /** Base names of the files the generator writes. */
  files: string[]
  /** Where the plugin reads the file on a server, when the generator records it. */
  install?: string
  /**
   * `source`: the plugin reads no gamedata file at all; its signatures are literals in
   * its source and the published file is a reference to paste in and rebuild.
   */
  reads: 'file' | 'source'
  /** Where the literals live, for `reads: 'source'`. */
  sourceFile?: string
  /** CounterStrikeSharp's own gamedata.json (the mrc4tt fork's, or stock). */
  core?: 'fork' | 'stock'
}

const CSS_DIR = 'addons/counterstrikesharp/gamedata/'

export const PLUGIN_CATALOG: Record<string, PluginInfo> = {
  CounterStrikeSharp: { framework: 'cssharp', files: ['gamedata.json'], install: `${CSS_DIR}gamedata.json`, reads: 'file', core: 'fork' },
  'CounterStrikeSharp-roflmuffin': { framework: 'cssharp', files: ['gamedata.json'], install: `${CSS_DIR}gamedata.json`, reads: 'file', core: 'stock' },
  matchzy: { framework: 'cssharp', files: ['matchzy.json'], install: `${CSS_DIR}matchzy.json`, reads: 'file' },
  'matchzy-original': { framework: 'cssharp', files: ['matchzy.json'], install: `${CSS_DIR}matchzy.json`, reads: 'file' },
  weaponpaints: { framework: 'cssharp', files: ['weaponpaints.json'], install: `${CSS_DIR}weaponpaints.json`, reads: 'file' },
  'weaponpaints-nereziel': { framework: 'cssharp', files: ['weaponpaints.json'], install: `${CSS_DIR}weaponpaints.json`, reads: 'file' },
  TeleportFix: { framework: 'cssharp', files: ['TeleportFix.json'], install: `${CSS_DIR}TeleportFix.json`, reads: 'file' },
  'cs2-retakes-allocator': {
    framework: 'cssharp',
    files: ['RetakesAllocator_gamedata.json'],
    install: `${CSS_DIR}RetakesAllocator_gamedata.json`,
    reads: 'file',
  },
  'bot-controller': { framework: 'cssharp', files: ['bot-controller.json'], reads: 'file' },
  'bot-hider': { framework: 'cssharp', files: ['bot-hider.json'], reads: 'file' },
  'css-extras': { framework: 'cssharp', files: ['css-extras.json'], reads: 'file' },

  cleanercs2: { framework: 'metamod', files: ['gamedata.json'], install: 'addons/cleanercs2/gamedata.json', reads: 'file' },
  gamebanfix: {
    framework: 'metamod',
    files: ['gamebanfix.games.txt'],
    install: 'addons/gamebanfix/bin/<platform>/gamedata/gamebanfix.games.txt',
    reads: 'file',
  },
  multiaddonmanager: { framework: 'metamod', files: ['multiaddonmanager.json'], reads: 'source', sourceFile: 'src/multiaddonmanager.cpp' },
  stripper: { framework: 'metamod', files: ['stripper.json'], reads: 'source', sourceFile: 'src/hook.cpp' },
  statusmodifier: { framework: 'metamod', files: ['statusmodifier.jsonc'], reads: 'file' },
  'cs2-menus': { framework: 'metamod', files: ['signatures.txt'], reads: 'file' },
  CS2Fixes: { framework: 'metamod', files: ['cs2fixes.jsonc'], reads: 'file' },
  'cs2kz-metamod': { framework: 'metamod', files: ['cs2kz-core.games.txt'], reads: 'file' },
  cs2surf: { framework: 'metamod', files: ['cs2surf-core.games.jsonc'], reads: 'file' },
  CS2FOW: { framework: 'metamod', files: ['cs2fow.games.txt'], reads: 'file' },

  swiftlys2: { framework: 'swiftlys2', files: ['signatures.jsonc', 'offsets.jsonc'], reads: 'file' },
  'modsharp-public': {
    framework: 'modsharp',
    files: ['core.games.jsonc', 'engine.games.jsonc', 'EntityEnhancement.games.jsonc', 'log.games.jsonc', 'server.games.jsonc', 'tier0.games.jsonc'],
    reads: 'file',
  },
  'plugify-plugin-s2sdk': { framework: 'plugify', files: ['gamedata.jsonc'], reads: 'file' },
}

export function pluginInfo(plugin: string | undefined): PluginInfo | undefined {
  return plugin ? PLUGIN_CATALOG[plugin] : undefined
}

/**
 * File names too generic to say which plugin a file belongs to on their own:
 * CounterStrikeSharp and CleanerCS2 both read a `gamedata.json`.
 */
const GENERIC_NAMES = new Set(['gamedata.json', 'gamedata.jsonc', 'signatures.jsonc', 'offsets.jsonc', 'signatures.txt'])

/** The plugins whose generator writes a file of this (distinctive) name. */
export function pluginsNamed(fileName: string): string[] {
  const name = fileName.split(/[\\/]/).pop()?.toLowerCase() ?? ''
  if (!name || GENERIC_NAMES.has(name)) return []
  return Object.entries(PLUGIN_CATALOG)
    .filter(([, info]) => info.files.some((file) => file.toLowerCase() === name))
    .map(([plugin]) => plugin)
}
