import { valueAtBuild, type SiteHistory } from '../../api/siteData'
import type { PluginFile } from '../gamedata/fileModel'

export interface BuildChange {
  /** Descriptor id of the file the key is in. */
  file: string
  key: string
  platform: 'linux' | 'windows'
  before: unknown
  after: unknown
}

/**
 * Every value in these files that differs between `build` and the build before
 * it, one row per platform.
 *
 * Not the metadata's `updated`: that counts keys whose value differs from the
 * plugin's own template, which is "what this pipeline rewrote", and stays high
 * on a build where nothing moved at all (weaponpaints carried 9 on 14192 while
 * its file last changed in 14190). The history dataset is the only record of
 * build-to-build movement, so "changed in this build" is read from it.
 */
export function buildChanges(history: SiteHistory | undefined, ids: string[], build: string): BuildChange[] {
  if (!history) return []
  const order = history.builds.map((item) => item.gameVersion)
  const previous = order[order.indexOf(build) - 1]
  if (!previous) return []
  const rows: BuildChange[] = []
  for (const id of ids) {
    for (const [key, entry] of Object.entries(history.files[id] ?? {}).sort(([left], [right]) => left.localeCompare(right))) {
      if (!entry.changes.includes(build)) continue
      const before = valueAtBuild(history, id, key, previous)
      const after = valueAtBuild(history, id, key, build)
      ;(['linux', 'windows'] as const).forEach((platform, index) => {
        if (JSON.stringify(before?.[index]) === JSON.stringify(after?.[index])) return
        rows.push({ file: id, key, platform, before: before?.[index], after: after?.[index] })
      })
    }
  }
  return rows
}

/** How many keys of these files moved in `build`. */
export function changedKeyCount(history: SiteHistory | undefined, ids: string[], build: string): number {
  if (!history) return 0
  let count = 0
  for (const id of ids) {
    for (const entry of Object.values(history.files[id] ?? {})) if (entry.changes.includes(build)) count += 1
  }
  return count
}

/**
 * One plugin as a server owner thinks of it: a name and the files it needs.
 *
 * The published index is per file, which is right for the file viewer but not
 * for "is my plugin ready": SwiftlyS2 ships offsets.jsonc and signatures.jsonc,
 * and two rows for one plugin read as two plugins. The numbers here are the sums
 * over its files, so the row says the same thing the files say together.
 */
export interface PluginGroup {
  plugin: string
  files: PluginFile[]
  covered: number
  total: number
  /** Keys that moved in this build; 0 until withBuildChanges fills it from history. */
  updated: number
  gap: number
}

/** Fill each group's `updated` with the keys that moved in `build`, see buildChanges. */
export function withBuildChanges(groups: PluginGroup[], history: SiteHistory | undefined, build: string): PluginGroup[] {
  return groups.map((group) => ({
    ...group,
    updated: changedKeyCount(history, group.files.map((file) => file.descriptor.id), build),
  }))
}

export function groupByPlugin(files: PluginFile[]): PluginGroup[] {
  const groups = new Map<string, PluginGroup>()
  for (const file of files) {
    const plugin = file.descriptor.plugin
    const group = groups.get(plugin) ?? { plugin, files: [], covered: 0, total: 0, updated: 0, gap: 0 }
    group.files.push(file)
    group.covered += file.covered
    group.total += file.total
    group.gap += file.gap
    groups.set(plugin, group)
  }
  return [...groups.values()]
}

/**
 * Starred plugins first, then the ones this build changed (most first), then the
 * rest by name. A server owner runs three or four of these; the order puts what
 * they have to act on at the top without hiding anything.
 */
export function sortPlugins(groups: PluginGroup[], starred: ReadonlySet<string>): PluginGroup[] {
  const rank = (group: PluginGroup) => (starred.has(group.plugin) ? 0 : group.updated > 0 ? 1 : 2)
  return groups.slice().sort((left, right) =>
    rank(left) - rank(right)
    || (rank(left) === 1 ? right.updated - left.updated : 0)
    || left.plugin.localeCompare(right.plugin, undefined, { sensitivity: 'base' }))
}

const STAR_KEY = 'cs2vibe.myPlugins'

/** Per-viewer convenience only: a private window or blocked storage is an empty list. */
export function readStarred(): Set<string> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(STAR_KEY) ?? '[]')
    return new Set(Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [])
  } catch {
    return new Set()
  }
}

export function writeStarred(starred: ReadonlySet<string>): void {
  try {
    localStorage.setItem(STAR_KEY, JSON.stringify([...starred].sort()))
  } catch {
    // remembering is a convenience; a refused write changes nothing on the page
  }
}

/**
 * Where the file lands relative to the plugin's own package.
 *
 * A generator writes its output at the path it has in the plugin's repository,
 * so the descriptor id minus the plugin directory is that path. CounterStrikeSharp
 * keeps its tree under `config/`, which its release unpacks into `game/csgo/` -
 * dropping that prefix gives the path a server owner actually has on disk.
 */
export function installPath(file: PluginFile): string {
  const id = file.descriptor.id
  const inPlugin = id.startsWith(`${file.descriptor.plugin}/`) ? id.slice(file.descriptor.plugin.length + 1) : id
  return inPlugin.replace(/^config\/(?=addons\/)/, '')
}

/**
 * The fixed URL of the newest build's copy of this file, see LATEST_DIRECTORY in
 * gameDataPlugin.ts: latest/<plugin>/<basename>, always the newest published build.
 */
export function latestUrl(file: PluginFile, origin: string, base: string): string {
  const root = `${origin}${base.endsWith('/') ? base : `${base}/`}`
  return `${root}latest/${encodeURIComponent(file.descriptor.plugin)}/${encodeURIComponent(file.descriptor.fileName)}`
}

export function curlCommand(file: PluginFile, origin: string, base: string): string {
  return `curl -fsSL -o ${installPath(file)} ${latestUrl(file, origin, base)}`
}
