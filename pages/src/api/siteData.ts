import { requestJson } from '../assets/integrity'

export interface BuildChangeCount {
  gameVersion: string
  keyChanges: number
}

export interface KeyHistory {
  /** [build, linux, windows] at every point the value changed. */
  points: Array<[string, unknown, unknown]>
  changes: string[]
}

export interface SiteHistory {
  schemaVersion: 1
  gameVersion: string
  builds: BuildChangeCount[]
  files: Record<string, Record<string, KeyHistory>>
  keyToSymbol: Record<string, string>
  symbolToKeys: Record<string, Array<[string, string]>>
}

export interface ValidatorWarning {
  platform?: string
  category?: string
  message?: string
}

export interface RunTask {
  module: string
  task: string
  platform: string
  method: string
  produced: number
  missing: number
  optionalMissing: number
  status: string
}

export interface SiteDiagnostics {
  schemaVersion: 1
  gameVersion: string
  validator: {
    ran: boolean
    artifacts?: number
    slotVerified?: number
    errors?: number
    warnings?: number
    bySymbol?: Record<string, ValidatorWarning[]>
    reason?: string
  }
  run: RunTask[]
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Both documents are optional by design: a build published before
 * publish_site_data.py existed simply has none, and every panel that reads them
 * is written to disappear rather than to error.
 */
export async function getSiteHistory(signal?: AbortSignal): Promise<SiteHistory | undefined> {
  try {
    const value = await requestJson(`${import.meta.env.BASE_URL}history.json`, signal)
    if (!isObject(value) || value.schemaVersion !== 1 || !Array.isArray(value.builds) || !isObject(value.files)) {
      return undefined
    }
    return value as unknown as SiteHistory
  } catch {
    return undefined
  }
}

export async function getSiteDiagnostics(build: string, signal?: AbortSignal): Promise<SiteDiagnostics | undefined> {
  if (!/^\d{4,10}[a-z]?$/.test(build)) return undefined
  try {
    const value = await requestJson(`${import.meta.env.BASE_URL}diagnostics/${build}.json`, signal)
    if (!isObject(value) || value.schemaVersion !== 1 || !Array.isArray(value.run) || !isObject(value.validator)) {
      return undefined
    }
    return value as unknown as SiteDiagnostics
  } catch {
    return undefined
  }
}

/** How many of the published builds a key changed in, and when it last moved. */
export function keyFragility(history: SiteHistory | undefined, file: string, key: string): { changes: number; observed: number; last?: string } | undefined {
  const entry = history?.files[file]?.[key]
  if (!entry) return undefined
  return {
    changes: entry.changes.length,
    observed: entry.points.length,
    last: entry.changes[entry.changes.length - 1],
  }
}
