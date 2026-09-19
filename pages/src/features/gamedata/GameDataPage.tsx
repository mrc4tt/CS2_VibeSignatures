import { useQuery } from '@tanstack/react-query'
import { copyText } from '../../ui/clipboard'
import { saveText } from '../../ui/download'
import { Alert, Button, ChipGroup, Select, Skeleton } from '../../ui/primitives'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Explain } from '../../components/Explain'
import { buildDate, differencesSince, getSiteHistory, lastChangedIn } from '../../api/siteData'
import { formatAgo, formatDay, formatWhen } from '../../components/whenText'
import { getGameDataFile, getGameDataIndex, getGameDataMetadata } from './data'
import { changedKeys, describeFiles, formatLabel, notProducedKeys } from './fileModel'
import { FileView } from './FileView'
import { Pattern } from '../symbols/Pattern'
import type { GameDataChange } from './types'

type DetailTab = 'changes' | 'keys' | 'history' | 'since'

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
  const { t, i18n } = useTranslation()
  const language = i18n.resolvedLanguage ?? 'en'
  const [params, setParams] = useSearchParams()
  const [detailTab, setDetailTab] = useState<DetailTab>('since')
  const [showDetail, setShowDetail] = useState(false)
  const [fullWidth, setFullWidth] = useState(false)

  /**
   * `push` for anything that changes what you are looking at, so the browser's
   * back button returns to the file list or the previous file; `replace` for
   * typing, which would otherwise put one history entry per keystroke.
   */
  const setParam = (key: string, value?: string, push = false) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: !push })
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
  const historyQuery = useQuery({
    queryKey: ['history'],
    queryFn: ({ signal }) => getSiteHistory(signal),
    staleTime: Infinity,
  })
  const history = historyQuery.data
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

  // history.json keys files by their path inside gamedata/<build>/, which is the
  // descriptor id, so no mapping is needed.
  const keyHistory = selected ? history?.files[selected.descriptor.id] : undefined
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

  const sinceBuild = params.get('since') ?? undefined
  const differences = useMemo(
    () => (selected && sinceBuild ? differencesSince(history, selected.descriptor.id, sinceBuild) : []),
    [history, selected, sinceBuild],
  )
  const fileLastChanged = selected ? lastChangedIn(history, selected.descriptor.id) : undefined

  const changed = useMemo(() => changedKeys(metadataQuery.data), [metadataQuery.data])
  const missing = useMemo(() => notProducedKeys(metadataQuery.data), [metadataQuery.data])

  async function download(): Promise<void> {
    if (!selected || !fileQuery.data) return
    saveText(fileQuery.data, selected.descriptor.fileName)
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
          <ChipGroup
            label={t('chips.files')}
            value={gapFilter ? 'gap' : 'all'}
            onValueChange={(next) => setParam('only', next === 'gap' ? 'gap' : undefined)}
            items={[
              { value: 'all', label: t('gamedata2.allFiles'), count: files.length },
              { value: 'gap', label: t('gamedata2.hasGap'), count: files.filter((file) => file.gap > 0).length },
            ]}
          />
          {indexQuery.data && version && (
            <>
              <label htmlFor="gamedata-build" className="sr-only">{t('gamedata.build')}</label>
              <Select
                id="gamedata-build"
                className="min-w-[110px] px-2 py-1 font-mono text-[12.5px]"
                value={version}
                onChange={(event) => setParam('build', event.target.value)}
              >
                {indexQuery.data.versions.map((entry) => (
                  <option key={entry.gameVersion} value={entry.gameVersion}>{entry.gameVersion}</option>
                ))}
              </Select>
            </>
          )}
        </div>

        {indexQuery.error && <Alert tone="bad" title={t('gamedata.indexError')} description={indexQuery.error.message} />}
        {indexQuery.isLoading && (
          <div className="filegrid">
            {[0, 1, 2, 3, 4, 5].map((row) => (
              <div className="filecard" key={row}><Skeleton rows={2} /></div>
            ))}
          </div>
        )}

        <div className="filegrid">
          {shown.map((file) => (
            <button
              type="button"
              className="filecard"
              key={file.descriptor.id}
              onClick={() => setParam('file', file.descriptor.id, true)}
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
              <span className="fw">
                {(() => {
                  const changed = lastChangedIn(history, file.descriptor.id)
                  const when = buildDate(history, changed)
                  if (!changed) return t('gamedata2.neverChanged')
                  return t('gamedata2.updatedIn', {
                    build: changed,
                    ago: formatAgo(when ?? undefined, language) || formatDay(when ?? undefined, language),
                  })
                })()}
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
      <button type="button" className="backlink" onClick={() => { setParam('file', undefined, true); setShowDetail(false) }}>
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
            <Button aria-pressed={fullWidth} onClick={() => setFullWidth(!fullWidth)}>
              {fullWidth ? t('gamedata2.exitFull') : t('gamedata2.full')}
            </Button>
            <Button
              disabled={!fileQuery.data}
              onClick={() => void copyText(fileQuery.data ?? '', { ok: t('clipboard.ok'), failed: t('clipboard.failed') })}
            >
              {t('gamedata2.copyText')}
            </Button>
            <Button variant="primary" disabled={!fileQuery.data} onClick={() => void download()}>
              {t('gamedata.download')}
            </Button>
          </span>
        </div>

        <div className="fdhist">
          <div className="hrow">
            <span className="hl">{t('gamedata2.whenBuilt')}</span>
            <span className="hv">
              {formatWhen(buildDate(history, version) ?? undefined, language) || version}
              <span className="ago">{formatAgo(buildDate(history, version) ?? undefined, language)}</span>
            </span>
          </div>
          <div className="hrow">
            <span className="hl">{t('gamedata2.whenChanged')}</span>
            <span className="hv">
              {fileLastChanged
                ? <>
                    {t('gamedata2.changedInBuild', { build: fileLastChanged })}
                    <span className="ago">
                      {formatAgo(buildDate(history, fileLastChanged) ?? undefined, language)}
                    </span>
                    {fileLastChanged !== version && (
                      <span className="subj">{t('gamedata2.unchangedSince', { build: version })}</span>
                    )}
                  </>
                : <span style={{ fontFamily: 'var(--sans)' }}>{t('gamedata2.neverChanged')}</span>}
            </span>
          </div>
        </div>

        {fileQuery.error && <Alert className="gamedata-inline-alert" tone="bad" title={t('gamedata.fileError')} description={fileQuery.error.message} />}
        {fileQuery.isLoading && <div style={{ padding: 16 }}><Skeleton rows={16} /></div>}

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
              {(['since', 'changes', 'keys', 'history'] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={detailTab === tab}
                  onClick={() => setDetailTab(tab)}
                >
                  {t(`gamedata2.tab.${tab}`)}
                  <span className="cnt">
                    {tab === 'changes' ? changed.length
                      : tab === 'keys' ? missing.length
                        : tab === 'history' ? fragility.length
                          : sinceBuild ? differences.length : ''}
                  </span>
                </button>
              ))}
            </div>
            <div className="fdpane pad">
              {metadataQuery.isLoading && <Skeleton rows={4} />}
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
              {detailTab === 'since' && (
                <>
                  <p className="plain prose">{t('gamedata2.sinceIntro')}</p>
                  <ChipGroup
                    className="filters"
                    label={t('chips.since')}
                    allowEmpty
                    value={sinceBuild}
                    onValueChange={(next) => setParam('since', next)}
                    items={(history?.builds ?? []).slice().reverse().filter((b) => b.gameVersion !== version).map((b) => ({
                      value: b.gameVersion,
                      label: b.gameVersion,
                      count: formatDay(b.publishedAt ?? undefined, language),
                    }))}
                  />
                  {!sinceBuild && <p className="plain">{t('gamedata2.sincePick')}</p>}
                  {sinceBuild && differences.length === 0 && (
                    <p className="plain">{t('gamedata2.sinceNone', { build: sinceBuild })}</p>
                  )}
                  {sinceBuild && differences.length > 0 && (
                    <>
                      <p className="plain">
                        <b>{t('gamedata2.sinceCount', { count: differences.length, build: sinceBuild })}</b>
                      </p>
                      {differences.map((difference) => (
                        <details className="chgrow" key={difference.key}>
                          <summary>
                            <span className="ck">{difference.key}</span>
                            <span className="cw">
                              {!difference.before ? t('gamedata2.sinceAdded')
                                : !difference.after ? t('gamedata2.sinceRemoved')
                                  : t('gamedata2.sinceChanged')}
                            </span>
                          </summary>
                          <div className="cbody">
                            {(['linux', 'windows'] as const).map((platform, index) => {
                              const before = difference.before?.[index]
                              const after = difference.after?.[index]
                              if (JSON.stringify(before) === JSON.stringify(after)) return null
                              return (
                                <div className="chgline" key={platform}>
                                  <span className="lab">{platform}</span>
                                  <span className="o">- <ChangeValue value={before ?? null} /></span>
                                  <span className="n2">+ <ChangeValue value={after ?? null} /></span>
                                </div>
                              )
                            })}
                          </div>
                        </details>
                      ))}
                    </>
                  )}
                </>
              )}
              {detailTab === 'history' && (
                fragility.length === 0
                  ? <p className="plain">{t('gamedata2.noHistory')}</p>
                  : <>
                      <p className="plain">{t('gamedata2.historyIntro', { builds: history?.builds.length ?? 0 })}</p>
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
