import { requestJson } from '../assets/integrity'

/**
 * What autopilot is doing right now, written by autopilot.sh to
 * diagnostics/status.json when a run starts and when one fails.
 *
 * It exists for one question a server owner has the hour after a CS2 update:
 * "is gamedata for the new build coming, or do I wait for nothing?". The
 * published builds cannot answer it - a run takes hours and publishes only at
 * the end - so this file is the only sign a run has started.
 */
export interface SiteStatus {
  schemaVersion: 1
  /** The newest Steam build autopilot has seen, e.g. "14193". */
  build: string
  state: 'started' | 'failed' | 'done'
  startedAt: string
  updatedAt?: string
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Optional by design: no file, a bad file or a network error all mean "no banner". */
export async function getSiteStatus(signal?: AbortSignal): Promise<SiteStatus | undefined> {
  try {
    const value = await requestJson(`${import.meta.env.BASE_URL}diagnostics/status.json`, signal)
    if (!isObject(value) || value.schemaVersion !== 1) return undefined
    if (typeof value.build !== 'string' || !/^\d{4,10}[a-z]?$/.test(value.build)) return undefined
    if (value.state !== 'started' && value.state !== 'failed' && value.state !== 'done') return undefined
    if (typeof value.startedAt !== 'string' || Number.isNaN(Date.parse(value.startedAt))) return undefined
    return value as unknown as SiteStatus
  } catch {
    return undefined
  }
}

/** Build tags are a number with an optional re-release letter: 14178 < 14178b < 14179. */
export function compareBuilds(left: string, right: string): number {
  const parse = (tag: string): [number, string] => {
    const match = /^(\d+)([a-z]?)$/.exec(tag)
    return match ? [Number(match[1]), match[2]] : [Number.NaN, '']
  }
  const [leftNumber, leftLetter] = parse(left)
  const [rightNumber, rightLetter] = parse(right)
  if (leftNumber !== rightNumber) return leftNumber - rightNumber
  return leftLetter.localeCompare(rightLetter)
}

/** A run older than this is not "on the way" any more; the banner would only mislead. */
const STALE_MS = 3 * 24 * 60 * 60 * 1000

/**
 * The build the banner should announce, or undefined for no banner.
 *
 * Shown only while the seen build is newer than every published one: once the
 * run publishes, the status file may still say "started" (it is not rewritten on
 * success) and that is fine, because the published build has caught up.
 */
export function pendingBuild(
  status: SiteStatus | undefined,
  published: readonly string[],
  now: number = Date.now(),
): { build: string; state: 'started' | 'failed'; startedAt: string } | undefined {
  if (!status || status.state === 'done') return undefined
  if (now - Date.parse(status.startedAt) > STALE_MS) return undefined
  if (published.some((build) => compareBuilds(build, status.build) >= 0)) return undefined
  return { build: status.build, state: status.state, startedAt: status.startedAt }
}
