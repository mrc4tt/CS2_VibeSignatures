import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  buildLineModel, foldRanges, hiddenLines, tokenizeLine, type Token,
} from './fileModel'
import type { GameDataFileDescriptor, GameDataMetadata } from './types'

function TokenText({ token }: { token: Token }) {
  if (token.kind === 'hex') {
    return (
      <span className="hex">
        {token.text.split(/(\s+)/).map((part, index) =>
          part === '?' || part === '??'
            ? <span className="wc" key={index}>{part}</span>
            : <span key={index}>{part}</span>)}
      </span>
    )
  }
  const className = token.kind === 'key' ? 'jk'
    : token.kind === 'string' ? 'js'
      : token.kind === 'number' ? 'jn'
        : token.kind === 'comment' ? 'jc'
          : token.kind === 'punct' ? 'jp' : undefined
  return <span className={className}>{token.text}</span>
}

interface Props {
  descriptor: GameDataFileDescriptor
  content: string
  metadata?: GameDataMetadata
  find: string
  marks: boolean
  focusLine?: number
  onFind(value: string): void
  onMarks(value: boolean): void
}

/**
 * The file as a plugin reads it. Marks are opt-in, because the default reason to
 * open this page is to read or copy the file, not to audit it.
 */
export function FileView({ descriptor, content, metadata, find, marks, focusLine, onFind, onMarks }: Props) {
  const { t } = useTranslation()
  const [folded, setFolded] = useState<Set<number>>(new Set())
  const [changeIndex, setChangeIndex] = useState(-1)
  const viewRef = useRef<HTMLDivElement>(null)

  const lines = useMemo(() => content.split('\n'), [content])
  const ranges = useMemo(() => foldRanges(lines), [lines])
  const hidden = useMemo(() => hiddenLines(folded, ranges), [folded, ranges])
  const model = useMemo(() => buildLineModel(marks ? metadata : undefined), [marks, metadata])
  const changedLines = useMemo(
    () => [...model.changed.keys()].sort((left, right) => left - right),
    [model],
  )
  useEffect(() => { setFolded(new Set()); setChangeIndex(-1) }, [descriptor.id])

  const needle = find.trim().toLowerCase()
  const matches = needle ? lines.filter((line) => line.toLowerCase().includes(needle)).length : 0

  function scrollTo(line: number): void {
    viewRef.current?.querySelector<HTMLElement>(`[data-line="${line}"]`)?.scrollIntoView({ block: 'center' })
  }

  function stepChange(direction: 1 | -1): void {
    if (changedLines.length === 0) return
    const next = (changeIndex + direction + changedLines.length * 2) % changedLines.length
    setChangeIndex(next)
    scrollTo(changedLines[next])
  }

  useEffect(() => {
    if (focusLine) scrollTo(focusLine)
  }, [focusLine])

  return (
    <>
      <div className="rawbar">
        <label className="findbox">
          <input
            type="search"
            value={find}
            placeholder={t('gamedata2.find')}
            aria-label={t('gamedata2.find')}
            onChange={(event) => onFind(event.target.value)}
          />
        </label>
        <button type="button" className="chip" aria-pressed={marks} onClick={() => onMarks(!marks)}>
          {t('gamedata2.marks')}
        </button>
        {marks && changedLines.length > 0 && (
          <span className="nav2">
            <button type="button" onClick={() => stepChange(-1)} aria-label={t('gamedata2.prevChange')}>▲</button>
            <span>{t('gamedata2.changeCount', {
              index: changeIndex >= 0 ? changeIndex + 1 : 0,
              total: changedLines.length,
            })}</span>
            <button type="button" onClick={() => stepChange(1)} aria-label={t('gamedata2.nextChange')}>▼</button>
          </span>
        )}
        <span className="legend">
          {marks ? (
            <>
              <span><i className="c" />{t('gamedata2.legendFrom')}</span>
              <span><i className="u" />{t('gamedata2.legendChanged')}</span>
            </>
          ) : (
            <span>{t('gamedata2.plainNote')}</span>
          )}
          {needle && <span>{t('gamedata2.linesMatch', { count: matches })}</span>}
        </span>
      </div>

      <div className="rawscroll" ref={viewRef}>
        <div className="raw">
          {lines.map((line, index) => {
            const lineNumber = index + 1
            if (hidden.has(lineNumber)) return null
            const isChanged = model.changed.has(lineNumber)
            const isCovered = model.covered.has(lineNumber)
            const isHit = Boolean(needle) && line.toLowerCase().includes(needle)
            const canFold = ranges.has(lineNumber)
            const classes = ['rl']
            if (isChanged) classes.push('upd')
            else if (isCovered) classes.push('cov')
            if (isHit) classes.push('hit')
            if (focusLine === lineNumber) classes.push('foc')
            if (line.length > 110) classes.push('longline')
            return (
              <div className={classes.join(' ')} key={lineNumber} data-line={lineNumber}>
                <span className="ln">{lineNumber}</span>
                <span
                  className="fold"
                  role={canFold ? 'button' : undefined}
                  tabIndex={-1}
                  onClick={canFold ? () => {
                    const next = new Set(folded)
                    if (next.has(lineNumber)) next.delete(lineNumber)
                    else next.add(lineNumber)
                    setFolded(next)
                  } : undefined}
                >
                  {canFold ? (folded.has(lineNumber) ? '▸' : '▾') : ' '}
                </span>
                <span className="st" />
                <span className="lc">
                  {tokenizeLine(line, descriptor.language).map((token, tokenIndex) => (
                    <TokenText token={token} key={tokenIndex} />
                  ))}
                  {folded.has(lineNumber) && <span className="folded-hint"> …</span>}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </>
  )
}
