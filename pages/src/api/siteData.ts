import { requestJson } from '../assets/integrity'

export interface BuildChangeCount {
  gameVersion: string
  keyChanges: number
  /** When this build's gamedata first landed. Absent for builds published before
   *  the field existed, so every reader treats it as optional. */
  publishedAt?: string | null
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

/** The value a key held at a given build, reconstructed from its change points. */
export function valueAtBuild(
  history: SiteHistory | undefined,
  file: string,
  key: string,
  build: string,
): [unknown, unknown] | undefined {
  const entry = history?.files[file]?.[key]
  if (!entry) return undefined
  const order = history!.builds.map((item) => item.gameVersion)
  const at = order.indexOf(build)
  if (at < 0) return undefined
  let value: [unknown, unknown] | undefined
  for (const point of entry.points) {
    if (order.indexOf(point[0]) <= at) value = [point[1], point[2]]
  }
  return value
}

export interface KeyDifference {
  key: string
  before?: [unknown, unknown]
  after?: [unknown, unknown]
}

/**
 * Every key in one file whose value differs between an older build and the
 * newest one. This is the question a server owner actually has: not "what
 * changed in the last step" but "I am on build X, what do I have to change".
 */
export function differencesSince(
  history: SiteHistory | undefined,
  file: string,
  build: string,
): KeyDifference[] {
  const entries = history?.files[file]
  if (!entries || !history) return []
  const newest = history.builds[history.builds.length - 1]?.gameVersion
  if (!newest || newest === build) return []
  const out: KeyDifference[] = []
  for (const key of Object.keys(entries).sort()) {
    const before = valueAtBuild(history, file, key, build)
    const after = valueAtBuild(history, file, key, newest)
    if (JSON.stringify(before) === JSON.stringify(after)) continue
    out.push({ key, before, after })
  }
  return out
}

/** The newest build in which anything in this file moved. */
export function lastChangedIn(history: SiteHistory | undefined, file: string): string | undefined {
  const entries = history?.files[file]
  if (!entries || !history) return undefined
  const order = history.builds.map((item) => item.gameVersion)
  let best = -1
  for (const entry of Object.values(entries)) {
    for (const build of entry.changes) {
      const at = order.indexOf(build)
      if (at > best) best = at
    }
  }
  return best >= 0 ? order[best] : undefined
}

export function buildDate(history: SiteHistory | undefined, build?: string): string | undefined {
  if (!build) return undefined
  const entry = history?.builds.find((item) => item.gameVersion === build)
  return entry?.publishedAt ?? undefined
}
