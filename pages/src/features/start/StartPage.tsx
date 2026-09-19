import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getSiteMeta } from '../../api/siteMeta'
import { getSiteHistory } from '../../api/siteData'
import { formatAgo, formatWhen } from '../../components/whenText'
import { Explain } from '../../components/Explain'
import { VIEW_PATHS, type AppView } from '../../app/appViews'
import { getGameDataIndex } from '../gamedata/data'
import { describeFiles } from '../gamedata/fileModel'
import { Card, Dot, Progress, Skeleton, Tag } from '../../ui/primitives'

const SEEN_KEY = 'cs2vibe.seenBuild'

function readSeen(): string | null {
  try {
    return localStorage.getItem(SEEN_KEY)
  } catch {
    return null
  }
}

export function StartPage({ onGo }: { onGo(view: AppView): void }) {
  const { t, i18n } = useTranslation()
  const [seen] = useState(readSeen)
  const [dismissed, setDismissed] = useState(false)
  const language = i18n.resolvedLanguage ?? 'en'
  const metaQuery = useQuery({
    queryKey: ['site-meta'],
    queryFn: ({ signal }) => getSiteMeta(signal),
    staleTime: 5 * 60 * 1000,
  })
  const historyQuery = useQuery({
    queryKey: ['history'],
    queryFn: ({ signal }) => getSiteHistory(signal),
    staleTime: Infinity,
  })
  // The shipped-files panel reads the same index Game Data does, so the two can
  // never disagree about how much of a plugin's file this build filled in.
  const indexQuery = useQuery({
    queryKey: ['gamedata', 'index'],
    queryFn: ({ signal }) => getGameDataIndex(signal),
    staleTime: 5 * 60 * 1000,
  })
  const meta = metaQuery.data
  const history = historyQuery.data

  const files = useMemo(() => {
    const version = indexQuery.data?.versions.find((entry) => entry.gameVersion === meta?.latest.gameVersion)
      ?? indexQuery.data?.versions[0]
    return describeFiles(version?.files ?? [])
  }, [indexQuery.data, meta])

  const sinceLastVisit = useMemo(() => {
    if (!meta || !history) return undefined
    const order = history.builds.map((build) => build.gameVersion)
    const at = seen ? order.indexOf(seen) : -1
    if (!seen || at < 0) return { first: true, builds: 0, keys: 0 }
    if (seen === meta.latest.gameVersion) return undefined
    const newer = history.builds.slice(at + 1)
    return { first: false, builds: newer.length, keys: newer.reduce((total, build) => total + build.keyChanges, 0) }
  }, [meta, history, seen])

  function markSeen(): void {
    setDismissed(true)
    try {
      if (meta) localStorage.setItem(SEEN_KEY, meta.latest.gameVersion)
    } catch {
      // a private window is not a reason to fail a click
    }
  }

  const tasks: Array<{ view: AppView; q: string; d: string }> = [
    { view: 'symbols', q: t('start.t1q'), d: t('start.t1d') },
    { view: 'gamedata', q: t('start.t2q'), d: t('start.t2d') },
    { view: 'gamedata', q: t('start.t3q'), d: t('start.t3d') },
    { view: 'words', q: t('start.t4q'), d: t('start.t4d') },
  ]
  const gap = meta ? meta.latest.pluginKeys - meta.latest.pluginKeysCovered : 0
  const changedThisBuild = files.reduce((total, file) => total + file.updated, 0)
  const complete = files.filter((file) => file.gap === 0).length

  return (
    <div className="handbook stack">
      {sinceLastVisit && !dismissed && (
        <p className="visit">
          <span>
            {sinceLastVisit.first
              ? t('start.firstVisit', { build: meta?.latest.gameVersion ?? '' })
              : t('start.sinceLast', { builds: sinceLastVisit.builds, keys: sinceLastVisit.keys })}
          </span>
          <button type="button" onClick={markSeen} aria-label={t('start.dismiss')}>×</button>
        </p>
      )}
      {/* Build header: what this page is about, stated once, at the top. */}
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div className="flex min-w-0 flex-col gap-2">
          <div className="flex items-center gap-3">
            <span className="font-mono text-[28px] font-semibold tracking-tight text-ink">{meta?.latest.gameVersion ?? '…'}</span>
            <Tag tone="ok">{t('start.currentBadge')}</Tag>
          </div>
          {meta && (
            <p className="m-0 text-[13px] text-muted-foreground">
              {t('start.read')} <b className="font-medium text-ink-2">{formatWhen(meta.latest.lastPublishTime, language)}</b>
              {' · '}{formatAgo(meta.latest.lastPublishTime, language)}
              {' · '}{t('start.fingerprint')}{' '}
              <b className="font-mono font-medium text-ink-2">{meta.latest.configSha256.replace(/^sha256:/, '').slice(0, 8)}</b>
            </p>
          )}
        </div>
        <Link
          to={VIEW_PATHS.symbols}
          onClick={() => onGo('symbols')}
          className="rounded-[8px] bg-accent-fill px-4 py-2 text-[13.5px] font-semibold text-accent-ink no-underline hover:brightness-110"
        >
          {t('start.browseSymbols')}
        </Link>
      </header>

      <div className="hero">
        <h1>{t('start.h1')}</h1>
        <p className="lede">{t('start.lede', { build: meta?.latest.gameVersion ?? '…' })}</p>
      </div>

      {/* Links, not buttons: these are destinations, so middle-click, ctrl-click
          and "copy link address" all work. */}
      <div className="tasks">
        {tasks.map((task) => (
          <Link key={task.q} to={VIEW_PATHS[task.view]} className="task" onClick={() => onGo(task.view)}>
            <span className="q">{task.q}</span>
            <span className="d">{task.d}</span>
          </Link>
        ))}
      </div>

      {/* Four measured numbers, one tile each. */}
      {metaQuery.isLoading && <Card><Skeleton rows={2} /></Card>}
      {metaQuery.error && <Card><p className="plain">{metaQuery.error.message}</p></Card>}
      {meta && (
        <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
          <Card className="flex flex-col gap-1.5">
            <span className="text-[11.5px] font-medium uppercase tracking-wide text-muted-foreground">{t('start.statSymbols')}</span>
            <span className="font-display text-[30px] font-bold leading-none text-ink">{meta.latest.symbolRecords}</span>
          </Card>
          <Card className="flex flex-col gap-2">
            <span className="text-[11.5px] font-medium uppercase tracking-wide text-muted-foreground">
              {t('start.statKeys', { total: meta.latest.pluginKeys })}
            </span>
            <span className="font-display text-[30px] font-bold leading-none text-ok">{meta.latest.pluginKeysCovered}</span>
            <Progress
              percent={(100 * meta.latest.pluginKeysCovered) / Math.max(1, meta.latest.pluginKeys)}
              tone="qualify"
              label={t('start.statKeys', { total: meta.latest.pluginKeys })}
            />
          </Card>
          <Card className="flex flex-col gap-1.5">
            <span className="text-[11.5px] font-medium uppercase tracking-wide text-muted-foreground">{t('start.statGap')}</span>
            <span className={gap > 0 ? 'font-display text-[30px] font-bold leading-none text-warn' : 'font-display text-[30px] font-bold leading-none text-ok'}>{gap}</span>
          </Card>
          <Card className="flex flex-col gap-1.5">
            <span className="text-[11.5px] font-medium uppercase tracking-wide text-muted-foreground">{t('start.statBuilds')}</span>
            <span className="font-display text-[30px] font-bold leading-none text-ink">{meta.builds.length}</span>
          </Card>
        </div>
      )}

      {/*
        No wrapper. `.explain` already carries its own left rule, tint and
        padding, so a Card around it drew the stripe twice - and, because the
        switch in the top bar hides the paragraph and not its container, left an
        empty bordered box sitting above "What moved in" once the notes were
        turned off.
      */}
      <Explain html={t('start.explain')} />

      {/* What moved, next to which files carry it. */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Card className="flex flex-col gap-4">
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="font-display text-[17px] font-bold text-ink">
              {t('start.movedH', { build: meta?.latest.gameVersion ?? '' })}
            </h2>
            <span className="text-[12.5px] text-muted-foreground">{t('start.movedSub', { count: changedThisBuild })}</span>
          </div>
          {indexQuery.isLoading && <Skeleton rows={4} />}
          <div className="flex flex-col gap-2">
            {files.filter((file) => file.updated > 0).map((file) => (
              <Link
                key={file.descriptor.id}
                to={`${VIEW_PATHS.gamedata}?file=${encodeURIComponent(file.descriptor.id)}`}
                onClick={() => onGo('gamedata')}
                className="flex items-stretch gap-3 rounded-[9px] border border-rule bg-sunk px-3.5 py-2.5 no-underline hover:border-rule-strong"
              >
                <span className="w-[3px] shrink-0 rounded bg-accent-fill" />
                <span className="flex min-w-0 grow flex-col gap-0.5">
                  <span className="truncate font-mono text-[13px] text-ink">{file.descriptor.plugin}</span>
                  <span className="text-[11.5px] text-muted-foreground">{t('start.fileKeys', { covered: file.covered, total: file.total })}</span>
                </span>
                <span className="flex items-center"><Tag tone="accent">{t('start.fileChanged', { count: file.updated })}</Tag></span>
              </Link>
            ))}
          </div>
          <Link to={VIEW_PATHS.gamedata} onClick={() => onGo('gamedata')} className="self-start text-[13px] font-semibold">
            {t('start.movedAll')}
          </Link>
        </Card>

        <Card className="flex flex-col gap-4">
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="font-display text-[17px] font-bold text-ink">{t('start.filesH')}</h2>
            <span className="text-[12.5px] text-ok">{t('start.filesSub', { complete, total: files.length })}</span>
          </div>
          <div className="flex flex-col gap-2">
            {files.map((file) => (
              <div key={file.descriptor.id} className="flex items-center gap-2.5 text-[12.5px]">
                <Dot tone={file.gap === 0 ? 'ok' : 'warn'} />
                <span className="min-w-0 grow truncate font-mono text-ink-2">{file.descriptor.plugin}</span>
                <span className="shrink-0 text-faint">{t('start.fileKeys', { covered: file.covered, total: file.total })}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {history && history.builds.length > 1 && (
        <section className="panel">
          <header>
            <h2>{t('start.timelineH')}</h2>
            <span className="sub">{t('start.timelineSub')}</span>
          </header>
          <div className="panel-body">
            <div className="timeline">
              {history.builds.map((build) => {
                const max = Math.max(...history.builds.map((item) => item.keyChanges), 1)
                const height = Math.max(2, Math.round((26 * build.keyChanges) / max))
                return (
                  <span
                    className={build.keyChanges > 0 ? 'tlb has' : 'tlb'}
                    key={build.gameVersion}
                    title={`${build.gameVersion}: ${build.keyChanges}`}
                  >
                    <i style={{ height }} />
                    <span className="lv">{build.gameVersion}</span>
                  </span>
                )
              })}
            </div>
          </div>
        </section>
      )}

      <section className="panel">
        <header><h2>{t('start.stepsH')}</h2></header>
        <div className="panel-body">
          <div className="steps">
            {[1, 2, 3, 4].map((step) => (
              <div className="step" key={step}>
                <span className="i">{step}</span>
                <span dangerouslySetInnerHTML={{ __html: t(`start.s${step}`) }} />
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
