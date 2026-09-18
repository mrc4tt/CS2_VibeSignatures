import { useQuery } from '@tanstack/react-query'
import { FileCheckIcon } from '../../ui/icons'
import { Alert, Select, Skeleton } from '../../ui/primitives'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Explain } from '../../components/Explain'
import { getSiteHistory } from '../../api/siteData'
import { getGameDataFile, getGameDataIndex } from '../gamedata/data'
import { Pattern } from '../symbols/Pattern'
import { parseGameData, type FileValue, type GameDataFormat } from './parse'
import { patchFile } from './patch'
import { bestFit, identifyFile, keyVerdicts, scoreBuilds, summarise, type KeyState } from './verdict'

interface Loaded {
  name: string
  format: GameDataFormat
  /** Kept so the fixed file can be produced from the original bytes. */
  text: string
  values: Map<string, FileValue>
}

const STATES: KeyState[] = ['outdated', 'current', 'unknown', 'absent']

/** One tone per state, so a number reads the same here as anywhere else on the site. */
const STATE_TONE: Record<KeyState, 'bad' | 'ok' | 'warn' | 'neutral'> = {
  outdated: 'bad',
  current: 'ok',
  unknown: 'warn',
  absent: 'neutral',
}
const STATE_NUMBER = { bad: 'text-bad', ok: 'text-ok', warn: 'text-warn', neutral: 'text-ink' } as const
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
  const [mode, setMode] = useState<'file' | 'paste'>('file')
  const [pasted, setPasted] = useState('')
  const [copied, setCopied] = useState(false)

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
  // Only fetched once a file has been identified: someone who never drops a file
  // should not pay for the gamedata index.
  const { data: index } = useQuery({
    queryKey: ['gamedata-index'],
    queryFn: ({ signal }) => getGameDataIndex(signal),
    enabled: Boolean(file),
  })
  const publishedFile = useMemo(
    () => index?.versions.find((version) => version.gameVersion === newest)?.files.find((entry) => entry.id === file),
    [index, newest, file],
  )
  const patched = useMemo(
    () => (loaded && summary.outdated > 0 ? patchFile(loaded.text, verdicts) : null),
    [loaded, verdicts, summary.outdated],
  )
  const filtered = useMemo(() => verdicts.filter((verdict) => verdict.state === show), [verdicts, show])
  const shown = filtered.slice(0, limit)

  function save(text: string, name: string) {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = name
    anchor.click()
    URL.revokeObjectURL(url)
  }

  async function accept(input: File | string, name: string) {
    setError(null)
    setChosenFile(null)
    setLimit(ROWS)
    setCopied(false)
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
      setLoaded({ name, format: parsed.format, text, values: parsed.values })
    } catch {
      setLoaded(null)
      setError(t('check.unreadable'))
    }
  }

  if (isLoading) return <div className="handbook"><Skeleton rows={6} /></div>

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
        <header>
          <h2>{t('check.inputH')}</h2>
          <span className="sub">{t('check.private')}</span>
        </header>
        <div className="panel-body">
          {/* Two ways in, given the same weight. They used to be a drop zone and
              a collapsed grey line of text underneath it, which made pasting
              look like an afterthought and left the explain box as the biggest
              thing on the page. */}
          <div className="segmented" role="tablist">
            {(['file', 'paste'] as const).map((option) => (
              <button
                key={option}
                type="button"
                role="tab"
                aria-selected={mode === option}
                data-on={mode === option || undefined}
                onClick={() => setMode(option)}
              >
                {t(`check.mode.${option}`)}
              </button>
            ))}
          </div>

          {mode === 'file' ? (
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
              <p className="dznote">{t('check.examples')}</p>
            </div>
          ) : (
            <div className="pasteform">
              <label className="plabel" htmlFor="check-paste">{t('check.pasteLabel')}</label>
              <textarea
                id="check-paste"
                rows={9}
                spellCheck={false}
                value={pasted}
                placeholder={'{\n  "ClientPrint": {\n    "signatures": { "linux": "55 48 89 E5 …", "windows": "40 53 …" }\n  }\n}'}
                onChange={(event) => setPasted(event.target.value)}
                onPaste={(event) => {
                  const text = event.clipboardData.getData('text')
                  if (text.trim().length > 40) {
                    setPasted(text)
                    void accept(text, t('check.pasted'))
                  }
                }}
              />
              <div className="pactions">
                <button
                  type="button"
                  className="btn primary"
                  disabled={pasted.trim().length < 10}
                  onClick={() => void accept(pasted, t('check.pasted'))}
                >
                  {t('check.checkIt')}
                </button>
                {pasted && (
                  <button type="button" className="btn" onClick={() => { setPasted(''); setLoaded(null); setError(null) }}>
                    {t('check.clear')}
                  </button>
                )}
              </div>
            </div>
          )}

          <Explain>{t('check.explain')}</Explain>
        </div>
      </section>

      {error && <Alert tone="bad" title={error} />}

      {loaded && (
        <section className="panel">
          {/* The file you dropped and the verdict on it, side by side: which file
              this is and whether it still holds are the same question. */}
          <div className="flex flex-wrap items-stretch gap-4 p-4">
            <div className="flex min-w-0 grow items-center gap-3.5 rounded-[12px] border border-rule-strong bg-card px-4 py-3.5">
              <span className="flex size-[38px] shrink-0 items-center justify-center rounded-[9px] bg-card-2 text-[color:var(--accent-text)]">
                <FileCheckIcon size={18} />
              </span>
              <span className="flex min-w-0 grow flex-col gap-0.5">
                <span className="truncate font-mono text-[14px] text-ink">{loaded.name}</span>
                <span className="text-[12px] text-muted">
                  {t('check.readAs', { format: loaded.format.toUpperCase(), keys: loaded.values.size })}
                </span>
              </span>
            </div>
            {file && fit && (
              <div
                className={[
                  'flex w-full shrink-0 flex-col justify-center gap-1 rounded-[12px] border px-4 py-3.5 lg:w-[310px]',
                  summary.outdated === 0 ? 'border-ok-line bg-ok-bg' : 'border-warn-line bg-warn-bg',
                ].join(' ')}
              >
                <span className={summary.outdated === 0 ? 'font-display text-[16px] font-bold text-ok' : 'font-display text-[16px] font-bold text-warn'}>
                  {summary.outdated === 0
                    ? t('check.upToDate', { build: newest })
                    : t('check.needsWork', { keys: summary.outdated, build: newest })}
                </span>
                <span className="text-[12.5px] leading-relaxed text-ink-2">
                  {t('check.identifiedAs')} <strong>{file.split('/')[0]}</strong>
                </span>
              </div>
            )}
          </div>
          <div className="panel-body">
            {!file && (
              <Alert
                tone="warn"
               
                title={t('check.unknownPlugin')}
                description={
                  <>
                    {identification?.best
                      ? t('check.closest', { plugin: identification.best.plugin, shared: identification.best.shared, keys: loaded.values.size })
                      : t('check.noOverlap')}
                    <div className="pickplugin">
                      <label htmlFor="check-plugin" className="sr-only">{t('check.pick')}</label>
                      <Select
                        id="check-plugin"
                        className="min-w-[260px]"
                        defaultValue=""
                        onChange={(event) => setChosenFile(event.target.value)}
                      >
                        <option value="" disabled>{t('check.pick')}</option>
                        {Object.keys(history?.files ?? {}).sort().map((path) => (
                          <option key={path} value={path}>{path.split('/')[0]}</option>
                        ))}
                      </Select>
                    </div>
                  </>
                }
              />
            )}

            {file && (
              <>
                {/* The headline verdict moved into the bar above; what is left
                    here is which build your file looks like and how far back
                    that is - the part you act on. */}
                {fit && (
                  <p className="fitnote m-0 text-[12.5px] leading-relaxed text-muted">
                    {identification?.decisive && !chosenFile
                      ? `${t('check.sharedKeys', { shared: identification.best!.shared, keys: loaded.values.size })}. `
                      : ''}
                    {behind === 0
                      ? t('check.fitCurrent', { build: fit.build })
                      : t('check.fitBehind', { build: fit.build, builds: behind })}
                    {fit.tied ? ` ${t('check.tied', { oldest: fit.oldest, build: fit.build })}` : ''}
                  </p>
                )}

                {patched && patched.applied > 0 && (
                  <div className="fixit">
                    <div className="fixhead">
                      <strong>{t('check.fixH')}</strong>
                      <span>{t('check.fixSub', { applied: patched.applied })}</span>
                    </div>
                    <ol className="fixsteps">
                      <li>{t('check.step1')}</li>
                      <li>{t('check.step2')}</li>
                      <li>{t('check.step3')}</li>
                    </ol>
                    <div className="pactions">
                      <button
                        type="button"
                        className="btn primary"
                        onClick={() => save(patched.text, `${newest}-${loaded.name}`)}
                      >
                        {t('check.download')}
                      </button>
                      <button
                        type="button"
                        className="btn"
                        onClick={() => { void navigator.clipboard?.writeText(patched.text); setCopied(true) }}
                      >
                        {copied ? t('check.copied') : t('check.copy')}
                      </button>
                    </div>
                    {patched.skipped.length > 0 && (
                      <p className="dznote">
                        {t('check.manual', { count: patched.skipped.length })}{' '}
                        {[...new Set(patched.skipped.map((entry) => entry.key))].join(', ')}
                      </p>
                    )}
                  </div>
                )}

                {publishedFile && (
                  <p className="dznote takeours">
                    {t('check.orTakeOurs')}{' '}
                    <button
                      type="button"
                      className="linkish"
                      onClick={() => {
                        void getGameDataFile(publishedFile).then((text) =>
                          save(text, `${newest}-${publishedFile.fileName}`),
                        )
                      }}
                    >
                      {t('check.downloadPublished', { name: publishedFile.fileName })}
                    </button>
                  </p>
                )}

                {fit && behind === 0 && fit.share < 1 && (
                  <Alert
                    tone="qualify"
                   
                    title={t('check.maybeNewer')}
                    description={t('check.maybeNewerWhy', { build: newest })}
                  />
                )}

                {/*
                  Four states, and they are this checker's own: it compares your
                  file against published values, so it can say a value is current
                  or out of date, but not the things verify_plugin_gamedata says
                  after scanning the binaries. Naming them its way would claim a
                  distinction this data cannot support.
                */}
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  {STATES.map((state) => {
                    const tone = STATE_TONE[state]
                    const active = show === state
                    return (
                      <button
                        key={state}
                        type="button"
                        aria-pressed={active}
                        disabled={summary[state] === 0}
                        onClick={() => { setShow(state); setLimit(ROWS) }}
                        className={[
                          'flex flex-col items-start gap-1 rounded-[12px] border p-4 text-left transition-colors',
                          'disabled:cursor-not-allowed disabled:opacity-45',
                          active ? 'border-rule-strong bg-card-2' : 'border-rule bg-card hover:border-rule-strong',
                        ].join(' ')}
                      >
                        {/* `v` is the hook CheckFilePage.test.tsx reads the count through. */}
                        <span className={`v font-display text-[28px] font-bold leading-none ${STATE_NUMBER[tone]}`}>
                          {summary[state]}
                        </span>
                        <span className="text-[12px] uppercase tracking-wide text-muted">{t(`check.state.${state}`)}</span>
                      </button>
                    )
                  })}
                </div>

                <p className="plain prose dznote">{t(`check.meaning.${show}`)}</p>

                {/*
                  A table's header over a list of <details>, not a real <table>.
                  The rows stay disclosures because a signature is 40+ bytes and
                  dumping every one inline is what the folding was for; the
                  header and the column grid are what make it scannable.
                */}
                <div className="krowhead" aria-hidden="true">
                  <span>{t('check.col.entry')}</span>
                  <span>{t('check.col.kind')}</span>
                  <span>{t('check.col.platform')}</span>
                </div>
                <div className="krows">
                  {shown.map((verdict) => (
                    <details className="krow" data-state={verdict.state} key={`${verdict.state}-${verdict.key}`}>
                      <summary>
                        <code className="kname">{verdict.key}</code>
                        <span className="kindbadge">
                          {t(`check.kind.${
                            typeof (verdict.expected?.[0] ?? verdict.mine?.linux ?? verdict.expected?.[1] ?? verdict.mine?.windows) === 'number'
                              ? 'offset'
                              : 'signature'
                          }`)}
                        </span>
                        {/* One grid cell, so the badges line up down the column. */}
                        <span className="pbadges">
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
                        </span>
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
