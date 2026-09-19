import { CopyIcon } from 'lucide-react'
import { Fragment, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { copyText } from '../ui/clipboard'
import { cn } from '../ui/cn'
import { Button } from '../ui/primitives'
import { byteTokens, diffTokens, isWildcard, type DiffToken } from './tokenDiff'

type Side = 'old' | 'new'

/** Red for the value being replaced, green for the one replacing it - the usual diff colours. */
export const SIDE = {
  old: { sign: '−', row: 'bg-bad-bg', label: 'text-bad', mark: 'bg-bad/25 text-bad' },
  new: { sign: '+', row: 'bg-ok-bg', label: 'text-ok', mark: 'bg-ok/25 text-ok' },
} as const

/** One side of a change: what it is (a build, "your file"), then its value. */
function Line({
  side,
  label,
  className,
  action,
  children,
}: {
  side: Side
  label: ReactNode
  className?: string
  action?: ReactNode
  children: ReactNode
}) {
  const { t } = useTranslation()
  return (
    <div
      className={cn(
        'grid items-baseline gap-x-2.5 rounded-[6px] px-2 py-1',
        action ? 'grid-cols-[auto_minmax(0,1fr)_auto]' : 'grid-cols-[auto_minmax(0,1fr)]',
        SIDE[side].row,
        className,
      )}
    >
      <span className={cn('select-none font-mono text-[10.5px] font-semibold tabular-nums', SIDE[side].label)}>
        <span aria-hidden="true">{SIDE[side].sign} </span>
        {label}
        <span className="sr-only"> ({t(`diff.${side}`)})</span>
      </span>
      <div className="min-w-0 break-words font-mono text-[11.5px] leading-relaxed text-ink">{children}</div>
      {action}
    </div>
  )
}

/**
 * Copies the new value exactly as the plugin file spells it. Someone fixing one
 * key by hand otherwise has to drag-select forty bytes out of a wrapped line.
 */
function CopyValue({ value }: { value: unknown }) {
  const { t } = useTranslation()
  const text = typeof value === 'string' ? value : String(value)
  return (
    <Button
      variant="text"
      size="small"
      className="size-6 self-center p-0 text-ok hover:text-ok"
      aria-label={t('diff.copyNew')}
      title={t('diff.copyNew')}
      onClick={() => void copyText(text, { ok: t('clipboard.ok'), failed: t('clipboard.failed') })}
    >
      <CopyIcon className="size-3.5" aria-hidden="true" />
    </Button>
  )
}

/**
 * Bytes, with each run of changed ones marked. The mark is <del>/<ins> rather
 * than a coloured span so that it survives without colour: a screen reader can
 * announce it, and it is still a distinct element when copied as HTML.
 */
function Bytes({ tokens, separator, side }: { tokens: DiffToken[]; separator: string; side: Side }) {
  const Mark = side === 'old' ? 'del' : 'ins'
  const runs: DiffToken[][] = []
  for (const item of tokens) {
    const last = runs[runs.length - 1]
    if (last && last[0].changed === item.changed) last.push(item)
    else runs.push([item])
  }
  return runs.map((run, index) => {
    const text = run.map((item) => item.token)
    const gap = index < runs.length - 1 ? separator : ''
    if (run[0].changed) {
      return (
        <Fragment key={index}>
          <Mark className={cn('rounded-[3px] px-[2px] font-semibold no-underline', SIDE[side].mark)}>{text.join(separator)}</Mark>
          {gap}
        </Fragment>
      )
    }
    return (
      <Fragment key={index}>
        {text.map((token, at) => (
          <span key={at} className={isWildcard(token) ? 'text-[color:var(--ghost)]' : undefined}>
            {token}
            {at < text.length - 1 ? separator : ''}
          </span>
        ))}
        {gap}
      </Fragment>
    )
  })
}

/** A value that is not bytes - a slot index, an offset - changed as a whole. */
function Whole({ value, side }: { value: unknown; side: Side }) {
  const { t } = useTranslation()
  if (value === null || value === undefined) return <em className="not-italic text-faint">{t('diff.absent')}</em>
  const Mark = side === 'old' ? 'del' : 'ins'
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return <Mark className={cn('rounded-[3px] px-[2px] font-semibold no-underline', SIDE[side].mark)}>{text}</Mark>
}

/**
 * The old value over the new one, with only what differs marked. Used by
 * Between builds (two builds) and Check my file (your file against the
 * published one). `oldClassName`/`newClassName` put hooks on each line.
 */
export function ValueChange({
  before,
  after,
  beforeLabel,
  afterLabel,
  oldClassName,
  newClassName,
  copyable = false,
}: {
  before: unknown
  after: unknown
  beforeLabel: ReactNode
  afterLabel: ReactNode
  oldClassName?: string
  newClassName?: string
  /** Offer a copy button for the new value. */
  copyable?: boolean
}) {
  const left = byteTokens(before)
  const right = byteTokens(after)
  // Both sides must be bytes in the same spelling for a byte-level diff to mean anything.
  const tokens = left && right && left.separator === right.separator ? diffTokens(left.tokens, right.tokens) : undefined
  const delta = typeof before === 'number' && typeof after === 'number' ? after - before : undefined
  return (
    <div className="flex flex-col gap-1">
      <Line side="old" label={beforeLabel} className={oldClassName}>
        {tokens ? <Bytes tokens={tokens.before} separator={left!.separator} side="old" /> : <Whole value={before} side="old" />}
      </Line>
      <Line
        side="new"
        label={afterLabel}
        className={newClassName}
        action={copyable && after !== null && after !== undefined ? <CopyValue value={after} /> : undefined}
      >
        {tokens ? <Bytes tokens={tokens.after} separator={right!.separator} side="new" /> : <Whole value={after} side="new" />}
        {delta !== undefined && (
          <span className="ml-2 text-[10.5px] text-muted-foreground">({delta > 0 ? '+' : ''}{delta})</span>
        )}
      </Line>
    </div>
  )
}
