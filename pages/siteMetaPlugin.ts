import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import type { Plugin } from 'vite'
import { compareGameVersions, sendBytes, sendJson } from './staticAssetPluginUtils'

const SNAPSHOT_FILE_PATTERN = /^(\d{4,10}[a-z]?)\.yaml$/

export interface SiteMetaBuild {
  gameVersion: string
  lastPublishTime: string
  configSha256: string
  symbolRecords: number
  pluginKeys: number
  pluginKeysCovered: number
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

async function metadataSummaries(directory: string): Promise<{ total: number; covered: number }> {
  let total = 0
  let covered = 0
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
        if (Number.isInteger(summary?.total)) total += summary!.total as number
        if (Number.isInteger(summary?.covered)) covered += summary!.covered as number
      } catch {
        // a malformed companion must not fail the build; it is only a counter here
      }
    }
  }
  await walk(directory)
  return { total, covered }
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

export async function buildSiteMeta(symbolsDirectory: string, gamedataDirectory: string): Promise<SiteMeta> {
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
  return {
    schemaVersion: 1,
    latest: {
      gameVersion: header.gameVersion,
      lastPublishTime: header.lastPublishTime,
      configSha256: header.configSha256,
      symbolRecords: header.fileCount,
      pluginKeys: keys.total,
      pluginKeysCovered: keys.covered,
    },
    builds: versions,
    generatedAt: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
  }
}

export function badgesFor(meta: SiteMeta): Map<string, string> {
  const badges = new Map<string, string>()
  const value = `${meta.latest.gameVersion} · ${meta.latest.pluginKeysCovered}/${meta.latest.pluginKeys}`
  badges.set('badge/latest.svg', renderBadge('gamedata', value))
  badges.set(`badge/${meta.latest.gameVersion}.svg`, renderBadge('gamedata', value))
  for (const build of meta.builds) {
    if (build === meta.latest.gameVersion) continue
    badges.set(`badge/${build}.svg`, renderBadge('gamedata', build))
  }
  return badges
}

/**
 * Publishes the two things a script wants without scraping the page: `latest.json`
 * (does a newer build exist?) and `badge/<build>.svg` for a plugin readme.
 */
export function siteMetaPlugin(symbolsDirectory: string, gamedataDirectory: string): Plugin {
  return {
    name: 'site-meta-assets',
    configureServer(server) {
      server.middlewares.use(async (request, response, next) => {
        const pathname = new URL(request.url ?? '/', 'http://localhost').pathname
        try {
          if (pathname.endsWith('/latest.json')) {
            sendJson(response, await buildSiteMeta(symbolsDirectory, gamedataDirectory))
            return
          }
          const badge = /\/badge\/((?:\d{4,10}[a-z]?|latest)\.svg)$/.exec(pathname)
          if (!badge) {
            next()
            return
          }
          const badges = badgesFor(await buildSiteMeta(symbolsDirectory, gamedataDirectory))
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
      const meta = await buildSiteMeta(symbolsDirectory, gamedataDirectory)
      this.emitFile({ type: 'asset', fileName: 'latest.json', source: JSON.stringify(meta) })
      for (const [fileName, svg] of badgesFor(meta)) {
        this.emitFile({ type: 'asset', fileName, source: svg })
      }
    },
  }
}
