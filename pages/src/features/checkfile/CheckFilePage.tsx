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

  async function accept(input: File | string, name: string) {
    setError(null)
    setChosenFile(null)
    try {
      const text = typeof input === 'string' ? input : await input.text()
      if (!text.trim()) throw new Error('empty')
      const parsed = parseGameData(text)
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
                <p className="plain prose">
                  {identification?.decisive && !chosenFile
                    ? t('check.identified', { plugin: file.split('/')[0], shared: identification.best!.shared, keys: loaded.values.size })
                    : t('check.comparing', { plugin: file.split('/')[0] })}
                </p>

                {fit && (
                  <Alert
                    type={behind === 0 && summary.outdated === 0 ? 'success' : 'warning'}
                    showIcon
                    message={
                      behind === 0
                        ? t('check.isCurrent', { build: fit.build })
                        : t('check.isBehind', { build: fit.build, builds: behind, newest })
                    }
                    description={
                      <>
                        {t('check.matchDetail', { matched: fit.matched, comparable: fit.comparable, build: fit.build })}
                        {fit.tied && <> {t('check.tied', { oldest: fit.oldest, build: fit.build })}</>}
                      </>
                    }
                  />
                )}

                <div className="filters">
                  {STATES.map((state) => (
                    <button
                      key={state}
                      type="button"
                      className="chip"
                      data-on={show === state || undefined}
                      onClick={() => setShow(state)}
                    >
                      {t(`check.state.${state}`)} <span className="cnt">{summary[state]}</span>
                    </button>
                  ))}
                </div>

                <div className="cbody">
                  {verdicts.filter((verdict) => verdict.state === show).map((verdict) => (
                    <div className="chgline" key={`${verdict.state}-${verdict.key}`}>
                      <span className="lab">{verdict.key}</span>
                      {verdict.state === 'outdated' && (
                        <>
                          <span className="o">- <Value value={verdict.mine?.linux} /> / <Value value={verdict.mine?.windows} /></span>
                          <span className="n2">+ <Value value={verdict.expected?.[0]} /> / <Value value={verdict.expected?.[1]} /></span>
                        </>
                      )}
                      {verdict.state === 'current' && (
                        <span className="n2"><Value value={verdict.expected?.[0]} /> / <Value value={verdict.expected?.[1]} /></span>
                      )}
                      {verdict.state === 'unknown' && (
                        <span className="o"><Value value={verdict.mine?.linux} /> / <Value value={verdict.mine?.windows} /></span>
                      )}
                      {verdict.state === 'absent' && (
                        <span className="n2"><Value value={verdict.expected?.[0]} /> / <Value value={verdict.expected?.[1]} /></span>
                      )}
                    </div>
                  ))}
                  {verdicts.filter((verdict) => verdict.state === show).length === 0 && (
                    <p className="plain">{t('check.none')}</p>
                  )}
                </div>

                <p className="plain prose dznote">{t(`check.meaning.${show}`)}</p>
              </>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
