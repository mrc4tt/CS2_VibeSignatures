import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getSiteMeta } from '../../api/siteMeta'
import { buildDate, getSiteHistory, lastChangedIn, type SiteHistory } from '../../api/siteData'
import { formatAgo, formatDay } from '../../components/whenText'
import { Explain } from '../../components/Explain'
import { VIEW_PATHS } from '../../app/appViews'
import { getGameDataIndex } from '../gamedata/data'
import { describeFiles, formatLabel, type PluginFile } from '../gamedata/fileModel'
import { pluginLabel } from '../gamedata/pluginLabel'
import { Pattern } from '../symbols/Pattern'
import { buildChanges, curlCommand, groupByPlugin, installPath, latestUrl, readStarred, withBuildChanges, writeStarred } from './pluginModel'
import { StarButton } from './StarButton'
import { copyText } from '../../ui/clipboard'
import { buttonClass } from '../../ui/buttonStyle'
import { CheckIcon, CopyIcon, DownloadIcon, WarningIcon } from '../../ui/icons'
import { Alert, Button, Empty, Skeleton } from '../../ui/primitives'

const SHOWN_CHANGES = 8

function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <em>—</em>
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return /^[0-9A-Fa-f?\s]{8,}$/.test(text) ? <Pattern pattern={text} /> : <span>{text}</span>
}

/** How many keys of these files changed in each published build, oldest first. */
function changesPerBuild(history: SiteHistory | undefined, ids: string[]): Array<{ build: string; count: number }> {
  if (!history) return []
  const counts = new Map<string, number>()
  for (const id of ids) {
    for (const entry of Object.values(history.files[id] ?? {})) {
      for (const build of entry.changes) counts.set(build, (counts.get(build) ?? 0) + 1)
    }
  }
  return history.builds.map((build) => ({ build: build.gameVersion, count: counts.get(build.gameVersion) ?? 0 }))
}

function FileCard({ file, build }: { file: PluginFile; build: string }) {
  const { t } = useTranslation()
  const origin = window.location.origin
  const base = import.meta.env.BASE_URL
  const url = latestUrl(file, origin, base)
  const command = curlCommand(file, origin, base)
  const messages = { ok: t('clipboard.ok'), failed: t('clipboard.failed') }
  return (
    <section className="filebox">
      <div className="filebox-head">
        <div className="filebox-name">
          <span className="fname">{file.descriptor.fileName}</span>
          <span className="fmeta">
            {formatLabel(file.descriptor.language)} · {t('plugin.values', { covered: file.covered, total: file.total })}
            {file.gap > 0 && <span className="warnc"> · {t('plugin.missing', { count: file.gap })}</span>}
          </span>
        </div>
        <div className="filebox-acts">
          <a className={buttonClass('primary', 'middle')} href={url} download={file.descriptor.fileName}>
            <DownloadIcon size={15} /> {t('plugin.download', { file: file.descriptor.fileName })}
          </a>
          <Link className={buttonClass('default', 'middle')} to={`${VIEW_PATHS.gamedata}?file=${encodeURIComponent(file.descriptor.id)}&build=${encodeURIComponent(build)}`}>
            {t('plugin.view')}
          </Link>
        </div>
      </div>
      <dl className="filebox-rows">
        <dt>{t('plugin.where')}</dt>
        <dd><code>{installPath(file)}</code></dd>
        <dt>{t('plugin.link')}</dt>
        <dd className="copyrow">
          <code>{url}</code>
          <Button size="small" variant="text" aria-label={t('plugin.copyLink')} onClick={() => void copyText(url, messages)}>
            <CopyIcon size={14} />
          </Button>
        </dd>
        <dt>{t('plugin.curl')}</dt>
        <dd className="copyrow">
          <code>{command}</code>
          <Button size="small" variant="text" aria-label={t('plugin.copyCurl')} onClick={() => void copyText(command, messages)}>
            <CopyIcon size={14} />
          </Button>
        </dd>
      </dl>
    </section>
  )
}

export function PluginPage({ plugin }: { plugin: string }) {
  const { t, i18n } = useTranslation()
  const language = i18n.resolvedLanguage ?? 'en'
  const [starred, setStarred] = useState(readStarred)
  const [allChanges, setAllChanges] = useState(false)
  const metaQuery = useQuery({ queryKey: ['site-meta'], queryFn: ({ signal }) => getSiteMeta(signal), staleTime: 5 * 60 * 1000 })
  const indexQuery = useQuery({ queryKey: ['gamedata', 'index'], queryFn: ({ signal }) => getGameDataIndex(signal), staleTime: 5 * 60 * 1000 })
  const historyQuery = useQuery({ queryKey: ['history'], queryFn: ({ signal }) => getSiteHistory(signal), staleTime: Infinity })
  const history = historyQuery.data

  const version = indexQuery.data?.versions.find((entry) => entry.gameVersion === metaQuery.data?.latest.gameVersion)
    ?? indexQuery.data?.versions[0]
  const build = version?.gameVersion ?? ''
  const group = useMemo(
    () => withBuildChanges(groupByPlugin(describeFiles(version?.files ?? [])), history, build).find((item) => item.plugin === plugin),
    [version, plugin, history, build],
  )
  const files = group?.files ?? []
  const ids = files.map((file) => file.descriptor.id)
  const fileNames = new Map(files.map((file) => [file.descriptor.id, file.descriptor.fileName]))
  // Build-to-build movement comes from the history dataset; see buildChanges.
  const changes = useMemo(() => buildChanges(history, ids, build), [history, ids.join('|'), build]) // eslint-disable-line react-hooks/exhaustive-deps
  const loadingChanges = historyQuery.isLoading

  const timeline = useMemo(() => changesPerBuild(history, ids), [history, ids.join('|')]) // eslint-disable-line react-hooks/exhaustive-deps
  const lastChanged = ids
    .map((id) => lastChangedIn(history, id))
    .filter((value): value is string => Boolean(value))
    .sort((left, right) => (history?.builds.findIndex((b) => b.gameVersion === right) ?? 0) - (history?.builds.findIndex((b) => b.gameVersion === left) ?? 0))[0]
  const lastChangedAt = buildDate(history, lastChanged) ?? undefined
  const maxCount = Math.max(1, ...timeline.map((point) => point.count))
  const changedBuilds = timeline.filter((point) => point.count > 0).length

  function toggleStar(): void {
    const next = new Set(starred)
    if (next.has(plugin)) next.delete(plugin)
    else next.add(plugin)
    setStarred(next)
    writeStarred(next)
  }

  if (indexQuery.isLoading) return <div className="pluginpage"><Skeleton rows={8} /></div>
  if (indexQuery.error) return <Alert tone="bad" title={t('gamedata.indexError')} description={indexQuery.error.message} />
  if (!group) {
    return (
      <div className="pluginpage">
        <Empty description={t('plugin.notFound', { plugin })}>
          <Link to={VIEW_PATHS.start}>{t('plugin.back')}</Link>
        </Empty>
      </div>
    )
  }

  const shownChanges = allChanges ? changes : changes.slice(0, SHOWN_CHANGES)

  return (
    <div className="pluginpage">
      <Link to={VIEW_PATHS.start} className="backlink">← {t('plugin.back')}</Link>

      <header className="pluginhead">
        <div className="pluginhead-title">
          <h1>{pluginLabel(plugin)}</h1>
          <StarButton starred={starred.has(plugin)} plugin={pluginLabel(plugin)} onToggle={toggleStar} />
        </div>
        <p className="pluginstate">
          {group.gap > 0
            ? <span className="warnc"><WarningIcon size={16} /> {t('plugin.partial', { count: group.gap, build })}</span>
            : <span className="okc"><CheckIcon size={16} /> {t('plugin.ready', { build })}</span>}
          <span className="muted">
            {t('plugin.values', { covered: group.covered, total: group.total })}
            {' · '}
            {group.updated > 0 ? t('home.changed', { count: group.updated }) : t('home.unchanged')}
          </span>
        </p>
      </header>

      {files.map((file) => <FileCard key={file.descriptor.id} file={file} build={build} />)}

      <section className="psection">
        <h2>{t('plugin.changesH', { build })}</h2>
        {loadingChanges && <Skeleton rows={4} />}
        {!loadingChanges && changes.length === 0 && <p className="plain">{t('plugin.noChanges')}</p>}
        {changes.length > 0 && (
          <div className="tablewrap">
            <table className="chgtable">
              <thead>
                <tr>
                  <th>{t('plugin.key')}</th>
                  <th>{t('plugin.platform')}</th>
                  <th>{t('plugin.beforeAfter')}</th>
                </tr>
              </thead>
              <tbody>
                {shownChanges.map((change, index) => (
                  <tr key={`${change.file}:${change.key}:${change.platform}:${index}`}>
                    <td className="mono">{change.key}{files.length > 1 && <span className="fileof"> {fileNames.get(change.file)}</span>}</td>
                    <td><span className="platchip">{change.platform}</span></td>
                    <td className="mono vals">
                      <span className="old"><Value value={change.before} /></span>
                      <span className="arrow">→</span>
                      <span className="new"><Value value={change.after} /></span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {changes.length > SHOWN_CHANGES && (
          <Button variant="link" onClick={() => setAllChanges(!allChanges)}>
            {allChanges ? t('plugin.fewer') : t('plugin.allChanges', { count: changes.length })}
          </Button>
        )}
      </section>

      {history && (
        <section className="psection">
          <h2>{t('plugin.historyH')}</h2>
          <p className="plain">
            {lastChanged
              ? t('plugin.lastChanged', {
                  build: lastChanged,
                  ago: formatAgo(lastChangedAt, language) || formatDay(lastChangedAt, language),
                })
              : t('plugin.neverChanged')}
            {lastChanged && ' '}
            {lastChanged && t('plugin.changedIn', { count: changedBuilds, total: timeline.length })}
          </p>
          <div className="timeline" role="img" aria-label={t('plugin.timelineLabel', { count: changedBuilds, total: timeline.length })}>
            {timeline.map((point) => (
              <span className={point.count > 0 ? 'tlb has' : 'tlb'} key={point.build} title={`${point.build}: ${point.count}`}>
                <i style={{ height: point.count > 0 ? Math.max(4, Math.round((26 * point.count) / maxCount)) : 2 }} />
                <span className="lv">{point.build}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      <Explain summary={t('plugin.whatH')} html={t('plugin.what')} />
    </div>
  )
}
