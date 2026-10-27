/**
 * The deep scan: the one part of this page that does leave the browser.
 *
 * The rest of the page compares a file against values published here, which can
 * only say "same as ours" or "different". The service behind sig-api.miksen.me
 * runs verify_plugin_gamedata.py against the actual game binaries, so it can say
 * whether a signature still lands on one function, whether an offset still holds,
 * and propose a replacement only where this build already knows the right value.
 * It is opt-in per file because it means sending the file's text to that server.
 */

export const DEEP_SCAN_API: string = import.meta.env.VITE_VERIFY_API_URL || 'https://sig-api.miksen.me/api'

export type Platform = 'linux' | 'windows'
/** verify_plugin_gamedata's own words for how far a value was confirmed. */
export type Verification = 'verified' | 'contradicted' | 'unverified' | 'upstream'

export interface DeepPlatform {
  status: string
  verification?: Verification
  reference?: number
  value?: number
  at?: string
  count?: number
  vtable?: string
}

export interface DeepRow {
  name: string
  kind?: string
  module?: string
  platforms: Partial<Record<Platform, DeepPlatform>>
}

export interface DeepFix {
  key: string
  platform: Platform
  from: string | number
  to: string | number
  source: 'shipped' | 'record'
}

export interface DeepScanResult {
  build: string
  platforms?: Platform[]
  matched?: { plugin: string; file: string } | null
  unhealthy?: number
  verification?: Record<Verification, number>
  results: DeepRow[]
  fixes?: DeepFix[]
  note?: string
}

/** Why a scan did not come back; each has its own sentence on the page. */
export type DeepScanFailure = 'rateLimited' | 'busy' | 'tooBig' | 'rejected' | 'offline' | 'failed'

export class DeepScanError extends Error {
  reason: DeepScanFailure
  detail?: string

  constructor(reason: DeepScanFailure, detail?: string) {
    super(detail || reason)
    this.name = 'DeepScanError'
    this.reason = reason
    this.detail = detail
  }
}

function failureFor(status: number, retryAfter: string | null): DeepScanFailure {
  if (status === 413) return 'tooBig'
  if (status === 400) return 'rejected'
  // nginx answers 429 for the per-visitor limit; the service answers 429 with
  // Retry-After when its queue is full, which is everyone's problem, not yours.
  if (status === 429) return retryAfter ? 'busy' : 'rateLimited'
  if (status === 503 || status === 504) return 'busy'
  return 'failed'
}

/** What the side panel can narrow a scan to; the service defaults to its newest build and both platforms. */
export interface DeepScanOptions {
  platform?: Platform
  build?: string
  signal?: AbortSignal
  base?: string
}

export async function requestDeepScan(
  text: string,
  filename: string,
  { platform, build, signal, base = DEEP_SCAN_API }: DeepScanOptions = {},
): Promise<DeepScanResult> {
  let response: Response
  try {
    response = await fetch(`${base}/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        gamedata: text,
        filename,
        ...(platform ? { platform } : {}),
        ...(build ? { build } : {}),
      }),
      signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new DeepScanError('offline')
  }
  if (!response.ok) {
    let detail: string | undefined
    try {
      detail = ((await response.json()) as { error?: string }).error
    } catch {
      // nginx's own error pages are not JSON
    }
    throw new DeepScanError(failureFor(response.status, response.headers.get('Retry-After')), detail)
  }
  return (await response.json()) as DeepScanResult
}

/** The builds the service holds binaries for, newest first. Empty when it cannot be reached. */
export async function fetchScanBuilds(signal?: AbortSignal, base: string = DEEP_SCAN_API): Promise<string[]> {
  const response = await fetch(`${base}/builds`, { headers: { Accept: 'application/json' }, signal })
  if (!response.ok) throw new Error(`builds ${response.status}`)
  const body = (await response.json()) as { builds?: unknown }
  return Array.isArray(body.builds) ? body.builds.filter((build): build is string => typeof build === 'string') : []
}

export type DeepTone = 'ok' | 'bad' | 'warn' | 'neutral'

/**
 * One tone per platform verdict, from the pipeline's verification state rather
 * than the raw status: "ok" with a contradicting vtable is still wrong, and a
 * value nothing could judge (no binary, a symbol name) is neither good nor bad.
 */
export function platformTone(info: DeepPlatform | undefined): DeepTone {
  if (!info) return 'neutral'
  switch (info.verification) {
    case 'verified':
      return 'ok'
    case 'contradicted':
      return 'bad'
    case 'unverified':
      return 'warn'
    default:
      return 'neutral'
  }
}

const TONE_RANK: Record<DeepTone, number> = { bad: 0, warn: 1, neutral: 2, ok: 3 }

/** The worst platform decides the row, and the worst rows come first. */
export function rowTone(row: DeepRow): DeepTone {
  const tones = Object.values(row.platforms).map(platformTone)
  return tones.reduce<DeepTone>((worst, tone) => (TONE_RANK[tone] < TONE_RANK[worst] ? tone : worst), 'ok')
}

export function sortRows(rows: DeepRow[]): DeepRow[] {
  return [...rows].sort((a, b) => TONE_RANK[rowTone(a)] - TONE_RANK[rowTone(b)] || a.name.localeCompare(b.name))
}
