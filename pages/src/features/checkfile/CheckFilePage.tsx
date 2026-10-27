import { useQuery } from '@tanstack/react-query'
import { FileCheckIcon, PlayIcon } from '../../ui/icons'
import { buttonClass } from '../../ui/buttonStyle'
import { copyText } from '../../ui/clipboard'
import { saveText } from '../../ui/download'
import { Alert, Button, Select, Skeleton, Tabs } from '../../ui/primitives'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Explain } from '../../components/Explain'
import { requestNavigation } from '../../app/navigate'
import { getGameDataFile, getGameDataIndex } from '../gamedata/data'
import { DEEP_SCAN_API } from './deepScan'
import { handOff } from './handoff'
import { KeyList } from './KeyList'
import { isLoaded, readGameData, useFileCheck, type Loaded } from './useFileCheck'

/**
 * The quick check: drop a file, see which keys are out of date for the newest
 * build, take the fixed file. All of it in this browser. The deep scan against
 * the game binaries and the file view with a verdict on every line are their own
 * page (/scan), one button away, so this one stays short.
 */
export function CheckFilePage() {
  const { t } = useTranslation()
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [mode, setMode] = useState<'file' | 'paste'>('file')
  const [pasted, setPasted] = useState('')
  const [copied, setCopied] = useState(false)
  const { history, isLoading, newest, identification, chosenFile, setChosenFile, file, fit, verdicts, summary, patched, behind } = useFileCheck(loaded)
  const { data: index } = useQuery({
    queryKey: ['gamedata-index'],
    queryFn: ({ signal }) => getGameDataIndex(signal),
    enabled: Boolean(file),
  })
  const publishedFile = useMemo(
    () => index?.versions.find((version) => version.gameVersion === newest)?.files.find((entry) => entry.id === file),
    [index, newest, file],
  )

  async function accept(input: File | string, name: string) {
    setError(null)
    setChosenFile(null)
    setCopied(false)
    let text: string
    try {
      text = typeof input === 'string' ? input : await input.text()
    } catch {
      text = ''
    }
    const read = readGameData(text, name)
    if (isLoaded(read)) {
      setLoaded(read)
      return
    }
    setLoaded(null)
    setError(read.reason === 'noEntries' ? t('check.noEntries', { format: read.format.toUpperCase() }) : t('check.unreadable'))
  }

  if (isLoading) return <div className="handbook"><Skeleton rows={6} /></div>

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
          <Tabs
            variant="segmented"
            value={mode}
            onValueChange={(next) => setMode(next as 'file' | 'paste')}
            items={[
              {
                key: 'file',
                label: t('check.mode.file'),
                children: (
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
                    <label className={buttonClass('primary')}>
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
                ),
              },
              {
                key: 'paste',
                label: t('check.mode.paste'),
                children: (
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
                      <Button
                        variant="primary"
                        disabled={pasted.trim().length < 10}
                        onClick={() => void accept(pasted, t('check.pasted'))}
                      >
                        {t('check.checkIt')}
                      </Button>
                      {pasted && (
                        <Button onClick={() => { setPasted(''); setLoaded(null); setError(null) }}>
                          {t('check.clear')}
                        </Button>
                      )}
                    </div>
                  </div>
                ),
              },
            ]}
          />

          <Explain>{t('check.explain')}</Explain>

          {/*
            The check on this page runs in your browser. CI can either diff
            against the published file (the index addresses every one with a
            sha256) or POST the file to the same deep scan the page offers.
          */}
          <details className="ci">
            <summary>{t('check.ciH')}</summary>
            <p className="plain">{t('check.ciBody')}</p>
            <pre className="json-block">{`# the newest published file for one plugin, and its digest
url=$(curl -sS ${window.location.origin}/gamedata/index.json \\
  | jq -r '.versions[0].files[] | select(.plugin=="matchzy") | .content.url')
curl -sS ${window.location.origin}/gamedata/$url -o published.json

# fail the build when what you ship no longer matches it
diff <(jq -S . published.json) <(jq -S . gamedata/matchzy.json)

# or scan it against the game binaries; fail on anything contradicted
jq -n --rawfile g gamedata/matchzy.json '{gamedata: $g, filename: "matchzy.json"}' \\
  | curl -sS ${DEEP_SCAN_API}/verify -H 'Content-Type: application/json' -d @- \\
  | jq -e '.unhealthy == 0'`}</pre>
          </details>
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
                <span className="text-[12px] text-muted-foreground">
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
                {/* The headline verdict is in the bar above; what is left here is
                    which build your file looks like and how far back that is. */}
                {fit && (
                  <p className="fitnote m-0 text-[12.5px] leading-relaxed text-muted-foreground">
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
                      <Button variant="primary" onClick={() => saveText(patched.text, `${newest}-${loaded.name}`)}>
                        {t('check.download')}
                      </Button>
                      <Button
                        onClick={() => {
                          void copyText(patched.text, { ok: t('clipboard.ok'), failed: t('clipboard.failed') }).then(setCopied)
                        }}
                      >
                        {copied ? t('check.copied') : t('check.copy')}
                      </Button>
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
                          saveText(text, `${newest}-${publishedFile.fileName}`),
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

                <KeyList key={loaded.text} verdicts={verdicts} summary={summary} newest={newest} />
              </>
            )}
          </div>
        </section>
      )}

      {/* The way on to the scanner: same file, the binaries instead of our
          published values, and every verdict on its own line. */}
      <section className="scancta">
        <span className="flex size-[38px] shrink-0 items-center justify-center rounded-[9px] bg-card-2 text-[color:var(--accent-text)]">
          <PlayIcon size={16} />
        </span>
        <span className="flex min-w-0 grow flex-col gap-0.5">
          <strong className="font-display text-[15px] text-ink">{t('check.toScan.h')}</strong>
          <span className="text-[13px] leading-relaxed text-ink-2">{t('check.toScan.body')}</span>
        </span>
        <Button
          variant="primary"
          onClick={() => {
            if (loaded) handOff(loaded.text, loaded.name)
            requestNavigation({ view: 'scan' })
          }}
        >
          {loaded ? t('check.toScan.withFile') : t('check.toScan.open')}
        </Button>
      </section>
    </div>
  )
}
