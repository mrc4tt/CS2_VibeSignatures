import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { getSiteHistory } from '../../api/siteData'
import { parseGameData, type FileValue, type GameDataFormat } from './parse'
import { patchFile } from './patch'
import { bestFit, identifyFile, keyVerdicts, scoreBuilds, summarise } from './verdict'

export interface Loaded {
  name: string
  format: GameDataFormat
  /** Kept so the fixed file can be produced from the original bytes. */
  text: string
  values: Map<string, FileValue>
  /** Set when the page filled itself with a published file, so it can say so. */
  example?: { plugin: string; build: string }
}

/** Why a text could not be taken; the page words each one itself. */
export type ReadFailure = { reason: 'unreadable' } | { reason: 'noEntries'; format: GameDataFormat }

/**
 * A dropped or pasted text as this page can use it, or why it cannot.
 *
 * A file with no platform entries is readable and still useless here, and it is
 * the likeliest mistake - a README, the wrong file from the plugin folder. The
 * KeyValues reader never throws, so the empty map is the only way that shows up.
 */
export function readGameData(text: string, name: string): Loaded | ReadFailure {
  if (!text.trim()) return { reason: 'unreadable' }
  try {
    const parsed = parseGameData(text)
    if (parsed.values.size === 0) return { reason: 'noEntries', format: parsed.format }
    return { name, format: parsed.format, text, values: parsed.values }
  } catch {
    return { reason: 'unreadable' }
  }
}

export function isLoaded(value: Loaded | ReadFailure): value is Loaded {
  return !('reason' in value)
}

/**
 * The browser check both pages run on a loaded file: which plugin it belongs
 * to, which build it fits, and every key's state against the newest build.
 * Nothing in here leaves the browser.
 */
export function useFileCheck(loaded: Loaded | null) {
  const { data: history, isLoading } = useQuery({ queryKey: ['site-history'], queryFn: ({ signal }) => getSiteHistory(signal) })
  const [chosenFile, setChosenFile] = useState<string | null>(null)

  const newest = history?.builds[history.builds.length - 1]?.gameVersion
  const identification = useMemo(
    () => (loaded ? identifyFile(loaded.values, history) : null),
    [loaded, history],
  )
  const file = chosenFile ?? (identification?.decisive ? identification.best?.file : undefined)
  const scores = useMemo(
    () => (loaded && file ? scoreBuilds(loaded.values, history, file) : []),
    [loaded, history, file],
  )
  const fit = useMemo(() => bestFit(scores), [scores])
  const verdicts = useMemo(
    () => (loaded && file && newest ? keyVerdicts(loaded.values, history, file, newest) : []),
    [loaded, history, file, newest],
  )
  const summary = useMemo(() => summarise(verdicts), [verdicts])
  const patched = useMemo(
    () => (loaded && summary.outdated > 0 ? patchFile(loaded.text, verdicts) : null),
    [loaded, verdicts, summary.outdated],
  )
  const behind = fit && newest && fit.build !== newest && history
    ? history.builds.length - 1 - history.builds.findIndex((entry) => entry.gameVersion === fit.build)
    : 0

  return { history, isLoading, newest, identification, chosenFile, setChosenFile, file, fit, verdicts, summary, patched, behind }
}
