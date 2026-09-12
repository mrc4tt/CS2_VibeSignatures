/**
 * What a dropped gamedata file actually is, and whether it is current.
 *
 * Everything here reads the published history, so it runs in the browser with
 * no upload: the file never leaves the machine it was dropped on.
 *
 * The useful answer is not "outdated" but WHICH build the file is. history.json
 * holds every key's value at every build, so scoring the file against each
 * build in turn says "this is 14178b, three builds behind" instead of leaving
 * someone to guess.
 */

import { valueAtBuild, type SiteHistory } from '../../api/siteData'
import type { FileValue } from './parse'

export interface FileMatch {
  file: string
  plugin: string
  shared: number
  ofMine: number
  ofTheirs: number
}

export interface Identification {
  best?: FileMatch
  second?: FileMatch
  /** True when one candidate is far enough ahead to name it without asking. */
  decisive: boolean
  ranked: FileMatch[]
}

const pluginOf = (file: string): string => file.split('/')[0] ?? file

/**
 * Which published file this is, by key overlap.
 *
 * Plugins share key names — CS2Fixes and CounterStrikeSharp both ship
 * CBaseModelEntity_SetModel — so a narrow win is genuinely ambiguous and the
 * caller is told rather than given a guess.
 */
export function identifyFile(values: Map<string, FileValue>, history: SiteHistory | undefined): Identification {
  const ranked: FileMatch[] = []
  if (!history || values.size === 0) return { decisive: false, ranked }
  for (const [file, keys] of Object.entries(history.files)) {
    const theirs = Object.keys(keys)
    if (theirs.length === 0) continue
    let shared = 0
    for (const key of theirs) if (values.has(key)) shared += 1
    ranked.push({
      file,
      plugin: pluginOf(file),
      shared,
      ofMine: shared / values.size,
      ofTheirs: shared / theirs.length,
    })
  }
  ranked.sort((left, right) => right.shared - left.shared || right.ofTheirs - left.ofTheirs)
  const [best, second] = ranked
  const decisive = Boolean(
    best &&
      best.shared >= 3 &&
      best.ofMine >= 0.5 &&
      (!second || best.shared >= second.shared * 1.5 || best.shared - second.shared >= 5),
  )
  return { best, second, decisive, ranked }
}

const same = (mine: string | number | null, theirs: unknown): boolean => {
  if (mine === null || theirs === null || theirs === undefined) return false
  return String(mine).trim() === String(theirs).trim()
}

export interface BuildScore {
  build: string
  matched: number
  comparable: number
  share: number
}

/**
 * How well the file matches each published build, newest first.
 *
 * Only keys the file and the build both carry count, so a file holding a subset
 * of the keys is not punished for what it never shipped.
 */
export function scoreBuilds(
  values: Map<string, FileValue>,
  history: SiteHistory | undefined,
  file: string,
): BuildScore[] {
  if (!history?.files[file]) return []
  const keys = Object.keys(history.files[file]!)
  const scores: BuildScore[] = []
  for (const { gameVersion } of history.builds) {
    let matched = 0
    let comparable = 0
    for (const key of keys) {
      const mine = values.get(key)
      if (!mine) continue
      const theirs = valueAtBuild(history, file, key, gameVersion)
      if (!theirs) continue
      const bothSides = [same(mine.linux, theirs[0]), same(mine.windows, theirs[1])]
      const present = [mine.linux !== null && theirs[0] != null, mine.windows !== null && theirs[1] != null]
      if (!present[0] && !present[1]) continue
      comparable += 1
      if (present.every((has, index) => !has || bothSides[index])) matched += 1
    }
    scores.push({ build: gameVersion, matched, comparable, share: comparable ? matched / comparable : 0 })
  }
  return scores.reverse()
}

export type KeyState = 'current' | 'outdated' | 'unknown' | 'absent'

export interface KeyVerdict {
  key: string
  state: KeyState
  mine?: FileValue
  expected?: [unknown, unknown]
}

/** Per-key verdict against one build: what to change, and what is fine. */
export function keyVerdicts(
  values: Map<string, FileValue>,
  history: SiteHistory | undefined,
  file: string,
  build: string,
): KeyVerdict[] {
  const entries = history?.files[file]
  if (!entries) return []
  const out: KeyVerdict[] = []
  for (const key of Object.keys(entries).sort()) {
    const mine = values.get(key)
    const expected = valueAtBuild(history, file, key, build)
    if (!mine) {
      out.push({ key, state: 'absent', expected })
      continue
    }
    if (!expected) {
      out.push({ key, state: 'unknown', mine })
      continue
    }
    const linuxOk = mine.linux === null || expected[0] == null || same(mine.linux, expected[0])
    const windowsOk = mine.windows === null || expected[1] == null || same(mine.windows, expected[1])
    out.push({ key, state: linuxOk && windowsOk ? 'current' : 'outdated', mine, expected })
  }
  for (const key of [...values.keys()].sort()) {
    if (!(key in entries)) out.push({ key, state: 'unknown', mine: values.get(key) })
  }
  return out
}

export interface CheckSummary {
  current: number
  outdated: number
  unknown: number
  absent: number
}

export function summarise(verdicts: KeyVerdict[]): CheckSummary {
  const summary: CheckSummary = { current: 0, outdated: 0, unknown: 0, absent: 0 }
  for (const verdict of verdicts) summary[verdict.state] += 1
  return summary
}

export interface BestFit {
  /** Newest build the file fits, and the oldest one it fits equally well. */
  build: string
  oldest: string
  share: number
  matched: number
  comparable: number
  /** True when several builds fit identically, so the file cannot be pinned. */
  tied: boolean
}

/**
 * The build a file is, out of the builds it could be.
 *
 * Several builds often fit identically, because a plugin's keys do not change
 * in every game update: measured on the published history, NO CS2Fixes key
 * differs between 14178b and 14180, so a file from either is indistinguishable.
 * The newest fitting build is the answer - claiming the oldest would call a file
 * more out of date than the evidence supports - and the range is reported so the
 * tie is visible rather than hidden.
 */
export function bestFit(scores: BuildScore[]): BestFit | undefined {
  if (scores.length === 0) return undefined
  // Scores arrive newest first. Among builds that fit equally well, the one
  // that could compare MORE of the file is the better explanation: a key that
  // did not exist yet in an older build is not evidence for that build, it is
  // just absence. Without this, a file is reported as older than it is whenever
  // a key was added recently.
  const top = scores.reduce((left, right) =>
    right.share > left.share || (right.share === left.share && right.comparable > left.comparable) ? right : left,
  )
  const tiedRun = scores.filter((score) => score.share === top.share && score.comparable === top.comparable)
  return {
    build: tiedRun[0]!.build,
    oldest: tiedRun[tiedRun.length - 1]!.build,
    share: top.share,
    matched: top.matched,
    comparable: top.comparable,
    tied: tiedRun.length > 1,
  }
}
