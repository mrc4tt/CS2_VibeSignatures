import { platformTone, sortRows, type DeepScanResult, type DeepTone, type Platform } from './deepScan'

/** Closed before any scan; a slim bar after one; half or full height when someone opens it. */
export type SheetSize = 'closed' | 'min' | 'half' | 'full'

const AUTO_OPEN_KEY = 'cs2vibe.scan.autoOpen'

/** Whether the sheet opens by itself after a scan. Only a convenience, so storage that throws reads as "no". */
export function readAutoOpen(): boolean {
  try {
    return localStorage.getItem(AUTO_OPEN_KEY) === '1'
  } catch {
    return false
  }
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
      out.push(line)
    }
  }
  return out.join('\n')
}
