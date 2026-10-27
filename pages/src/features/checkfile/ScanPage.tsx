import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { requestNavigation } from '../../app/navigate'
import { ArrowLeftIcon, EditIcon, FileCheckIcon } from '../../ui/icons'
import { buttonClass } from '../../ui/buttonStyle'
import { Alert, Button, Tag } from '../../ui/primitives'
import { getGameDataFile, getGameDataIndex } from '../gamedata/data'
import { AnnotatedFile, type BrokenText } from './AnnotatedFile'
import { fetchScanBuilds, fetchScanHealth, requestDeepScan, type DeepFix } from './deepScan'
import { fileDetails } from './details'
import { clearHandoff, peekHandoff } from './handoff'
import { browserMarks, misnamedKeys, problemLines, renameMarks, scanMarks, type KeyRename } from './lineMarks'
import { applyFixes, renameKey } from './patch'
import { ResultSheet } from './ResultSheet'
import { readAutoOpen, type SheetSize } from './sheetModel'
import { ScanPanel, type ScanPlatform } from './ScanPanel'
import { failureText, isLoaded, readGameData, useFileCheck, type Loaded } from './useFileCheck'
import { agedValue } from './verdict'

/**
 * The scanner: one file, the settings and verdict in a column on the left, the
 * file itself on the right with every verdict on its line.
 *
 * It used to sit under Check my file, below the hero, the upload panel and the
 * file's identity bar, all inside the narrow reading column, so the editor was
 * the fifth thing down a long page. Here it is the page: full width, a toolbar
 * instead of an upload panel, and the file in view from the first paint. A
 * scan's result waits in a bar at the bottom until it is asked for.
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
  const [broken, setBroken] = useState<BrokenText | null>(null)
  const [dragging, setDragging] = useState(false)
  const [platform, setPlatform] = useState<ScanPlatform>('both')
  const [build, setBuild] = useState('')
  const [focusLine, setFocusLine] = useState<number | undefined>(undefined)
  const [sheet, setSheet] = useState<SheetSize>('closed')
  const [scanMs, setScanMs] = useState<number | undefined>(undefined)
  const scanStarted = useRef(0)
  const [blankEdit, setBlankEdit] = useState(0)
  const [pasted, setPasted] = useState('')
  // Once someone drops, pastes or edits, the example must never land on top of it.
  const userActed = useRef(loaded !== null)
  const { history, newest, file, verdicts, summary, patched } = useFileCheck(loaded)
  // Set when the text was replaced by its fixed copy: that copy is scanned as soon as it is in.
  const rescan = useRef(false)

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
    mutationFn: (input: Loaded) => {
      scanStarted.current = performance.now()
      return requestDeepScan(input.text, input.name, {
        platform: platform === 'both' ? undefined : platform,
        build: build || undefined,
      })
    },
    onSuccess: (data) => {
      setScanMs(performance.now() - scanStarted.current)
      if (data.note) return
      setFocusLine(undefined)
      setSheet(readAutoOpen() ? 'half' : 'min')
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
    // A misspelled key is found from the published file alone, so it is marked in both modes.
    const names = file ? renameMarks(loaded.text, misnamedKeys(verdicts)) : []
    if (scanResult && !scanResult.note) return [...scanMarks(loaded.text, scanResult), ...names]
    return file ? [...browserMarks(loaded.text, verdicts), ...names] : names
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
    const at = focusLine !== undefined ? problems.indexOf(focusLine) : -1
    // From a line that is not a problem (or none), step to the nearest problem in that direction.
    const next = at >= 0
      ? (at + direction + problems.length) % problems.length
      : direction === 1
        ? Math.max(0, problems.findIndex((line) => focusLine === undefined || line > focusLine))
        : (() => {
            const before = problems.filter((line) => focusLine !== undefined && line < focusLine).length - 1
            return before >= 0 ? before : problems.length - 1
          })()
    setFocusLine(problems[next])
  }

  const runScan = scan.mutate
  useEffect(() => {
    if (!rescan.current || !loaded) return
    rescan.current = false
    runScan(loaded)
  }, [loaded, runScan])

  function swapText(next: Loaded) {
    rescan.current = true
    setFocusLine(undefined)
    setSheet('closed')
    scan.reset()
    setLoaded(next)
  }

  function placeFixed(fixed: string, message = t('scan.result.usedFixed')) {
    if (!loaded) return
    const before = loaded
    const read = readGameData(fixed, loaded.name)
    if (!isLoaded(read)) return
    userActed.current = true
    // Marks from the deep scan belong to the text it scanned, so the changed text is
    // scanned again. Marks from the published values follow the text by themselves,
    // and a file must never be sent off by anything but a scan the user asked for.
    const swap = scanResult && !scanResult.note ? swapText : setLoaded
    swap(read)
    toast.success(message, {
      action: { label: t('scan.result.undo'), onClick: () => swap(before) },
      duration: 10_000,
    })
  }

  function applyOne(fixes: DeepFix[]) {
    if (!loaded) return
    const result = applyFixes(loaded.text, fixes)
    if (result.applied === 0) {
      toast.error(t('check.pop.notPlaced'))
      return
    }
    placeFixed(result.text, t('check.pop.applied', { count: result.applied }))
  }

  function renameOne(rename: KeyRename) {
    if (!loaded) return
    const next = renameKey(loaded.text, rename.from, rename.to)
    if (next === null) {
      toast.error(t('check.pop.notPlaced'))
      return
    }
    placeFixed(next, t('check.pop.renamed', { name: rename.to }))
  }

  async function accept(input: File | string, name: string, fromEditor = false) {
    userActed.current = true
    setError(null)
    setBroken(null)
    setFocusLine(undefined)
    setSheet('closed')
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
    // A typo made while typing is shown on its line in the editor, not above the page.
    if (fromEditor && read.reason === 'badJson') {
      setBroken({ text, line: read.line, message: failureText(read, t) })
      return
    }
    setError(failureText(read, t))
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
      data-sheet={scanResult && !scanResult.note && sheet !== 'closed' ? sheet : undefined}
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
            <AnnotatedFile
              text={loaded.text}
              fixed={fixedText}
              name={loaded.name}
              format={loaded.format}
              marks={marks}
              source={scanResult && !scanResult.note ? 'scan' : file ? 'browser' : null}
              problems={problems}
              focusLine={focusLine}
              onStep={stepProblem}
              onEdit={(text) => void accept(text, loaded.example ? t('check.pasted') : loaded.name, true)}
              blankEdit={blankEdit}
              broken={broken}
              onApply={applyOne}
              onRename={renameOne}
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

      {loaded && scanResult && !scanResult.note && (
        <ResultSheet
          result={scanResult}
          text={loaded.text}
          name={loaded.name}
          fixed={deepPatched?.applied ? deepPatched.text : null}
          size={sheet}
          onSize={setSheet}
          ms={scanMs}
          onJump={setFocusLine}
          onUseFixed={deepPatched?.applied ? () => placeFixed(deepPatched.text) : undefined}
          aged={(key, platform) => agedValue(history, file, key, platform, loaded.values.get(key)?.[platform])}
        />
      )}
    </div>
  )
}
