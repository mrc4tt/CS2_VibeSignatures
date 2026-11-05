import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getSiteMeta } from '../../api/siteMeta'
import { getSiteHistory } from '../../api/siteData'
import { formatAgo, formatWhen } from '../../components/whenText'
import { Explain } from '../../components/Explain'
import { pluginPath, VIEW_PATHS, type AppView } from '../../app/appViews'
import { getGameDataIndex } from '../gamedata/data'
import { describeFiles } from '../gamedata/fileModel'
import { pluginLabel } from '../gamedata/pluginLabel'
import { buildChanges, groupByPlugin, latestUrl, readStarred, sortPlugins, withBuildChanges, writeStarred, type PluginGroup } from '../plugins/pluginModel'
import { StarButton } from '../plugins/StarButton'
import { buttonClass } from '../../ui/buttonStyle'
import { CheckIcon, DownloadIcon } from '../../ui/icons'
import { Alert, Skeleton } from '../../ui/primitives'

const SEEN_KEY = 'cs2vibe.seenBuild'
/** How many builds the timeline shows; enough to cover a month of updates. */
const TIMELINE_BUILDS = 8
/** Changed keys named in a to-do row before the rest collapse into "+N". */
const NAMED_KEYS = 3

function readSeen(): string | null {
  try {
    return localStorage.getItem(SEEN_KEY)
  } catch {
    return null
  }
}

function DownloadButton({ group, primary = false, label }: { group: PluginGroup; primary?: boolean; label?: string }) {
  const { t } = useTranslation()
  const single = group.files.length === 1 ? group.files[0] : undefined
  if (!single) {
    return <Link className={buttonClass(primary ? 'primary' : 'default', 'small')} to={pluginPath(group.plugin)}>{t('home.open')}</Link>
  }
  return (
    <a
      className={buttonClass(primary ? 'primary' : 'default', 'small')}
      href={latestUrl(single, window.location.origin, import.meta.env.BASE_URL)}
      download={single.descriptor.fileName}
      aria-label={t('home.downloadOne', { file: single.descriptor.fileName, plugin: pluginLabel(group.plugin) })}
    >
      <DownloadIcon size={14} /> {label ?? t('start2.get', { file: single.descriptor.fileName })}
    </a>
  )
}

/**
 * One plugin that needs a decision in this build: a value moved, or a key has
 * no value. Everything else is quiet and lives in the lists below.
 */
function TodoRow({ group, keys }: { group: PluginGroup; keys: string[] }) {
  const { t } = useTranslation()
  const moved = group.updated > 0
  const named = keys.slice(0, NAMED_KEYS)
  return (
    <li className={moved ? 'todo warn' : 'todo bad'}>
      <div className="todo-text">
        <h3>
          <Link to={pluginPath(group.plugin)}>{pluginLabel(group.plugin)}</Link>
          {moved
            ? <span className="hpill warn">{t('start2.newValues', { count: group.updated })}</span>
            : <span className="hpill bad">{t('start2.missing', { count: group.gap })}</span>}
        </h3>
        <p>
          {moved
            ? <>
                {named.map((key, index) => <span key={key}>{index > 0 && ', '}<code>{key}</code></span>)}
                {keys.length > named.length && ` ${t('start2.more', { count: keys.length - named.length })}`}
                {' '}{t('start2.movedTail')}
              </>
            : t('start2.missingTail', { count: group.gap })}
        </p>
      </div>
      <div className="todo-acts">
        <DownloadButton group={group} primary={moved} label={moved ? undefined : t('start2.getAnyway')} />
        <Link className={buttonClass('default', 'small')} to={pluginPath(group.plugin)}>
          {moved ? t('start2.seeChange') : t('start2.seeWhich')}
        </Link>
      </div>
    </li>
  )
}

function PluginChip({ group, starred, onStar }: { group: PluginGroup; starred: boolean; onStar(): void }) {
  const { t } = useTranslation()
  const single = group.files.length === 1 ? group.files[0] : undefined
  const tone = group.gap > 0 ? 'bad' : group.updated > 0 ? 'warn' : 'ok'
  return (
    <li className="pchip">
      <StarButton starred={starred} plugin={pluginLabel(group.plugin)} onToggle={onStar} />
      <Link to={pluginPath(group.plugin)} className="pchip-name">
        <span className="pn">{pluginLabel(group.plugin)}</span>
        <span className="pfiles">{single ? single.descriptor.fileName : t('home.files', { count: group.files.length })}</span>
      </Link>
      <span className={`pdot ${tone}`} title={t(`start2.state.${tone}`)}>
        <span className="sr-only">{t(`start2.state.${tone}`)}</span>
      </span>
    </li>
  )
}

export function StartPage({ onGo }: { onGo(view: AppView): void }) {
  const { t, i18n } = useTranslation()
  const [seen] = useState(readSeen)
  const [dismissed, setDismissed] = useState(false)
  const [starred, setStarred] = useState(readStarred)
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

  const version = indexQuery.data?.versions.find((entry) => entry.gameVersion === meta?.latest.gameVersion)
    ?? indexQuery.data?.versions[0]
  const build = version?.gameVersion ?? meta?.latest.gameVersion ?? ''
  const groups = useMemo(
    () => withBuildChanges(groupByPlugin(describeFiles(version?.files ?? [])), history, build),
    [version, history, build],
  )
  const sorted = useMemo(() => sortPlugins(groups, starred), [groups, starred])
  const movedKeys = useMemo(() => {
    const keys = new Map<string, string[]>()
    for (const group of groups) {
      if (group.updated === 0) continue
      const rows = buildChanges(history, group.files.map((file) => file.descriptor.id), build)
      keys.set(group.plugin, [...new Set(rows.map((row) => row.key))])
    }
    return keys
  }, [groups, history, build])

  // Moved values first: those are the files a server has to replace. A missing
  // key keeps the plugin's own text, which works until it does not.
  const todo = [
    ...groups.filter((group) => group.updated > 0).sort((left, right) => right.updated - left.updated),
    ...groups.filter((group) => group.updated === 0 && group.gap > 0),
  ]
  const moved = groups.filter((group) => group.updated > 0).length
  const missing = groups.filter((group) => group.gap > 0).length
  const checked = groups.reduce((total, group) => total + group.covered, 0)
  const mine = sorted.filter((group) => starred.has(group.plugin))
  const rest = sorted.filter((group) => !starred.has(group.plugin))
  const order = history?.builds ?? []
  const previous = order[order.findIndex((item) => item.gameVersion === build) - 1]?.gameVersion
  const timeline = order.slice(-TIMELINE_BUILDS)
  const peak = Math.max(1, ...timeline.map((item) => item.keyChanges))

  // Only a returning visitor gets a note: "first visit" told a new one nothing
  // the status line under it does not.
  const sinceLastVisit = useMemo(() => {
    if (!meta || !history || !seen || seen === meta.latest.gameVersion) return undefined
    const at = history.builds.findIndex((item) => item.gameVersion === seen)
    if (at < 0) return undefined
    const newer = history.builds.slice(at + 1)
    return { builds: newer.length, keys: newer.reduce((total, item) => total + item.keyChanges, 0), from: seen }
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

  const chip = (group: PluginGroup) => (
    <PluginChip key={group.plugin} group={group} starred={starred.has(group.plugin)} onStar={() => toggleStar(group.plugin)} />
  )
  const ready = groups.length > 0

  return (
    <div className="home">
      {sinceLastVisit && !dismissed && (
        <p className="visit">
          <span>{t('start.sinceLast', { builds: sinceLastVisit.builds, keys: sinceLastVisit.keys })}</span>
          <Link to={`${VIEW_PATHS.diff}?from=${encodeURIComponent(sinceLastVisit.from)}`} onClick={markSeen}>{t('start2.seeAll')}</Link>
          <button type="button" onClick={markSeen} aria-label={t('start.dismiss')}>×</button>
        </p>
      )}

      <section className="hstatus" aria-labelledby="status-h">
        <div className="hstatus-row">
          <h1 id="status-h">{build ? t('start2.h1', { build }) : t('home.h1')}</h1>
          {meta && (
            <div className="hstatus-meta">
              {ready && <span className="hpill ok"><CheckIcon size={13} /> {t('start2.checked', { count: checked })}</span>}
              <span className="hpill plain" title={formatWhen(meta.latest.lastPublishTime, language)}>
                {t('start2.published', { ago: formatAgo(meta.latest.lastPublishTime, language) })}
              </span>
            </div>
          )}
        </div>
        {ready && (
          <p className="lede">
            {todo.length
              ? [
                  moved ? t('start2.sumMoved', { count: moved }) : '',
                  missing ? t('start2.sumMissing', { count: missing }) : '',
                  previous ? t('start2.sumRest', { previous }) : '',
                ].filter(Boolean).join(' ')
              : t('start2.allQuiet', { previous: previous ?? build })}
          </p>
        )}
      </section>

      {metaQuery.error && <Alert tone="bad" title={metaQuery.error.message} />}
      {indexQuery.error && <Alert tone="bad" title={t('gamedata.indexError')} description={indexQuery.error.message} />}
      {indexQuery.isLoading && <div className="panel"><Skeleton rows={4} /></div>}

      {ready && (
        <section className="panel" aria-labelledby="todo-h">
          <header>
            <h2 id="todo-h">{t('start2.todoH')}</h2>
            <span className="sub">{t('start2.todoSub', { count: todo.length, total: groups.length })}</span>
          </header>
          {todo.length
            ? <ul className="todos">{todo.map((group) => <TodoRow key={group.plugin} group={group} keys={movedKeys.get(group.plugin) ?? []} />)}</ul>
            : <p className="todo-none"><CheckIcon size={15} /> {t('start2.nothing')}</p>}
        </section>
      )}

      {ready && (
        <div className="hgrid">
          <section className="panel" aria-labelledby="mine-h">
            <header>
              <h2 id="mine-h">{t('start2.mineH')}</h2>
              <span className="sub">{t('start2.mineSub')}</span>
            </header>
            {mine.length
              ? <ul className="pchips">{mine.map(chip)}</ul>
              : <p className="hint">{t('start2.starHint')}</p>}
            <details className="hrest" open={mine.length === 0}>
              <summary>{t('start2.restH', { count: rest.length })}</summary>
              <ul className="pchips">{rest.map(chip)}</ul>
            </details>
          </section>

          <section className="panel" aria-labelledby="builds-h">
            <header>
              <h2 id="builds-h">{t('start2.buildsH')}</h2>
              <span className="sub">{t('start2.buildsSub')}</span>
            </header>
            <ol className="hbars">
              {timeline.map((item) => (
                <li key={item.gameVersion}>
                  <Link
                    to={`${VIEW_PATHS.diff}?from=${encodeURIComponent(item.gameVersion)}`}
                    className={item.gameVersion === build ? 'hbar cur' : 'hbar'}
                    aria-label={t('start2.barLabel', { build: item.gameVersion, count: item.keyChanges })}
                  >
                    <b>{item.keyChanges}</b>
                    <i style={{ height: `${item.keyChanges ? Math.max(6, Math.round(Math.sqrt(item.keyChanges / peak) * 100)) : 3}%` }} />
                    <span>{item.gameVersion}</span>
                  </Link>
                </li>
              ))}
            </ol>
            <p className="hbars-cap">{t('start2.buildsCap')}</p>
            <div className="hcheck">
              <span>{t('start2.checkQ')}</span>
              <Link className={buttonClass('default', 'small')} to={VIEW_PATHS.check} onClick={() => onGo('check')}>{t('start2.checkGo')}</Link>
            </div>
          </section>
        </div>
      )}

      <Explain summary={t('home.howH')} html={t('home.how')} />
    </div>
  )
}
