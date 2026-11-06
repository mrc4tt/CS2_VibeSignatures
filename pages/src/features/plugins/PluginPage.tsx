import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getSiteMeta } from '../../api/siteMeta'
import { buildDate, getSiteHistory, lastChangedIn, type SiteHistory } from '../../api/siteData'
import { formatAgo, formatDay } from '../../components/whenText'
import { Explain } from '../../components/Explain'
import { ValueChange } from '../../components/ValueChange'
import { VIEW_PATHS } from '../../app/appViews'
import { getGameDataFile, getGameDataIndex, getGameDataMetadata } from '../gamedata/data'
import { describeFiles, formatLabel, type PluginFile } from '../gamedata/fileModel'
import { FileView } from '../gamedata/FileView'
import { pluginLabel } from '../gamedata/pluginLabel'
import { buildChanges, curlCommand, groupByPlugin, installPath, latestUrl, readStarred, withBuildChanges, writeStarred, type BuildChange } from './pluginModel'
import { StarButton } from './StarButton'
import { copyText } from '../../ui/clipboard'
import { buttonClass } from '../../ui/buttonStyle'
import { CheckIcon, CopyIcon, DownloadIcon } from '../../ui/icons'
import { Alert, Button, Empty, Skeleton } from '../../ui/primitives'

/** Keys listed before "show all"; the busiest come first, so these are the ones that matter. */
const SHOWN_KEYS = 15

interface KeyRow {
  key: string
  changes: number
  last?: string
}

/** Every key (and sub-value, such as `.vtable`) still in one file, with how often it moved in the published history, busiest first. */
function keyRows(history: SiteHistory | undefined, id: string): KeyRow[] {
  const entries = Object.entries(history?.files[id] ?? {})
  const order = history?.builds.map((item) => item.gameVersion) ?? []
  const at = (build: string | undefined) => (build ? order.indexOf(build) : -1)
  return entries
    // A key the file dropped stays in the history; it is gone when its last
    // removal came after its last value.
    .filter(([, entry]) => at(entry.gone?.[entry.gone.length - 1]) <= at(entry.points[entry.points.length - 1]?.[0]))
    .map(([key, entry]) => ({ key, changes: entry.changes.length, last: entry.changes[entry.changes.length - 1] }))
    .sort((left, right) =>
      right.changes - left.changes
      || order.indexOf(right.last ?? '') - order.indexOf(left.last ?? '')
      || left.key.localeCompare(right.key))
}

/** One changed key: its platforms side by side, old value over new. */
function ChangedKey({ rows, previous, build }: { rows: BuildChange[]; previous: string; build: string }) {
  const { t } = useTranslation()
  const moved = new Set(rows.map((row) => row.platform))
  return (
    <div className="pdiff">
      <div className="pdiff-key">{rows[0].key}</div>
      {rows.map((row) => (
        <div className="pdiff-plat" key={row.platform}>
          <span className="platchip">{row.platform}</span>
          <ValueChange before={row.before} after={row.after} beforeLabel={previous} afterLabel={build} copyable />
        </div>
      ))}
      {(['linux', 'windows'] as const).filter((platform) => !moved.has(platform)).map((platform) => (
        <div className="pdiff-plat quiet" key={platform}>
          <span className="platchip">{platform}</span>
          <span className="muted">{t('plugin2.unchanged')}</span>
        </div>
      ))}
    </div>
  )
}

function GetFile({ file }: { file: PluginFile }) {
  const { t } = useTranslation()
  const origin = window.location.origin
  const base = import.meta.env.BASE_URL
  const url = latestUrl(file, origin, base)
  const command = curlCommand(file, origin, base)
  const messages = { ok: t('clipboard.ok'), failed: t('clipboard.failed') }
  return (
    <details className="pget">
      <summary>{t('plugin2.otherWays')}</summary>
      <dl className="filebox-rows">
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
    </details>
  )
}

export function PluginPage({ plugin }: { plugin: string }) {
  const { t, i18n } = useTranslation()
  const language = i18n.resolvedLanguage ?? 'en'
  const [params, setParams] = useSearchParams()
  const [starred, setStarred] = useState(readStarred)
  const [allKeys, setAllKeys] = useState(false)
  const [showFile, setShowFile] = useState(false)
  const [find, setFind] = useState('')
  const [marks, setMarks] = useState(false)
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
  // A plugin with several files shows one at a time; the choice is in the URL so
  // a link can point at the second file.
  const file = files.find((item) => item.descriptor.id === params.get('file')) ?? files[0]
  const id = file?.descriptor.id ?? ''
  const order = history?.builds.map((item) => item.gameVersion) ?? []
  const previous = order[order.indexOf(build) - 1] ?? ''

  const changes = useMemo(() => (id ? buildChanges(history, [id], build) : []), [history, id, build])
  const changedKeys = useMemo(() => {
    const byKey = new Map<string, BuildChange[]>()
    for (const row of changes) byKey.set(row.key, [...(byKey.get(row.key) ?? []), row])
    return [...byKey.values()]
  }, [changes])
  const keys = useMemo(() => keyRows(history, id), [history, id])
  const lastChanged = id ? lastChangedIn(history, id) : undefined
  const lastChangedAt = buildDate(history, lastChanged)

  const fileQuery = useQuery({
    queryKey: ['gamedata', build, id, file?.descriptor.content.url],
    queryFn: ({ signal }) => getGameDataFile(file!.descriptor, signal),
    enabled: Boolean(file && showFile),
    staleTime: Infinity,
  })
  const lineCount = fileQuery.data?.split('\n').length ?? 0
  const metadataQuery = useQuery({
    queryKey: ['gamedata', build, id, file?.descriptor.metadata?.url, lineCount],
    queryFn: ({ signal }) => getGameDataMetadata(file!.descriptor, lineCount, build, signal),
    enabled: Boolean(file?.descriptor.metadata && fileQuery.data && build),
    staleTime: Infinity,
  })

  function toggleStar(): void {
    const next = new Set(starred)
    if (next.has(plugin)) next.delete(plugin)
    else next.add(plugin)
    setStarred(next)
    writeStarred(next)
  }

  function pickFile(next: string): void {
    const copy = new URLSearchParams(params)
    copy.set('file', next)
    setParams(copy, { replace: true })
    setFind('')
  }

  if (indexQuery.isLoading) return <div className="pluginpage"><Skeleton rows={8} /></div>
  if (indexQuery.error) return <Alert tone="bad" title={t('gamedata.indexError')} description={indexQuery.error.message} />
  if (!group || !file) {
    return (
      <div className="pluginpage">
        <Empty description={t('plugin.notFound', { plugin })}>
          <Link to={VIEW_PATHS.start}>{t('plugin.back')}</Link>
        </Empty>
      </div>
    )
  }

  const url = latestUrl(file, window.location.origin, import.meta.env.BASE_URL)
  const shownKeys = allKeys ? keys : keys.slice(0, SHOWN_KEYS)

  return (
    <div className="pluginpage">
      <Link to={VIEW_PATHS.start} className="backlink">← {t('plugin.back')}</Link>

      <header className="phead">
        <div className="phead-title">
          <code className="ppath">{installPath(file)}</code>
          <div className="pluginhead-title">
            <h1>{pluginLabel(plugin)}</h1>
            <StarButton starred={starred.has(plugin)} plugin={pluginLabel(plugin)} onToggle={toggleStar} />
          </div>
        </div>
        <div className="phead-acts">
          <a className={buttonClass('primary', 'middle')} href={url} download={file.descriptor.fileName}>
            <DownloadIcon size={15} /> {t('plugin.download', { file: file.descriptor.fileName })}
          </a>
        </div>
      </header>

      {files.length > 1 && (
        <div className="pfiletabs" role="tablist" aria-label={t('plugin2.filesLabel')}>
          {files.map((item) => (
            <button
              type="button"
              role="tab"
              key={item.descriptor.id}
              aria-selected={item === file}
              onClick={() => pickFile(item.descriptor.id)}
            >
              {item.descriptor.fileName}
              {item.gap > 0 && <span className="pdot bad" aria-hidden="true" />}
            </button>
          ))}
        </div>
      )}

      <section className="panel pfacts" aria-label={t('plugin2.factsLabel')}>
        <div>
          <b className={file.gap > 0 ? 'warnc' : undefined}>{file.covered}/{file.total}</b>
          <span>{file.gap > 0 ? t('plugin2.factMissing', { count: file.gap }) : t('plugin2.factCovered')}</span>
        </div>
        <div>
          <b className={changedKeys.length ? 'warnc' : undefined}>{changedKeys.length}</b>
          <span>{t('plugin2.factChanged', { build })}</span>
        </div>
        <div>
          <b>{lastChanged ?? '–'}</b>
          <span>
            {lastChanged
              ? t('plugin2.factLast', { ago: formatAgo(lastChangedAt, language) || formatDay(lastChangedAt, language) })
              : t('plugin.neverChanged')}
          </span>
        </div>
        <div>
          <b className="okc"><CheckIcon size={18} /></b>
          <span>{t('plugin2.factVerified')}</span>
        </div>
      </section>

      <GetFile file={file} />

      <section className="panel" aria-labelledby="pchanges-h">
        <header>
          <h2 id="pchanges-h">{t('plugin2.sinceH')}</h2>
          {previous && <span className="sub">{t('plugin2.sinceSub', { previous, build })}</span>}
          {previous && (
            <Link className="pright" to={`${VIEW_PATHS.diff}?from=${encodeURIComponent(previous)}&to=${encodeURIComponent(build)}&plugins=${encodeURIComponent(plugin)}`}>
              {t('plugin2.olderBuild')}
            </Link>
          )}
        </header>
        {historyQuery.isLoading && <div className="panel-body"><Skeleton rows={3} /></div>}
        {history && changedKeys.length === 0 && <p className="pnone"><CheckIcon size={15} /> {t('plugin.noChanges')}</p>}
        {changedKeys.length > 0 && (
          <div className="pdiffs">
            {changedKeys.map((rows) => <ChangedKey key={rows[0].key} rows={rows} previous={previous} build={build} />)}
          </div>
        )}
      </section>

      {keys.length > 0 && (
        <section className="panel" aria-labelledby="pkeys-h">
          <header>
            <h2 id="pkeys-h">{t('plugin2.keysH')}</h2>
            <span className="sub">{t('plugin2.keysSub', { count: order.length })}</span>
          </header>
          <div className="tablewrap">
            <table className="keytab">
              <thead>
                <tr>
                  <th>{t('plugin.key')}</th>
                  <th className="num">{t('plugin2.changes')}</th>
                  <th className="num">{t('plugin2.lastCol')}</th>
                </tr>
              </thead>
              <tbody>
                {shownKeys.map((row) => (
                  <tr key={row.key} className={row.last === build ? 'cur' : undefined}>
                    <td className="mono">{row.key}</td>
                    <td className="num">
                      {row.changes
                        ? <span className={row.changes > 4 ? 'hpill warn' : 'hpill'}>{row.changes}</span>
                        : <span className="muted">{t('plugin2.never')}</span>}
                    </td>
                    <td className="num mono">{row.last ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {keys.length > SHOWN_KEYS && (
            <div className="pmore">
              <Button variant="link" onClick={() => setAllKeys(!allKeys)}>
                {allKeys ? t('plugin.fewer') : t('plugin2.allKeys', { count: keys.length })}
              </Button>
            </div>
          )}
        </section>
      )}

      <section className="panel pfile" aria-labelledby="pfile-h">
        <header>
          <h2 id="pfile-h">{t('plugin2.fileH')}</h2>
          <span className="sub">{formatLabel(file.descriptor.language)} · {t('plugin.values', { covered: file.covered, total: file.total })}</span>
          <span className="pright">
            <Button size="small" onClick={() => setShowFile(!showFile)} aria-expanded={showFile}>
              {showFile ? t('plugin2.hideFile') : t('plugin2.showFile')}
            </Button>
          </span>
        </header>
        {showFile && (
          <>
            {fileQuery.error && <Alert tone="bad" title={t('gamedata.fileError')} description={fileQuery.error.message} />}
            {fileQuery.isLoading && <div className="panel-body"><Skeleton rows={12} /></div>}
            {fileQuery.data && (
              <FileView
                descriptor={file.descriptor}
                content={fileQuery.data}
                metadata={metadataQuery.data}
                find={find}
                marks={marks}
                onFind={setFind}
                onMarks={setMarks}
              />
            )}
          </>
        )}
      </section>

      <Explain summary={t('plugin.whatH')} html={t('plugin.what')} />
    </div>
  )
}
