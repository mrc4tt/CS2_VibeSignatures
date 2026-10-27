import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { copyText } from '../../ui/clipboard'
import { EditIcon } from '../../ui/icons'
import { saveText } from '../../ui/download'
import { Button, ChipGroup } from '../../ui/primitives'
import { TokenText } from '../gamedata/FileView'
import { tokenizeLine } from '../gamedata/fileModel'
import { changedLines, marksByLine, type LineMark, type MarkNote } from './lineMarks'
import type { GameDataFormat } from './parse'

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
  /** Called with the edited text; the page reads it again as if it had been dropped. */
  onEdit(text: string): void
  /** Bumped by the page's Paste button: opens the editor empty, ready for a paste. */
  blankEdit?: number
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
 */
export function AnnotatedFile({ text, fixed, name, format, marks, source, problems, focusLine, onStep, onEdit, blankEdit = 0 }: Props) {
  const { t } = useTranslation()
  const [showFixed, setShowFixed] = useState(false)
  const [copied, setCopied] = useState(false)
  const [draft, setDraft] = useState<string | null>(null)
  const viewRef = useRef<HTMLDivElement>(null)

  const shown = showFixed && fixed ? fixed : text
  const lines = useMemo(() => shown.split('\n'), [shown])
  const byLine = useMemo(() => marksByLine(marks), [marks])
  const changed = useMemo(() => (fixed ? changedLines(text, fixed) : new Set<number>()), [text, fixed])
  const focusIndex = focusLine !== undefined ? problems.indexOf(focusLine) : -1

  useEffect(() => { if (!fixed) setShowFixed(false) }, [fixed])
  useEffect(() => { setDraft(null) }, [text])
  useEffect(() => { if (blankEdit > 0) setDraft('') }, [blankEdit])
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
        {draft !== null ? (
          <span className="flex gap-2">
            <Button size="small" variant="primary" disabled={!draft.trim()} onClick={() => onEdit(draft)}>
              {t('check.view.apply')}
            </Button>
            <Button size="small" onClick={() => setDraft(null)}>{t('check.view.cancel')}</Button>
          </span>
        ) : (
          <Button size="small" onClick={() => setDraft(shown)}>
            <EditIcon size={13} />
            {t('check.view.edit')}
          </Button>
        )}
        {draft === null && fixed && (
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
        {draft === null && problems.length > 0 && (
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

      {draft !== null ? (
        <textarea
          className="rawedit"
          aria-label={t('check.view.editLabel')}
          spellCheck={false}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      ) : (
        <div className="rawscroll" ref={viewRef}>
          <div className="raw">
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
              return (
                <div className={classes.join(' ')} key={lineNumber} data-line={lineNumber}>
                  <span className="ln">{lineNumber}</span>
                  <span className="fold"> </span>
                  <span className="st" title={tip || undefined} />
                  <span className="lc">
                    {tokenizeLine(line, format).map((token, tokenIndex) => <TokenText token={token} key={tokenIndex} />)}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="rawstatus">
        <span>{format.toUpperCase()}</span>
        <span>{t('check.view.lines', { count: lines.length })}</span>
        <span className={problems.length ? 'text-bad' : 'text-ok'}>
          {problems.length ? t('check.view.problems', { count: problems.length }) : t('check.view.clean')}
        </span>
        <span className="ml-auto">
          {source === 'scan' ? t('check.view.fromScan') : source === 'browser' ? t('check.view.fromBrowser') : t('check.view.noMarks')}
        </span>
      </div>
    </div>
  )
}
