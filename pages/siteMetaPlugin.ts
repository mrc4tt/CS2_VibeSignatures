import { readFile, readdir } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { join, relative } from 'node:path'
import type { Plugin } from 'vite'
import { disabledPlugins } from './disabledPlugins'
import { compareGameVersions, sendBytes, sendJson } from './staticAssetPluginUtils'

const SNAPSHOT_FILE_PATTERN = /^(\d{4,10}[a-z]?)\.yaml$/

export interface SiteMetaBuild {
  gameVersion: string
  lastPublishTime: string
  configSha256: string
  symbolRecords: number
  pluginKeys: number
  pluginKeysCovered: number
  /** Per-plugin key coverage, which is what a per-plugin badge is drawn from. */
  plugins: Record<string, { total: number; covered: number }>
  /**
   * The number Steam calls this build: `ISteamApps/UpToDateCheck`'s `required_version`
   * and `ServerVersion` in a server's `steam.inf`. `gameVersion` adds a letter when one
   * Steam version was analysed twice (`14178b`), so this is what a server is matched on.
   */
  steamVersion: number | null
  /**
   * `deployed` once `deployments/<build>.json` says every plugin repo carries this
   * build's gamedata, `analysed` before that - which is also what a build held by the
   * safe gate stays. Only `deployed` means the files are safe to put on a live server.
   */
  status: 'analysed' | 'deployed' | 'partial'
  /** The deploy record itself, or null while the build is analysed only. */
  deployment: DeploymentRecord | null
}

export interface DeploymentTarget {
  repo?: string | null
  path?: string
  commit?: string
  pushed?: boolean
  error?: string
}

/** Written by `record_deploy.py` after a deploy passes the drift check. */
export interface DeploymentRecord {
  schemaVersion: 1
  gameVersion: string
  status: 'deployed' | 'partial'
  recordedAt: string
  targets: Record<string, DeploymentTarget>
}

export interface SiteMeta {
  schemaVersion: 1
  latest: SiteMetaBuild
  builds: string[]
  generatedAt: string
}

/** Pull the top-level scalars out of a snapshot without parsing its whole `files` map. */
export function readSnapshotHeader(text: string, source: string): {
  gameVersion: string
  lastPublishTime: string
  configSha256: string
  fileCount: number
} {
  const scalar = (key: string): string => {
    const match = new RegExp(`^${key}:[ \\t]*(?:'([^']*)'|"([^"]*)"|([^\\n]*))$`, 'm').exec(text)
    if (!match) throw new Error(`${source}: missing ${key}`)
    return (match[1] ?? match[2] ?? match[3] ?? '').trim()
  }
  const fileCount = Number(scalar('file_count'))
  if (!Number.isInteger(fileCount) || fileCount < 0) throw new Error(`${source}: invalid file_count`)
  return {
    gameVersion: scalar('game_version'),
    lastPublishTime: scalar('last_publish_time'),
    configSha256: scalar('config_sha256'),
    fileCount,
  }
}

async function metadataSummaries(
  directory: string,
): Promise<{ total: number; covered: number; plugins: Record<string, { total: number; covered: number }> }> {
  let total = 0
  let covered = 0
  // Keyed by the directory directly under <build>/, which is the plugin name the
  // badge route and Game Data both already use.
  const plugins: Record<string, { total: number; covered: number }> = {}
  async function walk(path: string): Promise<void> {
    let entries
    try {
      entries = await readdir(path, { withFileTypes: true })
    } catch {
      return
    }
    for (const entry of entries) {
      const next = join(path, entry.name)
      if (entry.isDirectory()) {
        await walk(next)
        continue
      }
      if (!entry.name.endsWith('.metadata.json')) continue
      try {
        const parsed = JSON.parse(await readFile(next, 'utf8')) as { summary?: { total?: unknown; covered?: unknown } }
        const summary = parsed.summary
        const plugin = relative(directory, next).split(/[\\/]/)[0]
        const bucket = plugins[plugin] ?? (plugins[plugin] = { total: 0, covered: 0 })
        if (Number.isInteger(summary?.total)) {
          total += summary!.total as number
          bucket.total += summary!.total as number
        }
        if (Number.isInteger(summary?.covered)) {
          covered += summary!.covered as number
          bucket.covered += summary!.covered as number
        }
      } catch {
        // a malformed companion must not fail the build; it is only a counter here
      }
    }
  }
  await walk(directory)
  return { total, covered, plugins }
}

export function steamVersionOf(gameVersion: string): number | null {
  const match = /^(\d+)[a-z]?$/.exec(gameVersion)
  return match ? Number(match[1]) : null
}

/**
 * A missing record is the normal state of a build that is analysed but not deployed,
 * so it reads as null. A record that is present but unreadable is a broken deploy
 * contract and fails the build instead of quietly reporting "analysed".
 */
export async function readDeploymentRecord(directory: string, gameVersion: string): Promise<DeploymentRecord | null> {
  const path = join(directory, `${gameVersion}.json`)
  if (!existsSync(path)) return null
  const parsed = JSON.parse(await readFile(path, 'utf8')) as Partial<DeploymentRecord>
  if (
    parsed.schemaVersion !== 1
    || parsed.gameVersion !== gameVersion
    || (parsed.status !== 'deployed' && parsed.status !== 'partial')
    || typeof parsed.targets !== 'object'
    || parsed.targets === null
  ) {
    throw new Error(`${path}: expected a deploy record for ${gameVersion} (schema v1)`)
  }
  return parsed as DeploymentRecord
}

/** Shields-compatible flat badge, drawn rather than fetched so the page stays self-contained. */
export function renderBadge(label: string, value: string, color = '#17636e'): string {
  const width = (text: string): number => Math.round(text.length * 6.6) + 14
  const labelWidth = width(label)
  const valueWidth = width(value)
  const escape = (text: string): string =>
    text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${labelWidth + valueWidth}" height="20" role="img"`,
    ` aria-label="${escape(label)}: ${escape(value)}">`,
    `<rect width="${labelWidth}" height="20" rx="3" fill="#3b4350"/>`,
    `<rect x="${labelWidth}" width="${valueWidth}" height="20" rx="3" fill="${color}"/>`,
    `<rect x="${labelWidth}" width="6" height="20" fill="${color}"/>`,
    `<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">`,
    `<text x="7" y="14">${escape(label)}</text>`,
    `<text x="${labelWidth + 7}" y="14">${escape(value)}</text>`,
    `</g></svg>`,
  ].join('')
}

export async function buildSiteMeta(
  symbolsDirectory: string,
  gamedataDirectory: string,
  deploymentsDirectory?: string,
): Promise<SiteMeta> {
  const entries = await readdir(symbolsDirectory, { withFileTypes: true })
  const versions = entries
    .filter((entry) => entry.isFile() && SNAPSHOT_FILE_PATTERN.test(entry.name))
    .map((entry) => SNAPSHOT_FILE_PATTERN.exec(entry.name)![1])
    .sort(compareGameVersions)
  if (versions.length === 0) throw new Error(`${symbolsDirectory}: no snapshots to publish`)
  const latest = versions[0]
  const header = readSnapshotHeader(
    await readFile(join(symbolsDirectory, `${latest}.yaml`), 'utf8'),
    `${latest}.yaml`,
  )
  const keys = await metadataSummaries(join(gamedataDirectory, latest))
  const deployment = deploymentsDirectory ? await readDeploymentRecord(deploymentsDirectory, latest) : null
  return {
    schemaVersion: 1,
    latest: {
      gameVersion: header.gameVersion,
      lastPublishTime: header.lastPublishTime,
      configSha256: header.configSha256,
      symbolRecords: header.fileCount,
      pluginKeys: keys.total,
      pluginKeysCovered: keys.covered,
      plugins: keys.plugins,
      steamVersion: steamVersionOf(header.gameVersion),
      status: deployment ? deployment.status : 'analysed',
      deployment,
    },
    builds: versions,
    generatedAt: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
  }
}

/** Green when this build fills the whole file, amber when a key has no producer. */
const BADGE_OK = '#2f7247'
const BADGE_GAP = '#8a5f10'

export function badgesFor(meta: SiteMeta, disabled: ReadonlySet<string> = new Set()): Map<string, string> {
  const badges = new Map<string, string>()
  const value = `${meta.latest.gameVersion} · ${meta.latest.pluginKeysCovered}/${meta.latest.pluginKeys}`
  badges.set('badge/latest.svg', renderBadge('gamedata', value))
  badges.set(`badge/${meta.latest.gameVersion}.svg`, renderBadge('gamedata', value))
  for (const build of meta.builds) {
    if (build === meta.latest.gameVersion) continue
    badges.set(`badge/${build}.svg`, renderBadge('gamedata', build))
  }
  // One badge per plugin, so a plugin's own README can say whether this build
  // still fills its file without anybody going and looking.
  for (const [plugin, keys] of Object.entries(meta.latest.plugins ?? {})) {
    // A disabled generator's directory survives from older builds and its data
    // is stale on purpose, so a badge over it would be a promise nothing keeps.
    if (disabled.has(plugin)) continue
    const gap = keys.total - keys.covered
    badges.set(
      `badge/plugin/${plugin}.svg`,
      renderBadge(plugin, `${meta.latest.gameVersion} · ${keys.covered}/${keys.total}`, gap === 0 ? BADGE_OK : BADGE_GAP),
    )
  }
  return badges
}

/**
 * The datasets that describe change over time rather than one build, produced by
 * `publish_site_data.py` and committed. They are served from the site root
 * rather than from `gamedata/`, because both asset verifiers require that
 * directory to hold exactly what its index references and nothing else.
 */
async function extraFiles(inputRoot: string): Promise<Map<string, Buffer>> {
  const files = new Map<string, Buffer>()
  const history = join(inputRoot, 'gamedata', 'history.json')
  if (existsSync(history)) files.set('history.json', await readFile(history))
  const deployments = join(inputRoot, 'deployments')
  if (existsSync(deployments)) {
    for (const entry of await readdir(deployments, { withFileTypes: true })) {
      if (!entry.isFile() || !/^\d{4,10}[a-z]?\.json$/.test(entry.name)) continue
      files.set(`deployments/${entry.name}`, await readFile(join(deployments, entry.name)))
    }
  }
  const diagnostics = join(inputRoot, 'diagnostics')
  if (existsSync(diagnostics)) {
    for (const entry of await readdir(diagnostics, { withFileTypes: true })) {
      if (!entry.isFile() || !/^\d{4,10}[a-z]?\.json$/.test(entry.name)) continue
      files.set(`diagnostics/${entry.name}`, await readFile(join(diagnostics, entry.name)))
    }
  }
  return files
}

/**
 * Publishes what a script wants without scraping the page (`latest.json`,
 * `badge/<build>.svg`) plus the committed datasets the site cannot derive from a
 * single snapshot (`history.json`, `diagnostics/<build>.json`,
 * `deployments/<build>.json`).
 */
export function siteMetaPlugin(symbolsDirectory: string, gamedataDirectory: string, inputRoot: string): Plugin {
  return {
    name: 'site-meta-assets',
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        const pathname = new URL(request.url ?? '/', 'http://localhost').pathname
        try {
          if (pathname.endsWith('/latest.json')) {
            sendJson(response, await buildSiteMeta(symbolsDirectory, gamedataDirectory, join(inputRoot, 'deployments')))
            return
          }
          const extra = /\/(history\.json|(?:diagnostics|deployments)\/\d{4,10}[a-z]?\.json)$/.exec(pathname)
          if (extra) {
            const files = await extraFiles(inputRoot)
            const bytes = files.get(extra[1])
            if (!bytes) {
              response.statusCode = 404
              response.end()
              return
            }
            sendBytes(response, bytes)
            return
          }
          const badge = /\/badge\/((?:\d{4,10}[a-z]?|latest)\.svg)$/.exec(pathname)
          if (!badge) {
            next()
            return
          }
          const badges = badgesFor(
            await buildSiteMeta(symbolsDirectory, gamedataDirectory, join(inputRoot, 'deployments')),
            await disabledPlugins(join(inputRoot, 'gamedata-generators')),
          )
          const svg = badges.get(`badge/${badge[1]}`)
          if (!svg) {
            response.statusCode = 404
            response.end()
            return
          }
          sendBytes(response, Buffer.from(svg, 'utf8'), 'image/svg+xml; charset=utf-8')
        } catch (error) {
          next(error instanceof Error ? error : new Error(String(error)))
        }
      })
    },
    async generateBundle() {
      const meta = await buildSiteMeta(symbolsDirectory, gamedataDirectory, join(inputRoot, 'deployments'))
      this.emitFile({ type: 'asset', fileName: 'latest.json', source: JSON.stringify(meta) })
      const disabled = await disabledPlugins(join(inputRoot, 'gamedata-generators'))
      for (const [fileName, svg] of badgesFor(meta, disabled)) {
        this.emitFile({ type: 'asset', fileName, source: svg })
      }
      for (const [fileName, bytes] of await extraFiles(inputRoot)) {
        this.emitFile({ type: 'asset', fileName, source: bytes })
      }
    },
  }
}
