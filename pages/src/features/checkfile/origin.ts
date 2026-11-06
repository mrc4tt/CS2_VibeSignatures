/**
 * Whose file this is: which plugin, which framework loads it, where that plugin reads
 * it, and whether CounterStrikeSharp's gamedata updater will keep it current.
 *
 * The updater question is the one people get wrong. The mrc4tt fork of
 * CounterStrikeSharp replaces its own gamedata.json from latest/ and patches broken
 * signatures in the other files of addons/counterstrikesharp/gamedata/ from their
 * feed, and that is all it touches. A Metamod plugin (CS2Fixes, GameBanFix,
 * MultiAddonManager, ...) reads its own file from its own folder, often KeyValues,
 * and some read no file at all: their signatures are compiled in.
 *
 * Every answer names the evidence it rests on, strongest first: the text is byte for
 * byte a file published here, its keys are one published file's, its name is one only
 * a generator here writes, or only its layout. Where none of those holds, the answer
 * is "not identified", never a guess.
 */

import type { GameDataIndex } from '../gamedata/types'
import { pluginInfo, pluginsNamed, type Framework } from '../gamedata/pluginCatalog'
import { stripJsonc, type GameDataFormat } from './parse'
import type { Identification } from './verdict'

/** How a file is laid out, read from its text alone. */
export type Layout =
  /** `"Name": { "signatures": { "library", "linux", "windows" } }` */
  | 'cssharp'
  /** Valve KeyValues `"Games" { "csgo" { "Signatures" ... } }` */
  | 'games'
  /** KeyValues under another root (cs2-menus' `"Gamedata"`) */
  | 'keyvalues'
  /** JSON with top-level `Signatures` / `Offsets` / `Patches` blocks (CS2Fixes' CGameConfig, CS2KZ's `Signature` / `Offset`) */
  | 'cgameconfig'
  /** JSON with top-level `Addresses` / `VFuncs`, at most `Offsets` beside them (ModSharp) */
  | 'modsharp'
  /** JSON naming the Plugify s2sdk schema */
  | 'plugify'
  /** One object per key with the platform values directly in it (SwiftlyS2) */
  | 'flat'

/**
 * The framework a layout points at when nothing names the plugin; `flat` and other
 * KeyValues say nothing. All but `cssharp` are proof: CleanerCS2, MultiAddonManager
 * and StripperCS2 are Metamod plugins whose files here are in CounterStrikeSharp's
 * layout, so that layout is a fallback, never a reason to reject a plugin.
 */
const LAYOUT_FRAMEWORK: Partial<Record<Layout, Framework>> = {
  cssharp: 'cssharp',
  games: 'metamod',
  cgameconfig: 'metamod',
  modsharp: 'modsharp',
  plugify: 'plugify',
}
const PROVES_FRAMEWORK = new Set<Layout>(['games', 'cgameconfig', 'modsharp', 'plugify'])

const PLATFORM = /^(?:linux|windows|linuxsteamrt64|win64)$/
const KIND_BLOCKS = new Set(['Signatures', 'Signature', 'Offsets', 'Offset', 'Patches'])

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function detectLayout(text: string, format: GameDataFormat): Layout | undefined {
  if (format === 'vdf') {
    const root = /^\uFEFF?\s*(?:\/\/[^\n]*\n\s*)*"([^"]+)"\s*\{/.exec(text)?.[1]
    if (!root) return undefined
    return root.toLowerCase() === 'games' ? 'games' : 'keyvalues'
  }
  let document: unknown
  try {
    document = JSON.parse(format === 'json' ? text.replace(/^\uFEFF/, '') : stripJsonc(text.replace(/^\uFEFF/, '')))
  } catch {
    return undefined
  }
  if (!isObject(document)) return undefined
  if (typeof document.$schema === 'string' && /plugify/i.test(document.$schema)) return 'plugify'
  const blocks = Object.entries(document).filter(([key]) => key !== '$schema')
  if (blocks.length === 0) return undefined
  // ModSharp's files are `Addresses` (+ `Offsets`, `VFuncs`); CS2Surf's CS2KZ-style file
  // has an `Addresses` block too, but beside `Signature` / `Offset`.
  if (isObject(document.VFuncs)) return 'modsharp'
  if (blocks.some(([key, value]) => KIND_BLOCKS.has(key) && isObject(value))) {
    return isObject(document.Addresses) && !blocks.some(([key]) => key !== 'Addresses' && key !== 'Offsets') ? 'modsharp' : 'cgameconfig'
  }
  if (isObject(document.Addresses)) return 'modsharp'
  const entries = blocks.filter(([, value]) => isObject(value)) as Array<[string, Record<string, unknown>]>
  if (entries.length === 0) return undefined
  const cssharp = entries.filter(([, value]) => isObject(value.signatures) || isObject(value.offsets)).length
  if (cssharp / entries.length >= 0.8) return 'cssharp'
  const flat = entries.filter(([, value]) => Object.keys(value).some((key) => PLATFORM.test(key))).length
  if (flat / entries.length >= 0.8) return 'flat'
  return undefined
}

/** What the evidence for the plugin was, strongest first. */
export type Evidence = 'copy' | 'keys' | 'name' | 'layout'

/**
 * Whether CounterStrikeSharp's gamedata updater keeps this file current.
 *
 * - `core`: the fork's updater replaces it from latest/CounterStrikeSharp/gamedata.json.
 * - `plugin`: a CounterStrikeSharp plugin's file with a feed here; the fork's plugin
 *   gamedata update patches its broken signatures, when it sits in the gamedata folder.
 * - `stock`: stock CounterStrikeSharp's own file; stock has no updater for this feed.
 * - `noFeed`: a CounterStrikeSharp file nothing here publishes, so there is nothing to patch it from.
 * - `otherFramework`: not a CounterStrikeSharp file; its updater never reads it.
 * - `compiled`: the plugin reads no file; the values are literals in its source.
 * - `unknown`: the framework is not known, so neither is the answer.
 */
export type Coverage = 'core' | 'plugin' | 'stock' | 'noFeed' | 'otherFramework' | 'compiled' | 'unknown'

export interface Feed {
  plugin: string
  fileName: string
}

export interface Origin {
  /** The generator / published plugin id, when one is identified. */
  plugin?: string
  /** Several plugins fit equally (two forks writing one file name); `plugin` is then unset. */
  candidates?: string[]
  framework?: Framework
  evidence?: Evidence
  layout?: Layout
  /** For `copy`: the build whose published file this is. */
  build?: string
  install?: string
  reads?: 'file' | 'source'
  sourceFile?: string
  coverage: Coverage
  /** The newest build's copies under latest/, for an identified plugin that still publishes. */
  feeds: Feed[]
  /** history.json file id of the published file this one is, when the evidence names one. */
  published?: string
}

/** SHA-256 (hex) of the text as it would be on disk, with and without a BOM; empty without WebCrypto. */
export async function textHashes(text: string): Promise<string[]> {
  const subtle = globalThis.crypto?.subtle
  if (!subtle) return []
  const encoder = new TextEncoder()
  const variants = text.startsWith('\uFEFF') ? [text] : [text, `\uFEFF${text}`]
  const out: string[] = []
  for (const variant of variants) {
    const digest = await subtle.digest('SHA-256', encoder.encode(variant))
    out.push([...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join(''))
  }
  return out
}

/** The published file whose bytes these are, newest build first. */
export function publishedCopy(hashes: string[], index: GameDataIndex | undefined): { id: string; plugin: string; build: string } | undefined {
  if (!index || hashes.length === 0) return undefined
  const wanted = new Set(hashes)
  for (const version of index.versions) {
    const hit = version.files.find((file) => wanted.has(file.content.sha256))
    if (hit) return { id: hit.id, plugin: hit.plugin, build: version.gameVersion }
  }
  return undefined
}

export interface OriginInput {
  name: string
  text: string
  format: GameDataFormat
  /** From textHashes. */
  hashes?: string[]
  index?: GameDataIndex
  /** history.json file ids, to name the published counterpart of a file identified by name. */
  historyFiles?: string[]
  identification?: Identification | null
  /** The plugin the scan server matched the file to (half its keys or more), once a scan ran. */
  scanMatch?: string
}

const baseName = (path: string) => path.split(/[\\/]/).pop() ?? path

export function fileOrigin({ name, text, format, hashes = [], index, historyFiles = [], identification, scanMatch }: OriginInput): Origin {
  const layout = detectLayout(text, format)
  const layoutFramework = layout ? LAYOUT_FRAMEWORK[layout] : undefined
  // A plugin whose framework the layout contradicts is not this file's, whatever else
  // points at it: CounterStrikeSharp never reads KeyValues.
  const proven = layout && PROVES_FRAMEWORK.has(layout) ? layoutFramework : undefined
  const fits = (plugin: string) => {
    const known = pluginInfo(plugin)?.framework
    if (!known) return true
    if (known === 'cssharp' && (format === 'vdf' || format === 'flat')) return false
    return !proven || known === proven
  }

  let plugin: string | undefined
  let evidence: Evidence | undefined
  let build: string | undefined
  let published: string | undefined
  let candidates: string[] | undefined

  const copy = publishedCopy(hashes, index)
  if (copy && fits(copy.plugin)) {
    plugin = copy.plugin
    evidence = 'copy'
    build = copy.build
    published = historyFiles.includes(copy.id) ? copy.id : undefined
  } else if (identification?.decisive && identification.best && fits(identification.best.plugin)) {
    plugin = identification.best.plugin
    evidence = 'keys'
    published = identification.best.file
  } else if (scanMatch && pluginInfo(scanMatch) && fits(scanMatch)) {
    plugin = scanMatch
    evidence = 'keys'
  } else {
    const named = pluginsNamed(name).filter(fits)
    if (named.length > 0) {
      // Two forks writing one name (matchzy, weaponpaints): the keys pick one when
      // they share anything with it; otherwise the framework is still known.
      const byKeys = identification?.ranked.find((match) => match.shared > 0 && named.includes(match.plugin))
      if (named.length === 1 || byKeys) {
        plugin = byKeys?.plugin ?? named[0]
        // Compared with the published file only when they share a key: a name alone
        // must not make a file of unrelated keys read as "up to date".
        published = identification?.ranked.find((match) => match.plugin === plugin && match.shared > 0)?.file
      } else {
        candidates = named
      }
      evidence = 'name'
    }
  }

  const info = pluginInfo(plugin)
  const candidateFrameworks = new Set((candidates ?? []).map((id) => pluginInfo(id)?.framework))
  const framework = info?.framework
    ?? (candidateFrameworks.size === 1 ? [...candidateFrameworks][0] : undefined)
    ?? layoutFramework
  if (!evidence && framework) evidence = 'layout'

  return describe({ plugin, candidates, framework, evidence, layout, build, published, name, index })
}

interface Described {
  plugin?: string
  candidates?: string[]
  framework?: Framework
  evidence?: Evidence
  layout?: Layout
  build?: string
  published?: string
  name: string
  index?: GameDataIndex
}

/** Coverage, install path and feeds once it is settled whose file this is. */
function describe({ plugin, candidates, framework, evidence, layout, build, published, name, index }: Described): Origin {
  const info = pluginInfo(plugin)
  const newest = index?.versions[0]
  const publishing = plugin ? (newest?.files ?? []).filter((file) => file.plugin === plugin) : []
  const sameName = publishing.filter((file) => file.fileName === baseName(name))
  const feeds = (sameName.length ? sameName : publishing).map((file) => ({ plugin: file.plugin, fileName: file.fileName }))

  let coverage: Coverage
  if (!framework) coverage = 'unknown'
  else if (info?.reads === 'source') coverage = 'compiled'
  else if (framework !== 'cssharp') coverage = 'otherFramework'
  else if (info?.core === 'fork') coverage = 'core'
  else if (info?.core === 'stock') coverage = 'stock'
  else if (info && feeds.length > 0 && info.install?.startsWith('addons/counterstrikesharp/gamedata/')) coverage = 'plugin'
  else coverage = 'noFeed'

  return {
    plugin,
    candidates,
    framework,
    evidence,
    layout,
    build,
    install: info?.install,
    reads: info?.reads,
    sourceFile: info?.sourceFile,
    coverage,
    feeds,
    published,
  }
}

/**
 * The same answer for a published file, where the plugin is known up front:
 * the plugin page shows it without anything to scan.
 */
export function pluginOrigin(plugin: string, fileName: string, index?: GameDataIndex): Origin {
  return describe({ plugin, framework: pluginInfo(plugin)?.framework, name: fileName, index })
}
