import { useQuery } from '@tanstack/react-query'
import { Alert, Select, Skeleton } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Explain } from '../../components/Explain'
import { getSiteHistory } from '../../api/siteData'
import { getGameDataFile, getGameDataIndex, getGameDataMetadata } from './data'
import { changedKeys, describeFiles, formatLabel, notProducedKeys } from './fileModel'
import { FileView } from './FileView'
import { Pattern } from '../symbols/Pattern'
import type { GameDataChange } from './types'

type DetailTab = 'changes' | 'keys' | 'history'

function ChangeValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <em>—</em>
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return /^[0-9A-Fa-f?\s]{8,}$/.test(text) ? <Pattern pattern={text} /> : <span>{text}</span>
}

function ChangeRows({ changes }: { changes: GameDataChange[] }) {
  return (
    <div className="cbody">
      {changes.map((change, index) => (
        <div className="chgline" key={index}>
          <span className="lab">{change.path[change.path.length - 1]}</span>
          <span className="o">- <ChangeValue value={change.before} /></span>
          <span className="n2">+ <ChangeValue value={change.after} /></span>
        </div>
      ))}
    </div>
  )
}

export function GameDataPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const [detailTab, setDetailTab] = useState<DetailTab>('changes')
  const [showDetail, setShowDetail] = useState(false)
  const [fullWidth, setFullWidth] = useState(false)

  const setParam = (key: string, value?: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  useEffect(() => {
    document.body.classList.toggle('filefull', fullWidth)
    return () => document.body.classList.remove('filefull')
  }, [fullWidth])

  const indexQuery = useQuery({
    queryKey: ['gamedata', 'index'],
    queryFn: ({ signal }) => getGameDataIndex(signal),
    staleTime: 5 * 60 * 1000,
  })
  const version = params.get('build') ?? indexQuery.data?.versions[0]?.gameVersion
  const versionEntry = indexQuery.data?.versions.find((entry) => entry.gameVersion === version)
  const files = useMemo(() => describeFiles(versionEntry?.files ?? []), [versionEntry])
  const selectedId = params.get('file') ?? undefined
  const selected = files.find((file) => file.descriptor.id === selectedId)
  const find = params.get('find') ?? ''
  const marks = params.get('marks') === '1'
  const focusLine = Number(params.get('line')) || undefined
  const gapFilter = params.get('only') === 'gap'

  const fileQuery = useQuery({
    queryKey: ['gamedata', version, selected?.descriptor.id, selected?.descriptor.content.url],
    queryFn: ({ signal }) => getGameDataFile(selected!.descriptor, signal),
    enabled: Boolean(selected),
    staleTime: Infinity,
  })
  const lineCount = fileQuery.data?.split('\n').length ?? 0
  const metadataQuery = useQuery({
    queryKey: ['gamedata', version, selected?.descriptor.id, selected?.descriptor.metadata?.url, lineCount],
    queryFn: ({ signal }) => getGameDataMetadata(selected!.descriptor, lineCount, version!, signal),
    enabled: Boolean(selected?.descriptor.metadata && fileQuery.data && version),
    staleTime: Infinity,
  })

  const historyQuery = useQuery({
    queryKey: ['history'],
    queryFn: ({ signal }) => getSiteHistory(signal),
    staleTime: Infinity,
  })
  // history.json keys files by their path inside gamedata/<build>/, which is the
  // descriptor id, so no mapping is needed.
  const keyHistory = selected ? historyQuery.data?.files[selected.descriptor.id] : undefined
  const fragility = useMemo(() => {
    if (!keyHistory) return []
    return Object.entries(keyHistory)
      .map(([name, entry]) => ({
        name,
        changes: entry.changes.length,
        observed: entry.points.length,
        last: entry.changes[entry.changes.length - 1],
      }))
      .sort((left, right) => right.changes - left.changes || left.name.localeCompare(right.name))
  }, [keyHistory])

  const changed = useMemo(() => changedKeys(metadataQuery.data), [metadataQuery.data])
  const missing = useMemo(() => notProducedKeys(metadataQuery.data), [metadataQuery.data])

  async function download(): Promise<void> {
    if (!selected || !fileQuery.data) return
    const blob = new Blob([fileQuery.data], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = selected.descriptor.fileName
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  }

  if (!selected) {
    const shown = gapFilter ? files.filter((file) => file.gap > 0) : files
    return (
      <div className="handbook">
        <div className="hero">
          <h1>{t('gamedata2.h1')}</h1>
          <p className="lede">{t('gamedata2.lede')}</p>
        </div>
        <Explain html={t('gamedata2.explain')} />

        <div className="filters" style={{ margin: '14px 0' }}>
          <button type="button" className="chip" aria-pressed={!gapFilter} onClick={() => setParam('only')}>
            {t('gamedata2.allFiles')}<span className="n">{files.length}</span>
          </button>
          <button type="button" className="chip" aria-pressed={gapFilter} onClick={() => setParam('only', 'gap')}>
            {t('gamedata2.hasGap')}<span className="n">{files.filter((file) => file.gap > 0).length}</span>
          </button>
          {indexQuery.data && version && (
            <Select
              size="small"
              style={{ minWidth: 110 }}
              value={version}
              onChange={(value: string) => setParam('build', value)}
              options={indexQuery.data.versions.map((entry) => ({ value: entry.gameVersion, label: entry.gameVersion }))}
            />
          )}
        </div>

        {indexQuery.error && <Alert type="error" showIcon message={t('gamedata.indexError')} description={indexQuery.error.message} />}
        {indexQuery.isLoading && (
          <div className="filegrid">
            {[0, 1, 2, 3, 4, 5].map((row) => (
              <div className="filecard" key={row}><Skeleton active paragraph={{ rows: 2 }} title={false} /></div>
            ))}
          </div>
        )}

        <div className="filegrid">
          {shown.map((file) => (
            <button
              type="button"
              className="filecard"
              key={file.descriptor.id}
              onClick={() => setParam('file', file.descriptor.id)}
            >
              <span className="fh">
                <span className="pl">{file.descriptor.plugin}</span>
                <span className="fmt">{formatLabel(file.descriptor.language)}</span>
              </span>
              <span className="fn">{file.descriptor.fileName}</span>
              <span className="meter">
                <i style={{ width: `${file.percent}%` }} />
                {file.gap > 0 && <i className="gapbar" style={{ width: `${100 - file.percent}%` }} />}
              </span>
              <span className="fs">
                <span>{t('gamedata2.keysOf', { covered: file.covered, total: file.total })}</span>
                {file.updated > 0 && <span className="updn">{t('gamedata2.changed', { count: file.updated })}</span>}
                {file.gap > 0
                  ? <span className="gapn">{t('gamedata2.missing', { count: file.gap })}</span>
                  : <span>{t('gamedata2.complete')}</span>}
              </span>
            </button>
          ))}
        </div>
      </div>
    )
  }

  const descriptor = selected.descriptor
  const sizeKb = (descriptor.content.size / 1024).toFixed(1)

  return (
    <div className="handbook">
      <button type="button" className="backlink" onClick={() => { setParam('file'); setShowDetail(false) }}>
        ← {t('gamedata2.allFiles')}
      </button>

      <section className="panel" style={{ marginBottom: 0 }}>
        <div className="fdhead">
          <span className="who">
            <span className="p1">{descriptor.plugin}</span>
            <span className="p2">{descriptor.id}</span>
            <span className="p3">
              <span>{formatLabel(descriptor.language)}</span>
              <span>{sizeKb} KB</span>
              {fileQuery.data && <span>{t('gamedata2.lines', { count: lineCount })}</span>}
              <span>{t('gamedata2.keysFilled', { covered: selected.covered, total: selected.total })}</span>
              {selected.gap > 0 && (
                <span style={{ color: 'var(--warn)' }}>{t('gamedata2.notProduced', { count: selected.gap })}</span>
              )}
            </span>
          </span>
          <span className="fdacts">
            <button type="button" className="btn" aria-pressed={fullWidth} onClick={() => setFullWidth(!fullWidth)}>
              {fullWidth ? t('gamedata2.exitFull') : t('gamedata2.full')}
            </button>
            <button
              type="button"
              className="btn"
              disabled={!fileQuery.data}
              onClick={() => void navigator.clipboard?.writeText(fileQuery.data ?? '')}
            >
              {t('gamedata2.copyText')}
            </button>
            <button type="button" className="btn primary" disabled={!fileQuery.data} onClick={() => void download()}>
              {t('gamedata.download')}
            </button>
          </span>
        </div>

        {fileQuery.error && <Alert className="gamedata-inline-alert" type="error" showIcon message={t('gamedata.fileError')} description={fileQuery.error.message} />}
        {fileQuery.isLoading && <div style={{ padding: 16 }}><Skeleton active paragraph={{ rows: 16 }} title={false} /></div>}

        {fileQuery.data && (
          <FileView
            descriptor={descriptor}
            content={fileQuery.data}
            metadata={metadataQuery.data}
            find={find}
            marks={marks}
            focusLine={focusLine}
            onFind={(value) => setParam('find', value)}
            onMarks={(value) => setParam('marks', value ? '1' : undefined)}
          />
        )}

        <button type="button" className="morelink" onClick={() => setShowDetail(!showDetail)}>
          {showDetail ? t('gamedata2.hideDetail') : t('gamedata2.showDetail')}
        </button>

        {showDetail && (
          <>
            <div className="fdtabs" role="tablist">
              {(['changes', 'keys', 'history'] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={detailTab === tab}
                  onClick={() => setDetailTab(tab)}
                >
                  {t(`gamedata2.tab.${tab}`)}
                  <span className="cnt">
                    {tab === 'changes' ? changed.length : tab === 'keys' ? missing.length : fragility.length}
                  </span>
                </button>
              ))}
            </div>
            <div className="fdpane pad">
              {metadataQuery.isLoading && <Skeleton active paragraph={{ rows: 4 }} title={false} />}
              {!descriptor.metadata && <p className="plain">{t('gamedata.noMetadata')}</p>}
              {detailTab === 'changes' && (
                changed.length === 0
                  ? <p className="plain">{t('gamedata2.noChanges')}</p>
                  : <div>
                      {changed.map((key) => (
                        <details className="chgrow" key={key.name}>
                          <summary>
                            <span className="ck">{key.name}</span>
                            <span className="cw">{key.changes.map((change) => change.path[change.path.length - 1]).join(', ')}</span>
                            {key.line !== undefined && (
                              <button
                                type="button"
                                className="gobtn"
                                onClick={(event) => {
                                  event.preventDefault()
                                  setParam('marks', '1')
                                  setParam('line', String(key.line))
                                }}
                              >
                                {t('gamedata2.goToLine', { line: key.line })}
                              </button>
                            )}
                          </summary>
                          <ChangeRows changes={key.changes} />
                        </details>
                      ))}
                    </div>
              )}
              {detailTab === 'history' && (
                fragility.length === 0
                  ? <p className="plain">{t('gamedata2.noHistory')}</p>
                  : <>
                      <p className="plain">{t('gamedata2.historyIntro', { builds: historyQuery.data?.builds.length ?? 0 })}</p>
                      <div className="tablewrap">
                        <table className="plaintable">
                          <thead>
                            <tr>
                              <th>{t('gamedata2.hKey')}</th>
                              <th>{t('gamedata2.hLast')}</th>
                              <th>{t('gamedata2.hChanges')}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {fragility.map((row) => (
                              <tr key={row.name}>
                                <td className="mono">{row.name}</td>
                                <td className="mono">
                                  {row.last ?? <span style={{ color: 'var(--ok)' }}>{t('gamedata2.hStable')}</span>}
                                </td>
                                <td className="mono">
                                  <span className="fragbar">
                                    {Array.from({ length: Math.max(1, row.observed) }, (_unused, index) => (
                                      <i className={index < row.changes ? 'on' : undefined} key={index} />
                                    ))}
                                  </span>
                                  {' '}{row.changes} / {row.observed}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </>
              )}
              {detailTab === 'keys' && (
                missing.length === 0
                  ? <p className="plain">{t('gamedata2.noGap')}</p>
                  : <>
                      <p className="plain">{t('gamedata2.gapSummary', { count: missing.length })}</p>
                      <div className="gapkeys">
                        {missing.map((name) => <span key={name}>{name}</span>)}
                      </div>
                    </>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  )
}
