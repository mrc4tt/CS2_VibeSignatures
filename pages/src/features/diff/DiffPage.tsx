import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CopyIcon, DownloadIcon, LinkIcon } from 'lucide-react'
import { useEffect, useMemo } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { differencesBetween, getSiteHistory, type FileDifference } from '../../api/siteData'
import { SIDE, ValueChange } from '../../components/ValueChange'
import { copyText } from '../../ui/clipboard'
import { cn } from '../../ui/cn'
import { saveText } from '../../ui/download'
import { Button, Card, ChipSet, Select, Skeleton, Tag } from '../../ui/primitives'
import { getGameDataFile, getGameDataIndex } from '../gamedata/data'
import { changedEntries, type ChangedEntries } from './entries'

/** Which plugins this visitor runs, so the page opens on them next time too. */
const PLUGIN_STORE = 'cs2vibe.diffPlugins'

function storedPlugins(): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(PLUGIN_STORE) ?? '[]')
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}

function storePlugins(plugins: string[]): void {
  try {
    localStorage.setItem(PLUGIN_STORE, JSON.stringify(plugins))
  } catch {
    // Private mode or blocked storage: the filter still works, it is just not remembered.
  }
}

const pluginOf = (file: string): string => file.split('/')[0]
/** The anchor for one key: plugin and key are unique together, and read fine in a URL. */
const anchorOf = (file: string, key: string): string => `${pluginOf(file)}:${key}`

/**
 * Everything that moved between two builds.
 *
 * The site could already say how far behind one file was; it could not answer
 * "I am on 14178b and going to 14181, what do I have to change", which is the
 * question someone who skipped a release actually has. All of it comes out of
 * history.json - nothing new had to be published for this page.
 */
export function DiffPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const historyQuery = useQuery({
    queryKey: ['history'],
    queryFn: ({ signal }) => getSiteHistory(signal),
    staleTime: Infinity,
  })
  const history = historyQuery.data
  const builds = useMemo(() => history?.builds.map((build) => build.gameVersion) ?? [], [history])
  const newest = builds[builds.length - 1]
  const from = params.get('from') ?? builds[builds.length - 2] ?? ''
  const to = params.get('to') ?? newest ?? ''

  const setParam = (key: string, value: string | undefined) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  // The URL wins, so a shared link shows what its sender saw; without one the
  // visitor's own last choice applies. Nothing chosen means every plugin.
  const pluginParam = params.get('plugins')
  const chosen = useMemo(
    () => (pluginParam !== null ? pluginParam.split(',').filter(Boolean) : storedPlugins()),
    [pluginParam],
  )
  const choosePlugins = (next: string[]) => {
    storePlugins(next)
    setParam('plugins', next.length ? next.join(',') : undefined)
  }

  const location = useLocation()
  const target = location.hash ? decodeURIComponent(location.hash.slice(1)) : ''

  const files = useMemo(() => differencesBetween(history, from, to), [history, from, to])
  const plugins = useMemo(
    () => [...new Set(Object.keys(history?.files ?? {}).map(pluginOf))].sort((a, b) => a.localeCompare(b)),
    [history],
  )
  // A linked key stays visible even when its plugin is filtered out here.
  const visible = files.filter(
    (file) => chosen.length === 0 || chosen.includes(pluginOf(file.file)) || target.startsWith(`${pluginOf(file.file)}:`),
  )
  const keyCount = visible.reduce((total, file) => total + file.differences.length, 0)

  // react-router does not scroll to a fragment; do it once the rows exist.
  useEffect(() => {
    if (!target) return
    document.getElementById(target)?.scrollIntoView({ block: 'start' })
  }, [target, files.length])

  const indexQuery = useQuery({
    queryKey: ['gamedata', 'index'],
    queryFn: ({ signal }) => getGameDataIndex(signal),
    staleTime: 5 * 60 * 1000,
  })
  const queryClient = useQueryClient()

  /** The changed keys' blocks, cut out of the `to` build's published file. */
  async function entriesFor(file: FileDifference): Promise<ChangedEntries | undefined> {
    const descriptor = indexQuery.data?.versions.find((version) => version.gameVersion === to)?.files.find((item) => item.id === file.file)
    if (!descriptor) {
      toast.error(t('diff.noFile', { build: to }))
      return undefined
    }
    try {
      const text = await queryClient.fetchQuery({
        queryKey: ['gamedata', 'file', to, descriptor.id],
        queryFn: ({ signal }) => getGameDataFile(descriptor, signal),
        staleTime: Infinity,
      })
      return changedEntries(text, file.differences.map((difference) => difference.key))
    } catch {
      toast.error(t('diff.noFile', { build: to }))
      return undefined
    }
  }

  const entriesMessage = (entries: ChangedEntries) =>
    [
      t('diff.entriesCopied', { count: entries.found.length, build: to }),
      entries.missing.length ? t('diff.entriesMissing', { count: entries.missing.length, build: to }) : '',
    ].filter(Boolean).join(' ')

  async function copyEntries(file: FileDifference) {
    const entries = await entriesFor(file)
    if (entries) await copyText(entries.text, { ok: entriesMessage(entries), failed: t('clipboard.failed') })
  }

  async function downloadEntries(file: FileDifference) {
    const entries = await entriesFor(file)
    if (!entries) return
    const name = file.file.split('/').pop() ?? pluginOf(file.file)
    saveText(entries.text, `${name}.${from}-to-${to}.txt`)
    toast.success(entriesMessage(entries))
  }

  function copyLink(anchor: string) {
    const url = `${window.location.origin}${location.pathname}?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}#${encodeURIComponent(anchor)}`
    void copyText(url, { ok: t('diff.linkCopied'), failed: t('clipboard.failed') })
  }

  return (
    <div className="handbook stack">
      <div className="hero">
        <h1>{t('diff.h1')}</h1>
        <p className="lede">{t('diff.lede')}</p>
      </div>

      {historyQuery.isLoading && <Card><Skeleton rows={5} /></Card>}

      {history && (
        <>
          <Card className="flex flex-wrap items-end gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="diff-from" className="text-[12px] font-medium text-muted-foreground">{t('diff.from')}</label>
              <Select
                id="diff-from"
                className="min-w-[120px] font-mono"
                value={from}
                onChange={(event) => setParam('from', event.target.value)}
              >
                {builds.map((build) => <option key={build} value={build}>{build}</option>)}
              </Select>
            </div>
            <span className="pb-2.5 text-muted-foreground" aria-hidden="true">→</span>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="diff-to" className="text-[12px] font-medium text-muted-foreground">{t('diff.to')}</label>
              <Select
                id="diff-to"
                className="min-w-[120px] font-mono"
                value={to}
                onChange={(event) => setParam('to', event.target.value)}
              >
                {builds.map((build) => <option key={build} value={build}>{build}</option>)}
              </Select>
            </div>
            <span className="ml-auto pb-2.5 text-[13px] text-muted-foreground" role="status" aria-live="polite">
              {t('diff.summary', { keys: keyCount, files: visible.length })}
            </span>
            {from !== to && (
              <div className="flex w-full flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
                <span className={cn('rounded-[5px] px-2 py-0.5 font-mono text-[11px] font-semibold', SIDE.old.row, SIDE.old.label)}>
                  {SIDE.old.sign} {from} {t('diff.old')}
                </span>
                <span className={cn('rounded-[5px] px-2 py-0.5 font-mono text-[11px] font-semibold', SIDE.new.row, SIDE.new.label)}>
                  {SIDE.new.sign} {to} {t('diff.new')}
                </span>
                <span>{t('diff.legend')}</span>
              </div>
            )}
            {plugins.length > 1 && (
              <div className="flex w-full flex-wrap items-center gap-x-3 gap-y-2">
                <span className="text-[12px] font-medium text-muted-foreground">{t('diff.plugins')}</span>
                <ChipSet
                  label={t('diff.plugins')}
                  value={chosen}
                  onValueChange={choosePlugins}
                  items={plugins.map((plugin) => ({
                    value: plugin,
                    label: plugin,
                    count: files.find((file) => pluginOf(file.file) === plugin)?.differences.length ?? 0,
                  }))}
                />
                <span className="text-[12px] text-faint">{chosen.length ? t('diff.pluginsSome') : t('diff.pluginsAll')}</span>
              </div>
            )}
          </Card>

          {visible.length === 0 && (
            <Card><p className="m-0 text-[13px] text-muted-foreground">{t('diff.none', { from, to })}</p></Card>
          )}

          {visible.map((file) => (
            <Card key={file.file} className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <div className="flex items-baseline gap-3">
                  <h2 className="font-mono text-[14px] font-medium text-ink">{pluginOf(file.file)}</h2>
                  <Tag tone="accent">{t('diff.keysMoved', { count: file.differences.length })}</Tag>
                </div>
                {/* The changed entries as the `to` build's file spells them, ready to paste over the old ones. */}
                <div className="flex flex-wrap gap-2">
                  <Button size="small" disabled={!indexQuery.data} onClick={() => void copyEntries(file)}>
                    <CopyIcon className="size-3.5" aria-hidden="true" /> {t('diff.copyEntries')}
                  </Button>
                  <Button size="small" disabled={!indexQuery.data} onClick={() => void downloadEntries(file)}>
                    <DownloadIcon className="size-3.5" aria-hidden="true" /> {t('diff.downloadEntries')}
                  </Button>
                </div>
              </div>
              <div className="flex flex-col divide-y divide-[color:var(--rule-soft)]">
                {file.differences.map((difference) => {
                  const anchor = anchorOf(file.file, difference.key)
                  return (
                    <div
                      key={difference.key}
                      id={anchor}
                      className={cn(
                        'grid scroll-mt-6 items-start gap-x-5 gap-y-2 py-2.5 lg:grid-cols-[minmax(0,260px)_minmax(0,1fr)]',
                        anchor === target && '-mx-2 rounded-[8px] px-2 ring-2 ring-accent-fill',
                      )}
                    >
                      <div className="flex min-w-0 items-start gap-1">
                        <code className="min-w-0 break-all font-mono text-[12.5px] text-ink">{difference.key}</code>
                        <Button
                          variant="text"
                          size="small"
                          className="size-6 shrink-0 p-0 text-muted-foreground"
                          aria-label={t('diff.copyLink', { key: difference.key })}
                          title={t('diff.copyLink', { key: difference.key })}
                          onClick={() => copyLink(anchor)}
                        >
                          <LinkIcon className="size-3.5" aria-hidden="true" />
                        </Button>
                      </div>
                      <div className="flex min-w-0 flex-col gap-2.5">
                        {(['linux', 'windows'] as const).map((platform, index) => {
                          const before = difference.before?.[index]
                          const after = difference.after?.[index]
                          if (JSON.stringify(before) === JSON.stringify(after)) return null
                          return (
                            <div className="flex flex-col gap-1" key={platform}>
                              <span className="text-[10px] uppercase tracking-wide text-faint">{platform}</span>
                              <ValueChange before={before} after={after} beforeLabel={from} afterLabel={to} copyable />
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )
                })}
              </div>
            </Card>
          ))}
        </>
      )}
    </div>
  )
}
