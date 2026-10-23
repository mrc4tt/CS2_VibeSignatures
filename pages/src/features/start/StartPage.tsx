import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getSiteMeta } from '../../api/siteMeta'
import { getSiteHistory } from '../../api/siteData'
import { formatAgo } from '../../components/whenText'
import { Explain } from '../../components/Explain'
import { pluginPath, VIEW_PATHS, type AppView } from '../../app/appViews'
import { getGameDataIndex } from '../gamedata/data'
import { describeFiles } from '../gamedata/fileModel'
import { pluginLabel } from '../gamedata/pluginLabel'
import { groupByPlugin, latestUrl, readStarred, sortPlugins, withBuildChanges, writeStarred, type PluginGroup } from '../plugins/pluginModel'
import { StarButton } from '../plugins/StarButton'
import { buttonClass } from '../../ui/buttonStyle'
import { CheckIcon, DownloadIcon, SearchIcon, WarningIcon } from '../../ui/icons'
import { Alert, Skeleton } from '../../ui/primitives'

const SEEN_KEY = 'cs2vibe.seenBuild'

function readSeen(): string | null {
  try {
    return localStorage.getItem(SEEN_KEY)
  } catch {
    return null
  }
}

function PluginRow({ group, starred, onStar }: { group: PluginGroup; starred: boolean; onStar(): void }) {
  const { t } = useTranslation()
  const single = group.files.length === 1 ? group.files[0] : undefined
  return (
    <li className="prow">
      <StarButton starred={starred} plugin={pluginLabel(group.plugin)} onToggle={onStar} />
      <Link to={pluginPath(group.plugin)} className="pname">
        <span className="pn">{pluginLabel(group.plugin)}</span>
        <span className="pfiles">
          {single ? single.descriptor.fileName : t('home.files', { count: group.files.length })}
        </span>
      </Link>
      <span className={group.gap > 0 ? 'pstate warn' : 'pstate ok'}>
        {group.gap > 0
          ? <><WarningIcon size={14} /> {t('home.partial', { count: group.gap })}</>
          : <><CheckIcon size={14} /> {t('home.ready')}</>}
      </span>
      <span className={group.updated > 0 ? 'pchg on' : 'pchg'}>
        {group.updated > 0 ? t('home.changed', { count: group.updated }) : t('home.unchanged')}
      </span>
      <span className="pact">
        {single
          ? (
              <a
                className={buttonClass('default', 'small')}
                href={latestUrl(single, window.location.origin, import.meta.env.BASE_URL)}
                download={single.descriptor.fileName}
                aria-label={t('home.downloadOne', { file: single.descriptor.fileName, plugin: pluginLabel(group.plugin) })}
              >
                <DownloadIcon size={14} /> {t('home.download')}
              </a>
            )
          : (
              <Link className={buttonClass('default', 'small')} to={pluginPath(group.plugin)}>
                {t('home.open')}
              </Link>
            )}
      </span>
    </li>
  )
}

export function StartPage({ onGo }: { onGo(view: AppView): void }) {
  const { t, i18n } = useTranslation()
  const [seen] = useState(readSeen)
  const [dismissed, setDismissed] = useState(false)
  const [starred, setStarred] = useState(readStarred)
  const [filter, setFilter] = useState('')
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
  // The plugin list reads the same index Game Data does, so the two can never
  // disagree about how much of a plugin's file this build filled in.
  const indexQuery = useQuery({
    queryKey: ['gamedata', 'index'],
    queryFn: ({ signal }) => getGameDataIndex(signal),
    staleTime: 5 * 60 * 1000,
  })
  const meta = metaQuery.data
  const history = historyQuery.data

  const groups = useMemo(() => {
    const version = indexQuery.data?.versions.find((entry) => entry.gameVersion === meta?.latest.gameVersion)
      ?? indexQuery.data?.versions[0]
    return withBuildChanges(groupByPlugin(describeFiles(version?.files ?? [])), history, version?.gameVersion ?? '')
  }, [indexQuery.data, meta, history])
  const sorted = useMemo(() => sortPlugins(groups, starred), [groups, starred])
  const needle = filter.trim().toLowerCase()
  const shown = needle
    ? sorted.filter((group) => `${group.plugin} ${pluginLabel(group.plugin)}`.toLowerCase().includes(needle))
    : sorted
  const complete = groups.filter((group) => group.gap === 0).length
  const mine = shown.filter((group) => starred.has(group.plugin))
  const rest = shown.filter((group) => !starred.has(group.plugin))

  // Only a returning visitor gets a note: "first visit" told a new one nothing
  // the status line under it does not.
  const sinceLastVisit = useMemo(() => {
    if (!meta || !history || !seen || seen === meta.latest.gameVersion) return undefined
    const order = history.builds.map((build) => build.gameVersion)
    const at = order.indexOf(seen)
    if (at < 0) return undefined
    const newer = history.builds.slice(at + 1)
    return { builds: newer.length, keys: newer.reduce((total, build) => total + build.keyChanges, 0) }
  }, [meta, history, seen])

  function markSeen(): void {
    setDismissed(true)
    try {
      if (meta) localStorage.setItem(SEEN_KEY, meta.latest.gameVersion)
    } catch {
      // a private window is not a reason to fail a click
    }
  }

  function toggleStar(plugin: string): void {
    const next = new Set(starred)
    if (next.has(plugin)) next.delete(plugin)
    else next.add(plugin)
    setStarred(next)
    writeStarred(next)
  }

  const renderRow = (group: PluginGroup) => (
    <PluginRow key={group.plugin} group={group} starred={starred.has(group.plugin)} onStar={() => toggleStar(group.plugin)} />
  )

  return (
    <div className="home">
      {sinceLastVisit && !dismissed && (
        <p className="visit">
          <span>{t('start.sinceLast', { builds: sinceLastVisit.builds, keys: sinceLastVisit.keys })}</span>
          <button type="button" onClick={markSeen} aria-label={t('start.dismiss')}>×</button>
        </p>
      )}

      <section className="homehero">
        {meta
          ? (
              <p className="buildok">
                <CheckIcon size={16} />
                {t('home.build', { build: meta.latest.gameVersion, ago: formatAgo(meta.latest.lastPublishTime, language) })}
              </p>
            )
          : <p className="buildok muted">…</p>}
        <h1>{t('home.h1')}</h1>
        <p className="lede">{t('home.lede')}</p>
        <div className="heroacts">
          <a className={buttonClass('primary', 'large')} href="#plugins">{t('home.pick')}</a>
          <Link className={buttonClass('default', 'large')} to={VIEW_PATHS.check} onClick={() => onGo('check')}>
            {t('home.checkFile')}
          </Link>
        </div>
      </section>

      {metaQuery.error && <Alert tone="bad" title={metaQuery.error.message} />}

      <section id="plugins" className="plugins" aria-labelledby="plugins-h">
        <div className="sechead">
          <div>
            <h2 id="plugins-h">{t('home.pluginsH')}</h2>
            {groups.length > 0 && (
              <p className="sub">{t('home.pluginsSub', { complete, total: groups.length, build: meta?.latest.gameVersion ?? '' })}</p>
            )}
          </div>
          <label className="pfilter">
            <SearchIcon size={15} />
            <span className="sr-only">{t('home.filter')}</span>
            <input type="search" value={filter} placeholder={t('home.filter')} onChange={(event) => setFilter(event.target.value)} />
          </label>
        </div>

        {indexQuery.isLoading && <div className="plist"><Skeleton rows={6} /></div>}
        {indexQuery.error && <Alert tone="bad" title={t('gamedata.indexError')} description={indexQuery.error.message} />}

        {mine.length > 0 && (
          <>
            <h3 className="plabel">{t('home.mine')}</h3>
            <ul className="plist">{mine.map(renderRow)}</ul>
          </>
        )}
        {rest.length > 0 && (
          <>
            {mine.length > 0 && <h3 className="plabel">{t('home.others')}</h3>}
            <ul className="plist">{rest.map(renderRow)}</ul>
          </>
        )}
        {groups.length > 0 && shown.length === 0 && <p className="plain">{t('home.noMatch', { query: filter })}</p>}
        {groups.length > 0 && starred.size === 0 && <p className="hint">{t('home.starHint')}</p>}
      </section>

      <section className="homecards">
        <Link to={VIEW_PATHS.check} className="hcard" onClick={() => onGo('check')}>
          <span className="q">{t('home.checkH')}</span>
          <span className="d">{t('home.checkD')}</span>
        </Link>
        <Link to={VIEW_PATHS.diff} className="hcard" onClick={() => onGo('diff')}>
          <span className="q">{t('home.skipH')}</span>
          <span className="d">{t('home.skipD')}</span>
        </Link>
        <Link to={VIEW_PATHS.symbols} className="hcard" onClick={() => onGo('symbols')}>
          <span className="q">{t('home.symbolH')}</span>
          <span className="d">{t('home.symbolD')}</span>
        </Link>
      </section>

      <Explain summary={t('home.howH')} html={t('home.how')} />
    </div>
  )
}
