import { platformTone, sortRows, type DeepScanResult, type DeepTone, type Platform } from './deepScan'

/** Closed before any scan; a slim bar after one; half or full height when someone opens it. */
export type SheetSize = 'closed' | 'min' | 'half' | 'full'

const AUTO_OPEN_KEY = 'cs2vibe.scan.autoOpen'

/**
 * Whether the sheet opens by itself after a scan that found something. On unless
 * someone turned it off: a result that waits in a slim bar at the bottom made
 * people scroll down and press a button to read what they had just asked for.
 */
export function readAutoOpen(): boolean {
  try {
    return localStorage.getItem(AUTO_OPEN_KEY) !== '0'
  } catch {
    return true
  }
}

/** Heights a dragged sheet settles on, as a share of the window, smallest first. */
export const SHEET_STOPS: Array<[SheetSize, number]> = [['min', 0], ['half', 0.62], ['full', 1]]

/**
 * The size a drag ends on: the stop nearest the height the sheet was let go at,
 * or the next one along when it was flicked (moved fast in one direction).
 */
export function settleSheet(height: number, viewport: number, velocity: number): SheetSize {
  const share = Math.max(0, Math.min(1, height / Math.max(1, viewport)))
  const FLICK = 0.5 // px per ms
  if (Math.abs(velocity) > FLICK) {
    const up = velocity < 0
    const index = SHEET_STOPS.findIndex(([, stop]) => (up ? stop > share : stop >= share))
    if (up) return SHEET_STOPS[index < 0 ? SHEET_STOPS.length - 1 : index][0]
    const below = [...SHEET_STOPS].reverse().find(([, stop]) => stop < share)
    return (below ?? SHEET_STOPS[0])[0]
  }
  let best = SHEET_STOPS[0]
  for (const stop of SHEET_STOPS) if (Math.abs(stop[1] - share) < Math.abs(best[1] - share)) best = stop
  return best[0]
}

export function writeAutoOpen(on: boolean): void {
  try {
    localStorage.setItem(AUTO_OPEN_KEY, on ? '1' : '0')
  } catch {
    // a private window keeps the choice for this page only
  }
}

export const PLATFORMS: Platform[] = ['windows', 'linux']
export const PLATFORM_LABEL: Record<Platform, string> = { windows: 'Windows', linux: 'Linux' }
const LOG_SIGN: Record<DeepTone, string> = { ok: '✓', bad: '✗', warn: '!', neutral: '·' }

/** The same result as plain text, one block per entry, for someone who wants the scanner's own words. */
export function scanLog(result: DeepScanResult): string {
  const out: string[] = []
  for (const row of sortRows(result.results)) {
    out.push(`[${row.name}]`)
    for (const platform of PLATFORMS) {
      const info = row.platforms[platform]
      if (!info) continue
      let line = `  ${LOG_SIGN[platformTone(info)]} ${PLATFORM_LABEL[platform]}${row.module ? ` (${row.module})` : ''}: ${info.status}`
      if (info.at) line += ` at ${info.at}`
      if (info.count) line += ` (${info.count} hits)`
      if (info.reference !== undefined) line += `, build has ${info.reference}`
      if (info.vtable && info.vtable !== 'ok') line += `, vtable ${info.vtable}`
      if (info.inferred) line += `, recognised as ${info.inferred.symbol} (${info.inferred.how.split(':')[0]})`
      out.push(line)
    }
  }
  return out.join('\n')
}
