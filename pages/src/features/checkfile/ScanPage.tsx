import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { requestNavigation } from '../../app/navigate'
import { ArrowLeftIcon, EditIcon, FileCheckIcon } from '../../ui/icons'
import { buttonClass } from '../../ui/buttonStyle'
import { Alert, Button, Tabs, Tag } from '../../ui/primitives'
import { getGameDataFile, getGameDataIndex } from '../gamedata/data'
import { AnnotatedFile } from './AnnotatedFile'
import { DeepScan } from './DeepScan'
import { fetchScanBuilds, fetchScanHealth, requestDeepScan } from './deepScan'
import { fileDetails } from './details'
import { clearHandoff, peekHandoff } from './handoff'
import { KeyList } from './KeyList'
import { browserMarks, problemLines, scanMarks } from './lineMarks'
import { applyFixes } from './patch'
import { ScanPanel, type ScanPlatform } from './ScanPanel'
import { isLoaded, readGameData, useFileCheck, type Loaded } from './useFileCheck'

/**
 * The scanner: one file, the settings and verdict in a column on the left, the
 * file itself on the right with every verdict on its line.
 *
 * It used to sit under Check my file, below the hero, the upload panel and the
 * file's identity bar, all inside the narrow reading column, so the editor was
 * the fifth thing down a long page. Here it is the page: full width, a toolbar
 * instead of an upload panel, and the file in view from the first paint.
 */
export function ScanPage() {
  const { t } = useTranslation()
  const [loaded, setLoaded] = useState<Loaded | null>(() => {
    const carried = peekHandoff()
    if (!carried) return null
    const read = readGameData(carried.text, carried.name)
    return isLoaded(read) ? read : null
  })
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [view, setView] = useState<'file' | 'list'>('file')
  const [platform, setPlatform] = useState<ScanPlatform>('both')
  const [build, setBuild] = useState('')
  const [focusIndex, setFocusIndex] = useState(-1)
  const [blankEdit, setBlankEdit] = useState(0)
  const [pasted, setPasted] = useState('')
  // Once someone drops, pastes or edits, the example must never land on top of it.
  const userActed = useRef(loaded !== null)
  const { newest, file, verdicts, summary, patched } = useFileCheck(loaded)

  useEffect(clearHandoff, [])

  const { data: index } = useQuery({
    queryKey: ['gamedata-index'],
    queryFn: ({ signal }) => getGameDataIndex(signal),
    enabled: !loaded,
  })
  // Asking which builds it can scan against sends nothing about the file; the
  // file itself only goes on a click.
  const { data: scanBuilds } = useQuery({
    queryKey: ['scan-builds'],
    queryFn: ({ signal }) => fetchScanBuilds(signal),
    retry: false,
    staleTime: 5 * 60_000,
  })
  const { data: health } = useQuery({
    queryKey: ['scan-health'],
    queryFn: ({ signal }) => fetchScanHealth(signal),
    retry: false,
    refetchInterval: 15_000,
  })
  const details = useMemo(() => (loaded ? fileDetails(loaded.text, loaded.values) : null), [loaded])
  const scan = useMutation({
    mutationFn: (input: Loaded) =>
      requestDeepScan(input.text, input.name, {
        platform: platform === 'both' ? undefined : platform,
        build: build || undefined,
      }),
    onSuccess: (data) => {
      if (data.note) return
      setView('file')
      setFocusIndex(-1)
    },
  })
  // A result belongs to the text it was run on; a new file must not inherit the last one's.
  const scanResult = scan.data && scan.variables?.text === loaded?.text ? scan.data : undefined
  const deepPatched = useMemo(
    () => (loaded && scanResult?.fixes?.length ? applyFixes(loaded.text, scanResult.fixes) : null),
    [loaded, scanResult],
  )
  const marks = useMemo(() => {
    if (!loaded) return []
    if (scanResult && !scanResult.note) return scanMarks(loaded.text, scanResult)
    return file ? browserMarks(loaded.text, verdicts) : []
  }, [loaded, scanResult, file, verdicts])
  const problems = useMemo(() => problemLines(marks), [marks])
  const fixedText = deepPatched?.applied ? deepPatched.text : patched?.applied ? patched.text : null

  useEffect(() => {
    if (loaded || userActed.current || !index || !newest) return
    const files = (index.versions.find((version) => version.gameVersion === newest) ?? index.versions[0])?.files ?? []
    const pick = files.find((entry) => entry.plugin === 'matchzy') ?? files[0]
    if (!pick) return
    let cancelled = false
    void getGameDataFile(pick).then((text) => {
      if (cancelled || userActed.current) return
      const read = readGameData(text, pick.fileName)
      // an example that does not parse is simply not shown
      if (isLoaded(read)) setLoaded({ ...read, example: { plugin: pick.plugin, build: newest } })
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [index, newest, loaded])

  function stepProblem(direction: 1 | -1): void {
    if (problems.length === 0) return
    const start = focusIndex < 0 ? (direction === 1 ? -1 : 0) : focusIndex
    setFocusIndex((start + direction + problems.length) % problems.length)
    setView('file')
  }

  async function accept(input: File | string, name: string) {
    userActed.current = true
    setError(null)
    setView('file')
    setFocusIndex(-1)
    scan.reset()
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
    setError(read.reason === 'noEntries' ? t('check.noEntries', { format: read.format.toUpperCase() }) : t('check.unreadable'))
  }

  const verdict = scanResult && !scanResult.note
    ? { tone: scanResult.unhealthy ? 'bad' : 'ok', text: scanResult.unhealthy
      ? t('check.deep.unhealthy', { count: scanResult.unhealthy, build: scanResult.build })
      : t('check.deep.healthy', { build: scanResult.build }) }
    : file
      ? { tone: summary.outdated ? 'warn' : 'ok', text: summary.outdated
        ? t('check.needsWork', { keys: summary.outdated, build: newest })
        : t('check.upToDate', { build: newest }) }
      : null

  return (
    <div
      className="scanpage"
      data-dragging={dragging || undefined}
      onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
      onDragLeave={(event) => { if (event.currentTarget === event.target) setDragging(false) }}
      onDrop={(event) => {
        event.preventDefault()
        setDragging(false)
        const dropped = event.dataTransfer.files[0]
        if (dropped) void accept(dropped, dropped.name)
      }}
    >
      <h1 className="sr-only">{t('scan.h1')}</h1>
      {/* One bar for the file: what it is, what the check says, and the ways to
          swap it. It replaces the hero, the upload panel and the example notice. */}
      <div className="scanbar">
        <span className="flex size-[34px] shrink-0 items-center justify-center rounded-[9px] bg-card-2 text-[color:var(--accent-text)]">
          <FileCheckIcon size={16} />
        </span>
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="flex min-w-0 items-center gap-2">
            <span className="truncate font-mono text-[14px] text-ink">{loaded?.name ?? t('scan.noFile')}</span>
            {loaded?.example && <Tag tone="qualify">{t('scan.example', { plugin: loaded.example.plugin, build: loaded.example.build })}</Tag>}
          </span>
          <span className="text-[12px] text-muted-foreground">
            {loaded ? t('check.readAs', { format: loaded.format.toUpperCase(), keys: loaded.values.size }) : t('scan.dropHint')}
          </span>
        </span>
        {verdict && <span className={`scanverdict ${verdict.tone}`}>{verdict.text}</span>}
        <span className="ml-auto flex flex-wrap gap-2">
          <label className={buttonClass('primary')}>
            {t('scan.open')}
            <input
              type="file"
              hidden
              onChange={(event) => {
                const picked = event.target.files?.[0]
                if (picked) void accept(picked, picked.name)
                event.target.value = ''
              }}
            />
          </label>
          <Button
            onClick={() => {
              setView('file')
              setBlankEdit((n) => n + 1)
              if (!loaded) document.getElementById('scan-paste')?.focus()
            }}
          >
            <EditIcon size={13} />
            {t('scan.paste')}
          </Button>
          <Button variant="text" onClick={() => requestNavigation({ view: 'check' })}>
            <ArrowLeftIcon size={13} />
            {t('scan.back')}
          </Button>
        </span>
      </div>

      {error && <Alert tone="bad" title={error} />}

      <div className={loaded ? 'scangrid' : undefined}>
        {loaded && details ? (
          <ScanPanel
            plugin={file?.split('/')[0]}
            format={loaded.format}
            details={details}
            health={health}
            platform={platform}
            onPlatform={setPlatform}
            builds={scanBuilds ?? []}
            build={build}
            onBuild={setBuild}
            pending={scan.isPending}
            error={scan.error}
            result={scanResult}
            onScan={() => scan.mutate(loaded)}
            summary={file ? summary : undefined}
            problems={problems.length}
            onNext={() => stepProblem(1)}
          />
        ) : null}
        <div className="min-w-0">
          {loaded ? (
            <Tabs
              value={view}
              onValueChange={(next) => setView(next as 'list' | 'file')}
              items={[
                {
                  key: 'file',
                  label: t('check.view.file'),
                  children: (
                    <AnnotatedFile
                      text={loaded.text}
                      fixed={fixedText}
                      name={loaded.name}
                      format={loaded.format}
                      marks={marks}
                      source={scanResult && !scanResult.note ? 'scan' : file ? 'browser' : null}
                      problems={problems}
                      focusIndex={focusIndex}
                      onStep={stepProblem}
                      onEdit={(text) => void accept(text, loaded.example ? t('check.pasted') : loaded.name)}
                      blankEdit={blankEdit}
                    />
                  ),
                },
                {
                  key: 'list',
                  label: t('check.view.list'),
                  children: (
                    <div className="flex flex-col gap-4">
                      {scanResult
                        ? <DeepScan name={loaded.name} result={scanResult} patched={deepPatched} />
                        : file
                          ? <KeyList key={loaded.text} verdicts={verdicts} summary={summary} newest={newest} />
                          : <p className="plain">{t('scan.noList')}</p>}
                    </div>
                  ),
                },
              ]}
            />
          ) : (
            <div className="scanempty">
              <p className="dzmain">{t('check.drop')}</p>
              <p className="dznote">{t('check.examples')}</p>
              <label className="sr-only" htmlFor="scan-paste">{t('check.pasteLabel')}</label>
              <textarea
                id="scan-paste"
                className="rawedit"
                placeholder={t('check.pasteLabel')}
                spellCheck={false}
                value={pasted}
                onChange={(event) => setPasted(event.target.value)}
              />
              <Button variant="primary" disabled={pasted.trim().length < 10} onClick={() => void accept(pasted, t('check.pasted'))}>
                {t('check.checkIt')}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
