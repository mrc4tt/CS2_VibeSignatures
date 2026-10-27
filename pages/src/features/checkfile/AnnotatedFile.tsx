import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { copyText } from '../../ui/clipboard'
import { saveText } from '../../ui/download'
import { Button, ChipGroup } from '../../ui/primitives'
import { TokenText } from '../gamedata/FileView'
import { tokenizeLine } from '../gamedata/fileModel'
import { changedLines, marksByLine, type LineMark, type MarkNote } from './lineMarks'
import type { GameDataFormat } from './parse'

/** A text typed into the editor that is not valid JSON, and where it breaks. */
export interface BrokenText {
  text: string
  line: number
  message: string
}

interface Props {
  text: string
  /** The file with every fix placed, when there is one to offer. */
  fixed?: string | null
  name: string
  format: GameDataFormat
  marks: LineMark[]
  /** Where the marks came from, said in the status line so nobody mistakes one check for the other. */
  source: 'scan' | 'browser' | null
  problems: number[]
  /** The line to mark and scroll to: a problem stepped to, or a row picked in the scan result. */
  focusLine?: number
  onStep(direction: 1 | -1): void
  /** Called with the edited text once typing pauses; the page reads it again as if it had been dropped. */
  onEdit(text: string): void
  /** Bumped by the page's Paste button: empties the editor and puts the caret in it, ready for a paste. */
  blankEdit?: number
  /** Set when the last text handed to onEdit did not parse: its line is marked and the reason shown. */
  broken?: BrokenText | null
}

/**
 * The dropped file itself, with every verdict on the line it is about.
 *
 * The scan result answers "what is wrong"; this answers "where in my file",
 * which is what someone fixing it by hand needs. It reuses the published-file
 * viewer's look and tokenizer and adds a marker in the gutter: a dot for wrong,
 * a diamond for unconfirmed, a thin bar for holds, so the three differ by shape
 * and not only by colour. What a marker means is in its tooltip and in the
 * result sheet; lines are never pushed apart by notes, so the file reads as itself.
 *
 * It is typed into directly. A transparent textarea lies exactly over the
 * highlighted lines (same font, line height and padding, inside the same
 * scroller), so the caret and selection are the browser's own while the colours
 * come from the rows beneath. Once typing pauses the text is checked again; the
 * marks belong to the checked text, so they are hidden while it differs.
 */
export function AnnotatedFile({ text, fixed, name, format, marks, source, problems, focusLine, onStep, onEdit, blankEdit = 0, broken }: Props) {
  const { t } = useTranslation()
  const [showFixed, setShowFixed] = useState(false)
  const [copied, setCopied] = useState(false)
  const [draft, setDraft] = useState(text)
  const viewRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  // The last text handed to onEdit: when it comes back as `text` it must not
  // overwrite what was typed after it.
  const sent = useRef<string | null>(null)
  const editRef = useRef(onEdit)
  useEffect(() => { editRef.current = onEdit })

  const viewingFixed = showFixed && !!fixed
  const shown = viewingFixed ? fixed : draft
  const dirty = !viewingFixed && draft !== text
  // Only while the editor still holds exactly the text that failed: typing on clears it.
  const brokenHere = dirty && broken?.text === draft ? broken : null
  const lines = useMemo(() => shown.split('\n'), [shown])
  const byLine = useMemo(() => (dirty ? new Map<number, LineMark[]>() : marksByLine(marks)), [dirty, marks])
  const changed = useMemo(() => (fixed ? changedLines(text, fixed) : new Set<number>()), [text, fixed])
  const focusIndex = focusLine !== undefined ? problems.indexOf(focusLine) : -1

  useEffect(() => { if (!fixed) setShowFixed(false) }, [fixed])
  useEffect(() => {
    if (text === sent.current) return
    sent.current = null
    setDraft(text)
  }, [text])
  useEffect(() => {
    if (blankEdit === 0) return
    setShowFixed(false)
    setDraft('')
    inputRef.current?.focus()
  }, [blankEdit])
  useEffect(() => {
    if (draft === text || draft.trim().length < 2) return
    const timer = window.setTimeout(() => {
      sent.current = draft
      editRef.current(draft)
    }, 700)
    return () => window.clearTimeout(timer)
  }, [draft, text])
  useEffect(() => {
    if (brokenHere) viewRef.current?.querySelector<HTMLElement>(`[data-line="${brokenHere.line}"]`)?.scrollIntoView?.({ block: 'nearest' })
  }, [brokenHere])
  useEffect(() => {
    if (focusLine) viewRef.current?.querySelector<HTMLElement>(`[data-line="${focusLine}"]`)?.scrollIntoView?.({ block: 'start' })
  }, [focusLine])

  function noteText(note: MarkNote): string {
    switch (note.kind) {
      case 'expected':
        return t('check.deep.expected', { value: note.value })
      case 'hits':
        return t('check.deep.hits', { count: note.count })
      case 'vtable':
        return t('check.deep.vtable', { state: note.state })
      default:
        return note.status
    }
  }

  return (
    <div className="annotated overflow-hidden rounded-[12px] border border-rule-strong">
      <div className="rawbar">
        <span className="font-mono text-[12.5px] text-ink">{name}</span>
        {fixed && (
          <ChipGroup
            label={t('check.view.which')}
            value={showFixed ? 'fixed' : 'original'}
            onValueChange={(next) => setShowFixed(next === 'fixed')}
            items={[
              { value: 'original', label: t('check.view.original') },
              { value: 'fixed', label: t('check.view.fixed') },
            ]}
          />
        )}
        {problems.length > 0 && (
          <span className="nav2">
            <button type="button" onClick={() => onStep(-1)} aria-label={t('check.view.prev')}>▲</button>
            <span>{t('check.view.position', { index: focusIndex >= 0 ? focusIndex + 1 : 0, total: problems.length })}</span>
            <button type="button" onClick={() => onStep(1)} aria-label={t('check.view.next')}>▼</button>
          </span>
        )}
        <span className="legend">
          <span><i className="b" />{t('check.view.legendBad')}</span>
          <span><i className="w" />{t('check.view.legendWarn')}</span>
          <span><i className="c" />{t('check.view.legendOk')}</span>
          {showFixed && <span><i className="u" />{t('check.view.legendChanged')}</span>}
        </span>
        {fixed && (
          <span className="flex gap-2">
            <Button size="small" onClick={() => saveText(fixed, name)}>{t('check.view.download')}</Button>
            <Button
              size="small"
              onClick={() => {
                void copyText(fixed, { ok: t('clipboard.ok'), failed: t('clipboard.failed') }).then(setCopied)
              }}
            >
              {copied ? t('check.copied') : t('check.copy')}
            </Button>
          </span>
        )}
      </div>

      <div className="rawscroll" ref={viewRef}>
        <div className="raw">
          <textarea
            ref={inputRef}
            className="rawinput"
            aria-label={t('check.view.editLabel')}
            spellCheck={false}
            autoCapitalize="off"
            autoComplete="off"
            autoCorrect="off"
            wrap="off"
            readOnly={viewingFixed}
            value={shown}
            onChange={(event) => setDraft(event.target.value)}
          />
          {lines.map((line, index) => {
            const lineNumber = index + 1
            const isChanged = showFixed && changed.has(lineNumber)
            // In the fixed copy a rewritten line is no longer wrong, so it is shown as changed instead.
            const here = isChanged ? [] : byLine.get(lineNumber) ?? []
            const worst = here[0]?.tone
            const tip = here.map((mark) => {
              const what = mark.note ? noteText(mark.note) : t(`check.view.legend${mark.tone === 'bad' ? 'Bad' : mark.tone === 'warn' ? 'Warn' : 'Ok'}`)
              return `${t(`check.platform.${mark.platform}`)}: ${what}`
            }).join('\n')
            const classes = ['rl']
            if (worst) classes.push(`m-${worst}`)
            if (isChanged) classes.push('upd')
            if (focusLine === lineNumber) classes.push('foc')
            if (brokenHere?.line === lineNumber) classes.push('m-bad')
            return (
              <div className={classes.join(' ')} key={lineNumber} data-line={lineNumber}>
                <span className="ln">{lineNumber}</span>
                <span className="fold"> </span>
                <span className="st" title={(brokenHere?.line === lineNumber ? brokenHere.message : tip) || undefined} />
                <span className="lc">
                  {tokenizeLine(line, format).map((token, tokenIndex) => <TokenText token={token} key={tokenIndex} />)}
                </span>
              </div>
            )
          })}
        </div>
      </div>

      <div className="rawstatus">
        <span>{format.toUpperCase()}</span>
        <span>{t('check.view.lines', { count: lines.length })}</span>
        {brokenHere ? (
          <span className="text-bad" role="status">{brokenHere.message}</span>
        ) : dirty ? (
          <span className="text-muted-foreground">{t('check.view.typing')}</span>
        ) : (
          <span className={problems.length ? 'text-bad' : 'text-ok'}>
            {problems.length ? t('check.view.problems', { count: problems.length }) : t('check.view.clean')}
          </span>
        )}
        <span className="ml-auto">
          {source === 'scan' ? t('check.view.fromScan') : source === 'browser' ? t('check.view.fromBrowser') : t('check.view.noMarks')}
        </span>
      </div>
    </div>
  )
}
