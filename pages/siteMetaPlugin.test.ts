import { mkdtemp, mkdir, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { badgesFor, buildSiteMeta, readSnapshotHeader, renderBadge } from './siteMetaPlugin'

const SNAPSHOT_HEAD = [
  'analysis_output_contract_version: 1',
  'binaries:',
  '  server:',
  '    linux:',
  '      path: game/csgo/bin/linuxsteamrt64/libserver.so',
  'config_digest_version: 2',
  "config_sha256: 'sha256:abc123'",
  'file_count: 2',
  'files:',
  '  server/ClientPrint.linux.yaml:',
  '    func_name: ClientPrint',
  '  server/ClientPrint.windows.yaml:',
  '    func_name: ClientPrint',
  'game_version: 14181',
  'last_publish_time: 2026-09-11T07:57:31Z',
  'schema_version: 5',
  '',
].join('\n')

async function fixture(): Promise<{ symbols: string; gamedata: string }> {
  const root = await mkdtemp(join(tmpdir(), 'sitemeta-'))
  const symbols = join(root, 'gamesymbols')
  const gamedata = join(root, 'gamedata', '14181', 'CS2Fixes', 'gamedata')
  await mkdir(symbols, { recursive: true })
  await mkdir(gamedata, { recursive: true })
  await writeFile(join(symbols, '14181.yaml'), SNAPSHOT_HEAD, 'utf8')
  await writeFile(join(symbols, '14180.yaml'), SNAPSHOT_HEAD.replace('14181', '14180'), 'utf8')
  await writeFile(
    join(gamedata, 'cs2fixes.jsonc.metadata.json'),
    JSON.stringify({ summary: { total: 75, covered: 74, updated: 38 } }),
    'utf8',
  )
  return { symbols, gamedata: join(root, 'gamedata') }
}

describe('site meta publishing', () => {
  it('reads the snapshot header without parsing the whole files map', () => {
    const header = readSnapshotHeader(SNAPSHOT_HEAD, '14181.yaml')
    expect(header).toEqual({
      gameVersion: '14181',
      lastPublishTime: '2026-09-11T07:57:31Z',
      configSha256: 'sha256:abc123',
      fileCount: 2,
    })
  })

  it('reports a missing header field instead of guessing', () => {
    expect(() => readSnapshotHeader('schema_version: 5\n', 'broken.yaml')).toThrow(/missing file_count/)
  })

  it('summarises the newest build and every published build', async () => {
    const { symbols, gamedata } = await fixture()
    const meta = await buildSiteMeta(symbols, gamedata)
    expect(meta.latest.gameVersion).toBe('14181')
    expect(meta.latest.symbolRecords).toBe(2)
    expect(meta.latest.pluginKeys).toBe(75)
    expect(meta.latest.pluginKeysCovered).toBe(74)
    expect(meta.builds).toEqual(['14181', '14180'])
    expect(meta.generatedAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/)
  })

  it('counts zero keys when a build has no gamedata companions', async () => {
    const { symbols } = await fixture()
    const meta = await buildSiteMeta(symbols, join(symbols, 'does-not-exist'))
    expect(meta.latest.pluginKeys).toBe(0)
    expect(meta.latest.pluginKeysCovered).toBe(0)
  })

  it('draws one badge per build plus a latest alias', async () => {
    const { symbols, gamedata } = await fixture()
    const badges = badgesFor(await buildSiteMeta(symbols, gamedata))
    expect([...badges.keys()].sort()).toEqual(['badge/14180.svg', 'badge/14181.svg', 'badge/latest.svg'])
    expect(badges.get('badge/latest.svg')).toBe(badges.get('badge/14181.svg'))
    expect(badges.get('badge/latest.svg')).toContain('14181 · 74/75')
  })

  it('escapes badge text and stays a single svg element', () => {
    const svg = renderBadge('game<data>', '14181 & 14180')
    expect(svg.startsWith('<svg')).toBe(true)
    expect(svg.endsWith('</svg>')).toBe(true)
    expect(svg).toContain('game&lt;data&gt;')
    expect(svg).toContain('14181 &amp; 14180')
    expect(svg).not.toContain('<script')
  })
})
