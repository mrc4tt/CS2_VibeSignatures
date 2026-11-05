import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { copyText } from '../../ui/clipboard'
import { saveText } from '../../ui/download'
import { Button, ChipGroup } from '../../ui/primitives'
import { inferredOf, platformTone, rowTone, sortRows, type DeepFix, type DeepPlatform, type DeepRow, type DeepScanResult, type DeepTone, type Platform } from './deepScan'
import { locateValue } from './lineMarks'
import { VTABLE_KEY_SUFFIX } from './parse'
import type { AgedValue } from './verdict'
import { PLATFORM_LABEL, PLATFORMS, readAutoOpen, scanLog, settleSheet, writeAutoOpen, type SheetSize } from './sheetModel'

const NEXT_SIZE: Record<SheetSize, SheetSize> = { closed: 'min', min: 'half', half: 'full', full: 'min' }
/** Room the full-height sheet leaves above it for the site header (CSS: calc(100dvh - 72px)). */
const TOP_GAP = 72
/** A drag taller than this shows the open sheet's content while it is still moving. */
const OPEN_AT = 160

interface Drag {
  y0: number
  h0: number
  lastY: number
  lastT: number
  velocity: number
  moved: boolean
}

type Filter = 'all' | 'bad' | 'warn' | 'ok'

interface Item {
  row: DeepRow
  tone: DeepTone
  line: number | null
  fixes: DeepFix[]
  /** The platform the reason is about: the worst one. */
  worst?: { platform: Platform; info: DeepPlatform }
}

function itemsFor(result: DeepScanResult, text: string): Item[] {
  const fixes = result.fixes ?? []
  return sortRows(result.results).map((row) => {
    const tone = rowTone(row)
    const worst = PLATFORMS
      .filter((platform) => row.platforms[platform])
      .map((platform) => ({ platform, info: row.platforms[platform]! }))
      .find((entry) => platformTone(entry.info) === tone)
    const line = worst
      ? locateValue(text, row.name, worst.platform)
      : PLATFORMS.map((platform) => locateValue(text, row.name, platform)).find((found) => found !== null) ?? null
    return {
      row,
      tone,
      line,
      fixes: fixes.filter((fix) => fix.key === row.name || fix.key === `${row.name}${VTABLE_KEY_SUFFIX}`),
      worst,
    }
  })
}

interface Props {
  result: DeepScanResult
  /** The text the scan ran on: lines are looked up in it. */
  text: string
  name: string
  /** The file with every confirmed fix placed, when there is one. */
  fixed: string | null
  size: SheetSize
  onSize(size: SheetSize): void
  /** How long the scan took, for the header. */
  ms?: number
  onJump(line: number): void
  /** Puts the fixed file in the editor and scans it again; absent when there is nothing to place. */
  onUseFixed?(): void
  /** Which build an entry's wrong value is from, when the published history knows it. */
  aged?(key: string, platform: Platform): AgedValue | null
}

/**
 * The scan's result, over the bottom of the page.
 *
 * After a scan it is a slim bar with the verdict in one sentence: the file stays
 * the thing on screen and nobody is pushed into a panel they did not ask for.
 * Opened, it covers the lower half (or all) of the page with one row per entry,
 * worst first, each with what is wrong in plain words and the value that fixes
 * it. A row click marks its line in the file above.
 */
export function ResultSheet({ result, text, name, fixed, size, onSize, ms, onJump, onUseFixed, aged }: Props) {
  const { t, i18n } = useTranslation()
  const [filter, setFilter] = useState<Filter>('all')
  const [view, setView] = useState<'table' | 'log'>('table')
  const [autoOpen, setAutoOpen] = useState(readAutoOpen)
  const [copiedKey, setCopiedKey] = useState<string | null>(null)
  const sheetRef = useRef<HTMLElement>(null)
  const dragged = useRef(false)
  const [dragHeight, setDragHeight] = useState<number | null>(null)
  const open = size === 'half' || size === 'full' || (dragHeight !== null && dragHeight > OPEN_AT)

  const items = useMemo(() => itemsFor(result, text), [result, text])
  const counts = useMemo(() => {
    const tally = { bad: 0, warn: 0, ok: 0 }
    for (const item of items) if (item.tone !== 'neutral') tally[item.tone] += 1
    return tally
  }, [items])
  const shown = filter === 'all' ? items : items.filter((item) => item.tone === filter)
  const flagged = counts.bad + counts.warn
  const fixable = items.filter((item) => (item.tone === 'bad' || item.tone === 'warn') && item.fixes.length > 0).length
  const log = useMemo(() => (view === 'log' ? scanLog(result) : ''), [view, result])

  useEffect(() => {
    if (open) sheetRef.current?.focus({ preventScroll: true })
  }, [open])

  if (size === 'closed') return null

  const platforms = (result.platforms ?? PLATFORMS).map((platform) => PLATFORM_LABEL[platform]).join(' + ')
  const seconds = result.cached
    ? t('scan.result.cached')
    : ms !== undefined ? t('scan.result.seconds', { value: (ms / 1000).toLocaleString(i18n.language, { maximumFractionDigits: 1 }) }) : null
  const meta = [result.build, platforms, seconds].filter(Boolean).join(' · ')
  const problems = [
    counts.bad ? t('scan.result.errors', { count: counts.bad }) : null,
    counts.warn ? t('scan.result.warnings', { count: counts.warn }) : null,
  ].filter(Boolean) as string[]
  const fixLine = fixable === 0
    ? t('scan.result.fixableNone')
    : fixable === flagged
      ? t('scan.result.fixableAll', { count: fixable })
      : t('scan.result.fixableSome', { fixable, count: flagged })

  function cellText(info: DeepPlatform | undefined): string {
    return info ? t(`scan.result.tone.${platformTone(info)}`) : '-'
  }

  function reason(item: Item): string {
    const info = item.worst?.info
    if (!info) return ''
    if (info.status === 'ambiguous' && info.count) return t('scan.result.reason.ambiguous', { count: info.count })
    if (info.status === 'mismatch') return t('scan.result.reason.mismatch')
    if (info.status === 'broken') return t('scan.result.reason.broken')
    if (info.vtable && info.vtable !== 'ok') return t('scan.result.reason.vtable', { state: info.vtable })
    return item.tone === 'bad' ? t('scan.result.reason.contradicted') : t('scan.result.reason.unverified')
  }

  // The handle and the header drag the sheet up and down, as on a phone; it
  // settles on the nearest size, or the next one when flicked. The move and the
  // release are followed on the window, because a finger leaves the grip at
  // once, and the pointer is not captured, so a press without movement stays
  // an ordinary click on whatever is under it.
  function onDragStart(event: PointerEvent<HTMLElement>) {
    if (event.button !== 0 || !sheetRef.current) return
    const target = event.target as HTMLElement
    if (target.closest('button, input, label, a, [role="radiogroup"], [role="group"]') && !target.closest('.rsheet-handle')) return
    const state: Drag = {
      y0: event.clientY,
      h0: sheetRef.current.getBoundingClientRect().height,
      lastY: event.clientY,
      lastT: event.timeStamp,
      velocity: 0,
      moved: false,
    }
    dragged.current = false
    const max = () => window.innerHeight - TOP_GAP
    const heightAt = (y: number) => Math.max(56, Math.min(max(), state.h0 - (y - state.y0)))
    const move = (next: globalThis.PointerEvent) => {
      if (!state.moved && Math.abs(next.clientY - state.y0) < 5) return
      state.moved = true
      next.preventDefault()
      const dt = Math.max(1, next.timeStamp - state.lastT)
      state.velocity = (next.clientY - state.lastY) / dt
      state.lastY = next.clientY
      state.lastT = next.timeStamp
      setDragHeight(heightAt(next.clientY))
    }
    const end = (last: globalThis.PointerEvent) => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
      window.removeEventListener('pointercancel', end)
      if (!state.moved) return
      dragged.current = true
      setDragHeight(null)
      onSize(settleSheet(heightAt(last.clientY), max(), state.velocity))
    }
    window.addEventListener('pointermove', move, { passive: false })
    window.addEventListener('pointerup', end)
    window.addEventListener('pointercancel', end)
  }

  function copyValue(key: string, value: string) {
    void copyText(value, { ok: t('clipboard.ok'), failed: t('clipboard.failed') }).then((done) => setCopiedKey(done ? key : null))
  }

  return (
    <>
      {open && <div className="rsheet-dim" aria-hidden="true" onClick={() => onSize('min')} />}
      <section
        ref={sheetRef}
        className="rsheet"
        data-size={size}
        data-dragging={dragHeight !== null || undefined}
        style={dragHeight !== null ? { height: dragHeight } : undefined}
        aria-label={t('scan.result.title')}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && open) {
            event.stopPropagation()
            onSize('min')
          }
        }}
      >
        <div className="rsheet-grip" onPointerDown={onDragStart}>
        <button
          type="button"
          className="rsheet-handle"
          aria-label={t('scan.result.size')}
          onClick={() => {
            // the click that ends a drag is not a request for the next size
            if (dragged.current) { dragged.current = false; return }
            onSize(NEXT_SIZE[size])
          }}
        >
          <span />
        </button>
        <div className="rsheet-head">
          {open ? (
            <>
              <h2>{t('scan.result.title')}</h2>
              <span className="rsheet-meta">{meta}</span>
              <ChipGroup
                label={t('scan.result.filter.label')}
                value={filter}
                onValueChange={(next) => setFilter((next ?? 'all') as Filter)}
                items={[
                  { value: 'all', label: t('scan.result.filter.all'), count: items.length },
                  { value: 'bad', label: t('scan.result.filter.bad'), count: counts.bad },
                  { value: 'warn', label: t('scan.result.filter.warn'), count: counts.warn },
                  { value: 'ok', label: t('scan.result.filter.ok'), count: counts.ok },
                ]}
              />
            </>
          ) : (
            <span className={`rsheet-verdict ${flagged ? (counts.bad ? 'bad' : 'warn') : 'ok'}`}>
              <span>
                <i aria-hidden="true" />
                <strong>{flagged ? t('scan.result.notReady', { build: result.build }) : t('scan.result.ready', { build: result.build })}</strong>{' '}
                {flagged
                  ? `${problems.join(t('scan.result.and'))}. ${fixLine}`
                  : t('scan.result.allOk', { count: counts.ok })}
              </span>
              <Button size="small" onClick={() => onSize('half')}>{t('scan.result.open')}</Button>
            </span>
          )}
          <span className="rsheet-acts">
            {open && (
              <>
                <ChipGroup
                  label={t('scan.result.view.label')}
                  value={view}
                  onValueChange={(next) => setView((next ?? 'table') as 'table' | 'log')}
                  items={[
                    { value: 'table', label: t('scan.result.view.table') },
                    { value: 'log', label: t('scan.result.view.log') },
                  ]}
                />
                <label className="rsheet-auto">
                  <input
                    type="checkbox"
                    checked={autoOpen}
                    onChange={(event) => {
                      setAutoOpen(event.target.checked)
                      writeAutoOpen(event.target.checked)
                    }}
                  />
                  <span className="rsheet-auto-text">{t('scan.result.autoOpen')}</span>
                  <span className="rsheet-auto-short" aria-hidden="true">{t('scan.result.autoOpenShort')}</span>
                </label>
              </>
            )}
            {fixed && onUseFixed && (
              <Button size="small" variant="primary" onClick={onUseFixed}>{t('scan.result.useFixed')}</Button>
            )}
            {fixed && (
              <Button size="small" variant={onUseFixed ? 'default' : 'primary'} onClick={() => saveText(fixed, name)}>{t('scan.result.download')}</Button>
            )}
            {open && (
              <>
                <Button size="small" className="rsheet-sizebtn" aria-label={t('scan.result.size')} onClick={() => onSize(NEXT_SIZE[size])}>↕</Button>
                <Button size="small" className="rsheet-close" aria-label={t('scan.result.close')} onClick={() => onSize('min')}>✕</Button>
              </>
            )}
          </span>
        </div>
        </div>

        {open && (
          <>
            {/* The verdict first, large and in its colour: the one thing someone
                opened the scanner to learn. The table below is the detail. */}
            <div className={`rsheet-banner ${flagged ? (counts.bad ? 'bad' : 'warn') : 'ok'}`} role="status">
              <span className="rb-icon" aria-hidden="true">{flagged ? (counts.bad ? '✕' : '!') : '✓'}</span>
              <span className="rb-text">
                <strong>{flagged ? t('scan.result.notReady', { build: result.build }) : t('scan.result.ready', { build: result.build })}</strong>
                <span>{flagged ? `${problems.join(t('scan.result.and'))}. ${fixLine}` : t('scan.result.allOk', { count: counts.ok })}</span>
              </span>
              <span className="rb-counts">
                <span className="ok"><b>{counts.ok}</b>{t('scan.result.tone.ok')}</span>
                <span className="bad"><b>{counts.bad}</b>{t('scan.result.tone.bad')}</span>
                <span className="warn"><b>{counts.warn}</b>{t('scan.result.tone.warn')}</span>
              </span>
            </div>
            <div className="rsheet-legend">
              <span><i className="b" /><strong>{t('scan.result.tone.bad')}</strong> {t('scan.result.legend.bad')}</span>
              <span><i className="w" /><strong>{t('scan.result.tone.warn')}</strong> {t('scan.result.legend.warn')}</span>
              <span><i className="c" /><strong>{t('scan.result.tone.ok')}</strong> {t('scan.result.legend.ok')}</span>
            </div>
            <div className="rsheet-body">
              {view === 'log' ? (
                <pre className="rsheet-log">
                  {log.split('\n').map((line, index) => (
                    <span key={index} className={line.startsWith('  ✓') ? 'ok' : line.startsWith('  ✗') ? 'bad' : line.startsWith('  !') ? 'warn' : undefined}>
                      {line}
                      {'\n'}
                    </span>
                  ))}
                </pre>
              ) : shown.length === 0 ? (
                <p className="rsheet-empty">{t('scan.result.empty')}</p>
              ) : (
                <div className="rsheet-table">
                  <div className="rsheet-tr rsheet-th" aria-hidden="true">
                    <span />
                    <span>{t('scan.result.col.name')}</span>
                    <span className="kd">{t('scan.result.col.kind')}</span>
                    <span>Windows</span>
                    <span>Linux</span>
                    <span className="num">{t('scan.result.col.line')}</span>
                  </div>
                  {shown.map((item) => {
                    const flaggedRow = item.tone === 'bad' || item.tone === 'warn'
                    return (
                      <div className={`rsheet-item t-${item.tone}`} key={item.row.name}>
                        <button
                          type="button"
                          className="rsheet-tr"
                          disabled={item.line === null}
                          aria-label={item.line !== null ? `${item.row.name}: ${t('scan.result.jump', { line: item.line })}` : item.row.name}
                          onClick={() => {
                            if (item.line === null) return
                            onJump(item.line)
                            if (size === 'full') onSize('half')
                          }}
                        >
                          <span className="mk" aria-hidden="true" />
                          <span className="nm">
                            {item.row.name}
                            {(() => {
                              const seen = inferredOf(item.row)
                              return seen ? (
                                <small className="rsheet-inferred" title={t('scan.result.inferredTitle', { how: t(`scan.result.inferredBy.${seen.how.startsWith('address') ? 'address' : 'name'}`) })}>
                                  {t('scan.result.inferred', { symbol: seen.symbol })}
                                </small>
                              ) : null
                            })()}
                          </span>
                          <span className="kd">{item.row.kind ?? ''}</span>
                          {PLATFORMS.map((platform) => {
                            const info = item.row.platforms[platform]
                            return (
                              <span key={platform} className={`pc t-${info ? platformTone(info) : 'neutral'}`} title={info?.status}>
                                {cellText(info)}
                              </span>
                            )
                          })}
                          <span className="num">{item.line ?? ''}</span>
                        </button>
                        {flaggedRow && (
                          <div className="rsheet-why">
                            <span>{reason(item)}</span>
                            {(() => {
                              const old = item.worst && aged?.(item.row.name, item.worst.platform)
                              return old ? <span className="rsheet-aged">{t('scan.result.aged', { since: old.since, until: old.until })}</span> : null
                            })()}
                            {item.fixes.length > 0 ? item.fixes.map((fix) => {
                              const key = `${fix.key}:${fix.platform}`
                              return (
                                <span className="rsheet-fix" key={key}>
                                  <span className="lbl">{t('scan.result.newValue', { platform: PLATFORM_LABEL[fix.platform] })}</span>
                                  <code>{String(fix.to)}</code>
                                  <Button size="small" onClick={() => copyValue(key, String(fix.to))}>
                                    {copiedKey === key ? t('check.copied') : t('scan.result.copyValue')}
                                  </Button>
                                </span>
                              )
                            }) : <span className="text-muted-foreground">{t('scan.result.noFix')}</span>}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
            {/* The tally once more where the list ends, each count in its colour,
                so it is the last thing read as well as the first. */}
            <p className="rsheet-foot" role="status">
              <span className="lbl">{t('scan.result.footLabel')}</span>
              <span className="ok">{t('scan.result.passed', { count: counts.ok })}</span>
              <span className="sep">·</span>
              <span className="bad">{t('scan.result.errors', { count: counts.bad })}</span>
              <span className="sep">·</span>
              <span className="warn">{t('scan.result.warnings', { count: counts.warn })}</span>
            </p>
          </>
        )}
      </section>
    </>
  )
}

/**
 * The sheet while a scan runs. It opens at once on "Scan it", so the answer
 * arrives where the eye already is instead of somewhere below the file.
 */
export function ScanningSheet({ keys, build, size, onSize }: { keys: number; build?: string; size: SheetSize; onSize(size: SheetSize): void }) {
  const { t } = useTranslation()
  const open = size === 'half' || size === 'full'
  return (
    <>
      {open && <div className="rsheet-dim" aria-hidden="true" onClick={() => onSize('min')} />}
      <section className="rsheet" data-size={size} aria-label={t('scan.result.title')} aria-busy="true">
        <button type="button" className="rsheet-handle" aria-label={t('scan.result.size')} onClick={() => onSize(open ? 'min' : 'half')}>
          <span />
        </button>
        <div className="rsheet-head">
          <h2>{t('scan.result.title')}</h2>
          <span className="rsheet-sum run" role="status">
            <span className="rsheet-spin" aria-hidden="true" />
            {t('scan.result.running')}
          </span>
          {open && (
            <span className="rsheet-acts">
              <Button size="small" className="rsheet-close" aria-label={t('scan.result.close')} onClick={() => onSize('min')}>✕</Button>
            </span>
          )}
        </div>
        {open && (
          <div className="rsheet-running">
            <div className="rsheet-progress" aria-hidden="true"><i /></div>
            <p>{t('scan.result.runningSub', { count: keys, build: build || '…' })}</p>
            <p className="muted">{t('scan.result.runningWait')}</p>
          </div>
        )}
      </section>
    </>
  )
}
