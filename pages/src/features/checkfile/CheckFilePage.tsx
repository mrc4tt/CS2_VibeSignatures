import { useQuery } from '@tanstack/react-query'
import { Alert, Select, Skeleton } from 'antd'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Explain } from '../../components/Explain'
import { getSiteHistory } from '../../api/siteData'
import { Pattern } from '../symbols/Pattern'
import { parseGameData, type FileValue, type GameDataFormat } from './parse'
import { bestFit, identifyFile, keyVerdicts, scoreBuilds, summarise, type KeyState } from './verdict'

interface Loaded {
  name: string
  format: GameDataFormat
  values: Map<string, FileValue>
}

const STATES: KeyState[] = ['outdated', 'current', 'unknown', 'absent']
/** Signatures are long; a page of them at a time keeps the list readable. */
const ROWS = 25

function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <em>—</em>
  const text = typeof value === 'string' ? value : String(value)
  return /^[0-9A-Fa-f?\s\\x]{8,}$/.test(text) ? <Pattern pattern={text} /> : <span>{text}</span>
}

export function CheckFilePage() {
  const { t } = useTranslation()
  const { data: history, isLoading } = useQuery({ queryKey: ['site-history'], queryFn: ({ signal }) => getSiteHistory(signal) })
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [chosenFile, setChosenFile] = useState<string | null>(null)
  const [show, setShow] = useState<KeyState>('outdated')
  const [limit, setLimit] = useState(ROWS)
  const [dragging, setDragging] = useState(false)

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
  const filtered = useMemo(() => verdicts.filter((verdict) => verdict.state === show), [verdicts, show])
  const shown = filtered.slice(0, limit)

  async function accept(input: File | string, name: string) {
    setError(null)
    setChosenFile(null)
    setLimit(ROWS)
    try {
      const text = typeof input === 'string' ? input : await input.text()
      if (!text.trim()) throw new Error('empty')
      const parsed = parseGameData(text)
      // A file with no platform entries is readable and still useless here, and
      // it is the likeliest mistake - a README, the wrong file from the plugin
      // folder. Saying that is more use than offering a plugin to compare it
      // against. The KeyValues reader never throws, so this is the only way an
      // unusable file shows up.
      if (parsed.values.size === 0) {
        setLoaded(null)
        setError(t('check.noEntries', { format: parsed.format.toUpperCase() }))
        return
      }
      setLoaded({ name, format: parsed.format, values: parsed.values })
    } catch {
      setLoaded(null)
      setError(t('check.unreadable'))
    }
  }

  if (isLoading) return <div className="handbook"><Skeleton active paragraph={{ rows: 6 }} /></div>

  const behind = fit && newest && fit.build !== newest
    ? history!.builds.length - 1 - history!.builds.findIndex((entry) => entry.gameVersion === fit.build)
    : 0

  return (
    <div className="handbook">
      <div className="hero">
        <h1>{t('check.h1')}</h1>
        <p className="lede">{t('check.lede', { build: newest ?? '—' })}</p>
      </div>

      <section className="panel">
        <div className="panel-body">
          <div
            className="dropzone"
            data-dragging={dragging || undefined}
            onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault()
              setDragging(false)
              const dropped = event.dataTransfer.files[0]
              if (dropped) void accept(dropped, dropped.name)
            }}
          >
            <p className="dzmain">{t('check.drop')}</p>
            <label className="btn primary">
              {t('check.browse')}
              <input
                type="file"
                hidden
                onChange={(event) => {
                  const picked = event.target.files?.[0]
                  if (picked) void accept(picked, picked.name)
                }}
              />
            </label>
            <p className="dznote">{t('check.private')}</p>
          </div>

          <details className="pastebox">
            <summary>{t('check.paste')}</summary>
            <textarea
              rows={6}
              spellCheck={false}
              placeholder={'{ "ClientPrint": { "signatures": { "linux": "55 48 …" } } }'}
              onChange={(event) => {
                const text = event.target.value
                if (text.trim().length > 40) void accept(text, t('check.pasted'))
              }}
            />
          </details>

          <Explain>{t('check.explain')}</Explain>
        </div>
      </section>

      {error && <Alert type="error" showIcon message={error} />}

      {loaded && (
        <section className="panel">
          <header>
            <h2>{loaded.name}</h2>
            <span className="chip">{t('check.readAs', { format: loaded.format.toUpperCase(), keys: loaded.values.size })}</span>
          </header>
          <div className="panel-body">
            {!file && (
              <Alert
                type="warning"
                showIcon
                message={t('check.unknownPlugin')}
                description={
                  <>
                    {identification?.best
                      ? t('check.closest', { plugin: identification.best.plugin, shared: identification.best.shared, keys: loaded.values.size })
                      : t('check.noOverlap')}
                    <div className="pickplugin">
                      <Select
                        style={{ minWidth: 260 }}
                        placeholder={t('check.pick')}
                        options={Object.keys(history?.files ?? {}).sort().map((path) => ({
                          value: path,
                          label: path.split('/')[0],
                        }))}
                        onChange={(value: string) => setChosenFile(value)}
                      />
                    </div>
                  </>
                }
              />
            )}

            {file && (
              <>
                {fit && (
                  <Alert
                    type={summary.outdated === 0 ? 'success' : 'warning'}
                    showIcon
                    message={
                      summary.outdated === 0
                        ? t('check.upToDate', { build: newest })
                        : t('check.needsWork', { keys: summary.outdated, build: newest })
                    }
                    description={
                      <span className="fitnote">
                        {t('check.identifiedAs')} <strong>{file.split('/')[0]}</strong>
                        {identification?.decisive && !chosenFile
                          ? ` (${t('check.sharedKeys', { shared: identification.best!.shared, keys: loaded.values.size })})`
                          : ''}
                        {'. '}
                        {behind === 0
                          ? t('check.fitCurrent', { build: fit.build })
                          : t('check.fitBehind', { build: fit.build, builds: behind })}
                        {fit.tied ? ` ${t('check.tied', { oldest: fit.oldest, build: fit.build })}` : ''}
                      </span>
                    }
                  />
                )}

                <div className="statgrid">
                  {STATES.map((state) => (
                    <button
                      key={state}
                      type="button"
                      className={`stat kstat${state === 'outdated' && summary.outdated ? ' warnv' : ''}${state === 'current' ? ' okv' : ''}`}
                      data-on={show === state || undefined}
                      disabled={summary[state] === 0}
                      onClick={() => { setShow(state); setLimit(ROWS) }}
                    >
                      <span className="v">{summary[state]}</span>
                      <span className="l">{t(`check.state.${state}`)}</span>
                    </button>
                  ))}
                </div>

                <p className="plain prose dznote">{t(`check.meaning.${show}`)}</p>

                <div className="krows">
                  {shown.map((verdict) => (
                    <details className="krow" data-state={verdict.state} key={`${verdict.state}-${verdict.key}`}>
                      <summary>
                        <code className="kname">{verdict.key}</code>
                        {(['linux', 'windows'] as const).map((platform) => {
                          const ok = platform === 'linux' ? verdict.linuxOk : verdict.windowsOk
                          if (verdict.state !== 'outdated' && verdict.state !== 'current') return null
                          if (ok === undefined) return null
                          return (
                            <span className={`pbadge ${ok ? 'ok' : 'bad'}`} key={platform}>
                              {t(`check.platform.${platform}`)}
                            </span>
                          )
                        })}
                      </summary>
                      <div className="kdiff">
                        {(['linux', 'windows'] as const).map((platform, index) => {
                          const mineValue = verdict.mine?.[platform]
                          const theirsValue = verdict.expected?.[index]
                          if (mineValue == null && theirsValue == null) return null
                          const ok = platform === 'linux' ? verdict.linuxOk : verdict.windowsOk
                          return (
                            <div className="kline" key={platform}>
                              <span className="pl">{t(`check.platform.${platform}`)}</span>
                              <span className="vals">
                                {verdict.state === 'outdated' && ok === false ? (
                                  <>
                                    <span className="was"><span className="tag">{t('check.yours')}</span> <Value value={mineValue} /></span>
                                    <span className="now"><span className="tag">{t('check.published')}</span> <Value value={theirsValue} /></span>
                                  </>
                                ) : (
                                  <span className="same"><Value value={verdict.state === 'unknown' ? mineValue : theirsValue} /></span>
                                )}
                              </span>
                            </div>
                          )
                        })}
                      </div>
                    </details>
                  ))}
                  {shown.length === 0 && <p className="plain">{t('check.none')}</p>}
                </div>

                {filtered.length > shown.length && (
                  <button type="button" className="btn" onClick={() => setLimit(filtered.length)}>
                    {t('check.showAll', { count: filtered.length - shown.length })}
                  </button>
                )}
              </>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
