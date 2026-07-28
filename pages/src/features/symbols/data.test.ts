import { createHash, webcrypto } from 'node:crypto'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getGameSymbolDataset, getGameSymbolIndex } from './data'
import type { GameSymbolDataset, GameSymbolIndexVersion } from './types'

const dataset: GameSymbolDataset = {
  schemaVersion: 2,
  source: {
    gameVersion: '14172',
    snapshotSchemaVersion: 4,
    configDigestVersion: 2,
    analysisOutputContractVersion: 1,
    configSha256: 'sha256:test',
    fileCount: 0,
    lastPublishTime: '2026-07-27T04:42:43Z',
  },
  binaries: {},
  modules: [],
  records: [],
}

function encodedDataset(): { bytes: Uint8Array; version: GameSymbolIndexVersion } {
  const bytes = Buffer.from(JSON.stringify(dataset), 'utf8')
  const sha256 = createHash('sha256').update(bytes).digest('hex')
  return {
    bytes,
    version: {
      gameVersion: '14172',
      url: `14172.${sha256}.json`,
      sha256,
      size: bytes.byteLength,
      snapshotSchemaVersion: 4,
      fileCount: 0,
      lastPublishTime: '2026-07-27T04:42:43Z',
    },
  }
}

describe('game-symbol asset loading', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', webcrypto)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('accepts index schema v3 only when URL, SHA-256, and size metadata are valid', async () => {
    const { version } = encodedDataset()
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ schemaVersion: 3, versions: [version] }), {
      headers: { 'Content-Type': 'application/json' },
    })))

    await expect(getGameSymbolIndex()).resolves.toEqual({ schemaVersion: 3, versions: [version] })
  })

  it('rejects an index URL that does not strictly match the content-addressed filename', async () => {
    const { version } = encodedDataset()
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      schemaVersion: 3,
      versions: [{ ...version, url: '14172.json' }],
    }))))

    await expect(getGameSymbolIndex()).rejects.toThrow(/content-addressed url/)
  })

  it('verifies the response body bytes before parsing the snapshot JSON', async () => {
    const { bytes, version } = encodedDataset()
    const fetchMock = vi.fn(async () => new Response(bytes))
    vi.stubGlobal('fetch', fetchMock)

    await expect(getGameSymbolDataset(version)).resolves.toEqual(dataset)
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining(`/gamesymbols/${version.url}`), { signal: undefined })
  })

  it('rejects size and SHA-256 mismatches without parsing altered JSON', async () => {
    const { bytes, version } = encodedDataset()
    vi.stubGlobal('fetch', vi.fn(async () => new Response(bytes)))

    await expect(getGameSymbolDataset({ ...version, size: version.size + 1 })).rejects.toThrow(/size mismatch/)
    await expect(getGameSymbolDataset({
      ...version,
      url: `14172.${'0'.repeat(64)}.json`,
      sha256: '0'.repeat(64),
    })).rejects.toThrow(/SHA-256 mismatch/)
  })
})
