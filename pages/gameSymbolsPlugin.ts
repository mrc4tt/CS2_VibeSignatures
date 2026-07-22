import { readFile, readdir, stat } from 'node:fs/promises'
import { basename, join } from 'node:path'
import type { Plugin } from 'vite'
import { parse } from 'yaml'

const GAME_VERSION_PATTERN = /^\d{4,10}[a-z]?$/
const SNAPSHOT_FILE_PATTERN = /^(\d{4,10}[a-z]?)\.yaml$/
const SYMBOL_PATH_PATTERN = /^([^/]+)\/([^/]+)\.(windows|linux)\.yaml$/

type JsonObject = Record<string, unknown>

export type GameSymbolPlatform = 'windows' | 'linux'

export interface GameSymbolRecord {
  id: string
  module: string
  artifact: string
  symbolName: string
  platform: GameSymbolPlatform
  kind: string
  payload: JsonObject
}

export interface GameSymbolDataset {
  schemaVersion: 1
  source: {
    gameVersion: string
    snapshotSchemaVersion: number
    configDigestVersion: number
    analysisOutputContractVersion: number
    configSha256: string
    fileCount: number
  }
  modules: Array<{
    name: string
    count: number
    windowsCount: number
    linuxCount: number
  }>
  records: GameSymbolRecord[]
}

export interface GameSymbolIndex {
  schemaVersion: 1
  versions: Array<{
    gameVersion: string
    url: string
    snapshotSchemaVersion: number
    fileCount: number
  }>
}

interface CachedDataset {
  mtimeMs: number
  size: number
  dataset: GameSymbolDataset
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function requiredString(value: unknown, field: string, source: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new Error(`${source}: ${field} must be a non-empty string`)
  return value
}

function requiredInteger(value: unknown, field: string, source: string): number {
  if (!Number.isInteger(value)) throw new Error(`${source}: ${field} must be an integer`)
  return value as number
}

function optionalInteger(value: unknown, fallback: number, field: string, source: string): number {
  if (value === undefined) return fallback
  return requiredInteger(value, field, source)
}

function symbolKind(payload: JsonObject): string {
  if (typeof payload.patch_name === 'string') return 'patch'
  if (typeof payload.vtable_class === 'string') return 'vtable'
  if (typeof payload.struct_name === 'string' && typeof payload.member_name === 'string') return 'structMember'
  if (typeof payload.gv_name === 'string') return 'global'
  if (Number.isInteger(payload.vfunc_index)) return 'virtualFunction'
  if (typeof payload.func_name === 'string') return 'function'
  return 'unknown'
}

function symbolName(payload: JsonObject, artifact: string): string {
  if (typeof payload.func_name === 'string') return payload.func_name
  if (typeof payload.gv_name === 'string') return payload.gv_name
  if (typeof payload.patch_name === 'string') return payload.patch_name
  if (typeof payload.struct_name === 'string' && typeof payload.member_name === 'string') return `${payload.struct_name}.${payload.member_name}`
  if (typeof payload.vtable_class === 'string') return payload.vtable_class
  return artifact
}

export function normalizeGameSymbolSnapshot(raw: unknown, expectedGameVersion: string, source: string): GameSymbolDataset {
  if (!GAME_VERSION_PATTERN.test(expectedGameVersion)) throw new Error(`${source}: invalid game version ${expectedGameVersion}`)
  if (!isObject(raw)) throw new Error(`${source}: snapshot root must be a mapping`)

  const gameVersion = requiredString(raw.game_version, 'game_version', source)
  if (gameVersion !== expectedGameVersion) throw new Error(`${source}: game_version ${gameVersion} does not match filename ${expectedGameVersion}`)

  const files = raw.files
  if (!isObject(files)) throw new Error(`${source}: files must be a mapping`)
  const fileCount = requiredInteger(raw.file_count, 'file_count', source)
  const fileEntries = Object.entries(files)
  if (fileEntries.length !== fileCount) throw new Error(`${source}: file_count ${fileCount} does not match ${fileEntries.length} files`)

  const moduleCounts = new Map<string, { count: number; windowsCount: number; linuxCount: number }>()
  const records = fileEntries.map(([id, payloadValue]) => {
    const pathMatch = SYMBOL_PATH_PATTERN.exec(id)
    if (!pathMatch) throw new Error(`${source}: invalid symbol path ${id}`)
    if (!isObject(payloadValue)) throw new Error(`${source}: ${id} payload must be a mapping`)

    const module = pathMatch[1]
    const artifact = pathMatch[2]
    if (module === '.' || module === '..' || artifact === '.' || artifact === '..' || module.includes('\\') || artifact.includes('\\')) {
      throw new Error(`${source}: invalid symbol path ${id}`)
    }
    const platform = pathMatch[3] as GameSymbolPlatform
    const counts = moduleCounts.get(module) ?? { count: 0, windowsCount: 0, linuxCount: 0 }
    counts.count += 1
    if (platform === 'windows') counts.windowsCount += 1
    else counts.linuxCount += 1
    moduleCounts.set(module, counts)

    return {
      id,
      module,
      artifact,
      symbolName: symbolName(payloadValue, artifact),
      platform,
      kind: symbolKind(payloadValue),
      payload: payloadValue,
    }
  })

  return {
    schemaVersion: 1,
    source: {
      gameVersion,
      snapshotSchemaVersion: requiredInteger(raw.schema_version, 'schema_version', source),
      configDigestVersion: optionalInteger(raw.config_digest_version, 1, 'config_digest_version', source),
      analysisOutputContractVersion: optionalInteger(raw.analysis_output_contract_version, 1, 'analysis_output_contract_version', source),
      configSha256: requiredString(raw.config_sha256, 'config_sha256', source),
      fileCount,
    },
    modules: [...moduleCounts.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([name, counts]) => ({ name, ...counts })),
    records,
  }
}

function compareGameVersions(left: string, right: string): number {
  const leftMatch = /^(\d+)([a-z]?)$/.exec(left)
  const rightMatch = /^(\d+)([a-z]?)$/.exec(right)
  if (!leftMatch || !rightMatch) return right.localeCompare(left)
  const numberDifference = Number(rightMatch[1]) - Number(leftMatch[1])
  if (numberDifference !== 0) return numberDifference
  return rightMatch[2].localeCompare(leftMatch[2])
}

export function createGameSymbolIndex(datasets: GameSymbolDataset[]): GameSymbolIndex {
  return {
    schemaVersion: 1,
    versions: datasets
      .map((dataset) => ({
        gameVersion: dataset.source.gameVersion,
        url: `${dataset.source.gameVersion}.json`,
        snapshotSchemaVersion: dataset.source.snapshotSchemaVersion,
        fileCount: dataset.source.fileCount,
      }))
      .sort((left, right) => compareGameVersions(left.gameVersion, right.gameVersion)),
  }
}

export function gameSymbolsPlugin(symbolsDirectory: string): Plugin {
  const cache = new Map<string, CachedDataset>()

  async function snapshotFiles(): Promise<string[]> {
    const entries = await readdir(symbolsDirectory, { withFileTypes: true })
    return entries
      .filter((entry) => entry.isFile() && SNAPSHOT_FILE_PATTERN.test(entry.name))
      .map((entry) => join(symbolsDirectory, entry.name))
  }

  async function loadDataset(filePath: string): Promise<GameSymbolDataset> {
    const fileStat = await stat(filePath)
    const cached = cache.get(filePath)
    if (cached?.mtimeMs === fileStat.mtimeMs && cached.size === fileStat.size) return cached.dataset

    const fileName = basename(filePath)
    const match = SNAPSHOT_FILE_PATTERN.exec(fileName)
    if (!match) throw new Error(`Invalid gamesymbol snapshot filename: ${fileName}`)
    const raw = parse(await readFile(filePath, 'utf8')) as unknown
    const dataset = normalizeGameSymbolSnapshot(raw, match[1], filePath)
    cache.set(filePath, { mtimeMs: fileStat.mtimeMs, size: fileStat.size, dataset })
    return dataset
  }

  async function loadAll(): Promise<GameSymbolDataset[]> {
    return Promise.all((await snapshotFiles()).map(loadDataset))
  }

  function sendJson(response: import('node:http').ServerResponse, value: unknown): void {
    const body = JSON.stringify(value)
    response.statusCode = 200
    response.setHeader('Content-Type', 'application/json; charset=utf-8')
    response.setHeader('Cache-Control', 'no-cache')
    response.end(body)
  }

  return {
    name: 'gamesymbol-assets',
    configureServer(server) {
      server.watcher.add(symbolsDirectory)
      server.middlewares.use(async (request, response, next) => {
        const pathname = new URL(request.url ?? '/', 'http://localhost').pathname
        if (pathname.endsWith('/gamesymbols/index.json')) {
          try {
            sendJson(response, createGameSymbolIndex(await loadAll()))
          } catch (error) {
            next(error instanceof Error ? error : new Error(String(error)))
          }
          return
        }

        const match = /\/gamesymbols\/(\d{4,10}[a-z]?)\.json$/.exec(pathname)
        if (!match) {
          next()
          return
        }
        try {
          sendJson(response, await loadDataset(join(symbolsDirectory, `${match[1]}.yaml`)))
        } catch (error) {
          next(error instanceof Error ? error : new Error(String(error)))
        }
      })
    },
    async buildStart() {
      const files = await snapshotFiles()
      files.forEach((filePath) => this.addWatchFile(filePath))
    },
    async generateBundle() {
      const files = await snapshotFiles()
      const datasets = await Promise.all(files.map(loadDataset))
      datasets.forEach((dataset) => {
        this.emitFile({
          type: 'asset',
          fileName: `gamesymbols/${dataset.source.gameVersion}.json`,
          source: JSON.stringify(dataset),
        })
      })
      this.emitFile({
        type: 'asset',
        fileName: 'gamesymbols/index.json',
        source: JSON.stringify(createGameSymbolIndex(datasets)),
      })
    },
  }
}
