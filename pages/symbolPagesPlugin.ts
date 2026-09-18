import { join } from 'node:path'
import type { Plugin } from 'vite'
import type { GameSymbolDataset, GameSymbolRecord } from './gameSymbolsPlugin'

/**
 * One prerendered page per symbol, at /symbols/<key>/.
 *
 * The app is a SPA, so a crawler that does not run JavaScript sees the same
 * empty shell on every URL - which is why pasting a symbol link into a plugin
 * channel produced a preview saying nothing. These shells carry the symbol's
 * name and its actual signature in their meta tags, so the answer is in the
 * unfurl and nobody has to open the tab. The body is the app's own bundle, so a
 * human who clicks still lands on the real page with that symbol selected.
 *
 * No images are generated. Discord, Slack and iMessage all render title and
 * description without one, and 2,000 rendered PNGs would cost more than the
 * preview is worth.
 */

/** Trim to something that survives an unfurl without being cut mid-byte. */
function clamp(text: string, limit: number): string {
  if (text.length <= limit) return text
  return `${text.slice(0, limit - 1).trimEnd()}…`
}

function escapeAttribute(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

interface SymbolSummary {
  key: string
  symbolName: string
  module: string
  linux?: string
  windows?: string
}

/** What a preview should say about one symbol: its byte pattern, or its slot. */
function describe(summary: SymbolSummary): string {
  const parts: string[] = []
  if (summary.linux) parts.push(`linux ${summary.linux}`)
  if (summary.windows) parts.push(`windows ${summary.windows}`)
  if (parts.length === 0) return `${summary.symbolName} in ${summary.module}.`
  return parts.join('  ·  ')
}

function valueOf(record: GameSymbolRecord): string | undefined {
  const payload = record.payload as Record<string, unknown>
  const signature = payload.func_sig ?? payload.vfunc_sig ?? payload.offset_sig
  if (typeof signature === 'string' && signature.length > 0) return signature
  const index = payload.vfunc_index
  if (Number.isInteger(index)) return `slot ${index as number}`
  const offset = payload.offset
  if (typeof offset === 'string' && offset.length > 0) return `offset ${offset}`
  return undefined
}

export function summariseRecords(records: GameSymbolRecord[]): SymbolSummary[] {
  const byKey = new Map<string, SymbolSummary>()
  for (const record of records) {
    const key = `${record.module}/${record.artifact}`
    const summary = byKey.get(key) ?? { key, symbolName: record.symbolName, module: record.module }
    const value = valueOf(record)
    if (record.platform === 'linux') summary.linux = value
    if (record.platform === 'windows') summary.windows = value
    byKey.set(key, summary)
  }
  return [...byKey.values()].sort((left, right) => left.key.localeCompare(right.key))
}

export function renderSymbolShell(shell: string, summary: SymbolSummary, gameVersion: string): string {
  const title = `${summary.symbolName} · CS2 ${gameVersion}`
  const description = clamp(describe(summary), 300)
  const url = `/symbols/${encodeURIComponent(summary.key)}`
  const tags = [
    `<title>${escapeAttribute(title)}</title>`,
    `<meta name="description" content="${escapeAttribute(description)}">`,
    `<meta property="og:type" content="article">`,
    `<meta property="og:title" content="${escapeAttribute(title)}">`,
    `<meta property="og:description" content="${escapeAttribute(description)}">`,
    `<meta property="og:url" content="${escapeAttribute(url)}">`,
    `<meta name="twitter:card" content="summary">`,
    `<meta name="twitter:title" content="${escapeAttribute(title)}">`,
    `<meta name="twitter:description" content="${escapeAttribute(description)}">`,
  ].join('\n    ')
  // Asset URLs in the shell are absolute (base '/'), so a page one level deeper
  // loads exactly the same bundle without rewriting anything.
  return shell.replace(/<title>[\s\S]*?<\/title>/, tags)
}

export function symbolPagesPlugin(): Plugin {
  let outDir = 'dist'
  let root = process.cwd()
  return {
    name: 'symbol-permalink-pages',
    apply: 'build',
    configResolved(config) {
      outDir = config.build.outDir
      root = config.root
    },
    // closeBundle, not generateBundle: the shells are built FROM the published
    // dataset, and that file only exists on disk once the bundle is written.
    // spaFallback copies 404.html at the same point for the same reason.
    async closeBundle() {
      const { readFile: read, writeFile, mkdir } = await import('node:fs/promises')
      const dist = join(root, outDir)
      let index: { versions?: Array<{ gameVersion: string; url: string }> }
      let shell: string
      try {
        index = JSON.parse(await read(join(dist, 'gamesymbols', 'index.json'), 'utf8'))
        shell = await read(join(dist, 'index.html'), 'utf8')
      } catch {
        return
      }
      const newest = index.versions?.[0]
      if (!newest) return

      let dataset: GameSymbolDataset
      try {
        dataset = JSON.parse(await read(join(dist, 'gamesymbols', newest.url), 'utf8')) as GameSymbolDataset
      } catch {
        return
      }

      const summaries = summariseRecords(dataset.records ?? [])
      for (const summary of summaries) {
        // The key holds a slash (module/artifact), so the page is two levels
        // deep; a static host serves index.html for the directory and the
        // router takes it from there.
        const directory = join(dist, 'symbols', ...summary.key.split('/'))
        await mkdir(directory, { recursive: true })
        await writeFile(
          join(directory, 'index.html'),
          renderSymbolShell(shell, summary, dataset.source.gameVersion),
          'utf8',
        )
      }
      this.info?.(`symbol permalinks: ${summaries.length} pages for ${dataset.source.gameVersion}`)
    },
  }
}
