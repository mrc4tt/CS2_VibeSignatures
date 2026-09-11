import { requestJson } from '../assets/integrity'

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

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * `latest.json` is the 300-byte answer to "which build is published and how
 * complete is it". The start page reads it instead of the 2 MB snapshot, and a
 * script polling for new builds reads the same document.
 */
export async function getSiteMeta(signal?: AbortSignal): Promise<SiteMeta> {
  const value = await requestJson(`${import.meta.env.BASE_URL}latest.json`, signal)
  if (!isObject(value) || value.schemaVersion !== 1 || !isObject(value.latest) || !Array.isArray(value.builds)) {
    throw new Error('Invalid latest.json; expected schema v1')
  }
  const latest = value.latest
  for (const field of ['gameVersion', 'lastPublishTime', 'configSha256'] as const) {
    if (typeof latest[field] !== 'string' || (latest[field] as string).length === 0) {
      throw new Error(`Invalid latest.${field}`)
    }
  }
  for (const field of ['symbolRecords', 'pluginKeys', 'pluginKeysCovered'] as const) {
    if (!Number.isInteger(latest[field])) throw new Error(`Invalid latest.${field}`)
  }
  return value as unknown as SiteMeta
}
