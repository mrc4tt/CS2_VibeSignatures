import { createHash } from 'node:crypto'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildLatestGameData, loadGameDataAssets } from './gameDataPlugin'
import {
  verifyGameDataAssetDirectory,
  verifyLatestGameDataDirectory,
  verifyRemoteGameDataAssets,
  writeGameDataVerificationManifest,
} from './verifyGameDataAssets.mjs'

const temporaryRoots = []

async function temporaryRoot() {
  const root = await mkdtemp(join(tmpdir(), 'gamedata-pages-'))
  temporaryRoots.push(root)
  return root
}

function digest(bytes) {
  return createHash('sha256').update(bytes).digest('hex')
}

async function writeAssets(root) {
  await mkdir(join(root, 'payloads'), { recursive: true })
  await mkdir(join(root, 'metadata'), { recursive: true })
  const payload = Buffer.from('{\n  "Sym": "NEW"\n}\n', 'utf8')
  const payloadUrl = `payloads/${digest(payload)}.jsonc`
  const metadataDocument = {
    schema_version: 2,
    gamever: '14176',
    file: 'Plugin/data.jsonc',
    summary: { total: 1, covered: 1, updated: 1 },
    entries: [{
      name: 'Sym', covered: true, covered_lines: [2], updated: true,
      changes: [{ path: ['Sym'], before: 'OLD', after: 'NEW', line: 2 }],
    }],
  }
  const metadata = Buffer.from(JSON.stringify(metadataDocument), 'utf8')
  const metadataUrl = `metadata/${digest(metadata)}.json`
  const index = {
    schemaVersion: 1,
    versions: [{
      gameVersion: '14176',
      fileCount: 1,
      metadataFileCount: 1,
      files: [{
        id: 'Plugin/data.jsonc', plugin: 'Plugin', fileName: 'data.jsonc', language: 'jsonc',
        content: { url: payloadUrl, sha256: digest(payload), size: payload.byteLength },
        metadata: {
          url: metadataUrl, sha256: digest(metadata), size: metadata.byteLength,
          schemaVersion: 2, summary: metadataDocument.summary,
        },
      }],
    }],
  }
  await writeFile(join(root, ...payloadUrl.split('/')), payload)
  await writeFile(join(root, ...metadataUrl.split('/')), metadata)
  await writeFile(join(root, 'index.json'), JSON.stringify(index))
  return { payload, payloadUrl, metadata, metadataUrl }
}

afterEach(async () => {
  vi.unstubAllGlobals()
  await Promise.all(temporaryRoots.splice(0).map((root) => rm(root, { recursive: true, force: true })))
})

describe('gamedata asset verification', () => {
  it('verifies the exact indexed payload and metadata inventory', async () => {
    const root = await temporaryRoot()
    const assets = await writeAssets(root)

    await expect(verifyGameDataAssetDirectory(root)).resolves.toEqual(expect.objectContaining({
      assets: expect.arrayContaining([expect.objectContaining({ url: assets.payloadUrl }), expect.objectContaining({ url: assets.metadataUrl })]),
    }))
    await writeFile(join(root, ...assets.payloadUrl.split('/')), Buffer.from('tampered', 'utf8'))
    await expect(verifyGameDataAssetDirectory(root)).rejects.toThrow(/size does not match index/)
  })

  it('rejects files that are not declared by the index', async () => {
    const root = await temporaryRoot()
    await writeAssets(root)
    await writeFile(join(root, 'payloads', 'extra.txt'), 'extra', 'utf8')

    await expect(verifyGameDataAssetDirectory(root)).rejects.toThrow(/inventory does not match index/)
  })

  it('waits for the current index and verifies every CDN body', async () => {
    const root = await temporaryRoot()
    await writeAssets(root)
    const staleIndex = Buffer.from('{}', 'utf8')
    const currentIndex = await readFile(join(root, 'index.json'))
    const manifest = await writeGameDataVerificationManifest(root, join(root, 'verification.json'))
    let indexRequests = 0
    vi.stubGlobal('fetch', vi.fn(async (input) => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/index.json')) {
        indexRequests += 1
        return new Response(indexRequests === 1 ? staleIndex : currentIndex)
      }
      const marker = '/gamedata/'
      const relativeUrl = url.pathname.slice(url.pathname.indexOf(marker) + marker.length)
      return new Response(await readFile(join(root, ...relativeUrl.split('/'))))
    }))

    await expect(verifyRemoteGameDataAssets('https://example.test/gamedata/', manifest, {
      attempts: 2,
      delayMs: 0,
      batchSize: 2,
    })).resolves.toEqual(expect.objectContaining({ verified: 2 }))
    expect(indexRequests).toBe(2)
  })

  it('requires latest/ to be the newest build, byte-identical to the source tree', async () => {
    const root = await temporaryRoot()
    const source = join(root, 'source')
    const dist = join(root, 'dist')
    const cssFile = 'CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json'
    const put = async (base, path, text) => {
      await mkdir(dirname(join(base, ...path.split('/'))), { recursive: true })
      await writeFile(join(base, ...path.split('/')), text)
    }
    await put(source, `14178b/${cssFile}`, '{"Sym":"OLD"}\n')
    await put(source, `14180/${cssFile}`, '{"Sym":"NEW"}\n')
    const loaded = await loadGameDataAssets(source)
    for (const asset of loaded.assets.values()) await put(join(dist, 'gamedata'), asset.url, asset.bytes)
    await put(join(dist, 'gamedata'), 'index.json', JSON.stringify(loaded.index))
    const latest = buildLatestGameData(loaded)
    for (const [url, bytes] of latest.files) await put(join(dist, 'latest'), url, bytes)
    await put(join(dist, 'latest'), 'manifest.json', JSON.stringify(latest.manifest))
    const verify = () => verifyLatestGameDataDirectory(join(dist, 'latest'), join(dist, 'gamedata'), source)

    await expect(verify()).resolves.toEqual(expect.objectContaining({ gameVersion: '14180' }))

    // The index still says NEW, but the source file the build was made from
    // changed after the fact: the served copy no longer matches it.
    await put(source, `14180/${cssFile}`, '{"Sym":"NEX"}\n')
    await expect(verify()).rejects.toThrow(/bytes differ from/)
    await put(source, `14180/${cssFile}`, '{"Sym":"NEW"}\n')

    await put(join(dist, 'latest'), 'CounterStrikeSharp/gamedata.json', '{"Sym":"OLD"}\n')
    await expect(verify()).rejects.toThrow(/SHA-256 does not match index/)
    await put(join(dist, 'latest'), 'CounterStrikeSharp/gamedata.json', '{"Sym":"NEW"}\n')

    await put(join(dist, 'latest'), 'Stray/extra.json', '{}\n')
    await expect(verify()).rejects.toThrow(/latest inventory does not match/)
    await rm(join(dist, 'latest', 'Stray'), { recursive: true })

    await put(join(dist, 'latest'), 'manifest.json', JSON.stringify({ ...latest.manifest, gameVersion: '14178b' }))
    await expect(verify()).rejects.toThrow(/is not the newest build 14180/)
  })
})
