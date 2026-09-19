import { useQuery } from '@tanstack/react-query'
import { Fragment, useMemo, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { differencesBetween, getSiteHistory } from '../../api/siteData'
import { cn } from '../../ui/cn'
import { Card, Select, Skeleton, Tag } from '../../ui/primitives'
import { byteTokens, diffTokens, isByteString, type DiffToken } from './tokenDiff'

type Side = 'old' | 'new'

/** Red for what the older build had, green for what the newer one has - the usual diff colours. */
const SIDE = {
  old: { sign: '\u2212', row: 'bg-bad-bg', label: 'text-bad', mark: 'bg-bad/25 text-bad' },
  new: { sign: '+', row: 'bg-ok-bg', label: 'text-ok', mark: 'bg-ok/25 text-ok' },
} as const

/** One side of a change: the build it comes from, then its value. */
function Line({ side, build, children }: { side: Side; build: string; children: ReactNode }) {
  const { t } = useTranslation()
  return (
    <div className={cn('grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-2.5 rounded-[6px] px-2 py-1', SIDE[side].row)}>
      <span className={cn('select-none font-mono text-[10.5px] font-semibold tabular-nums', SIDE[side].label)}>
        <span aria-hidden="true">{SIDE[side].sign} </span>
        {build}
        <span className="sr-only"> ({t(`diff.${side}`)})</span>
      </span>
      <div className="min-w-0 break-words font-mono text-[11.5px] leading-relaxed text-ink">{children}</div>
    </div>
  )
}

/**
 * Bytes, with each run of changed ones marked. The mark is <del>/<ins> rather
 * than a coloured span so that it survives without colour: a screen reader can
 * announce it, and it is still a distinct element when copied as HTML.
 */
function Bytes({ tokens, side }: { tokens: DiffToken[]; side: Side }) {
  const Mark = side === 'old' ? 'del' : 'ins'
  const runs: DiffToken[][] = []
  for (const item of tokens) {
    const last = runs[runs.length - 1]
    if (last && last[0].changed === item.changed) last.push(item)
    else runs.push([item])
  }
  return runs.map((run, index) => {
    const text = run.map((item) => item.token)
    const gap = index < runs.length - 1 ? ' ' : ''
    if (run[0].changed) {
      return (
        <Fragment key={index}>
          <Mark className={cn('rounded-[3px] px-[2px] font-semibold no-underline', SIDE[side].mark)}>{text.join(' ')}</Mark>
          {gap}
        </Fragment>
      )
    }
    return (
      <Fragment key={index}>
        {text.map((token, at) => (
          <span key={at} className={token.startsWith('?') ? 'text-[color:var(--ghost)]' : undefined}>
            {token}
            {at < text.length - 1 ? ' ' : ''}
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

function Change({ before, after, from, to }: { before: unknown; after: unknown; from: string; to: string }) {
  const tokens = isByteString(before) && isByteString(after) ? diffTokens(byteTokens(before), byteTokens(after)) : undefined
  const delta = typeof before === 'number' && typeof after === 'number' ? after - before : undefined
  return (
    <div className="flex flex-col gap-1">
      <Line side="old" build={from}>
        {tokens ? <Bytes tokens={tokens.before} side="old" /> : <Whole value={before} side="old" />}
      </Line>
      <Line side="new" build={to}>
        {tokens ? <Bytes tokens={tokens.after} side="new" /> : <Whole value={after} side="new" />}
        {delta !== undefined && (
          <span className="ml-2 text-[10.5px] text-muted-foreground">({delta > 0 ? '+' : ''}{delta})</span>
        )}
      </Line>
    </div>
  )
}

/**
 * Everything that moved between two builds.
 *
 * The site could already say how far behind one file was; it could not answer
 * "I am on 14178b and going to 14181, what do I have to change", which is the
 * question someone who skipped a release actually has. All of it comes out of
 * history.json - nothing new had to be published for this page.
 */
export function DiffPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const historyQuery = useQuery({
    queryKey: ['history'],
    queryFn: ({ signal }) => getSiteHistory(signal),
    staleTime: Infinity,
  })
  const history = historyQuery.data
  const builds = useMemo(() => history?.builds.map((build) => build.gameVersion) ?? [], [history])
  const newest = builds[builds.length - 1]
  const from = params.get('from') ?? builds[builds.length - 2] ?? ''
  const to = params.get('to') ?? newest ?? ''

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    next.set(key, value)
    setParams(next, { replace: true })
  }

  const files = useMemo(() => differencesBetween(history, from, to), [history, from, to])
  const keyCount = files.reduce((total, file) => total + file.differences.length, 0)

  return (
    <div className="handbook stack">
      <div className="hero">
        <h1>{t('diff.h1')}</h1>
        <p className="lede">{t('diff.lede')}</p>
      </div>

      {historyQuery.isLoading && <Card><Skeleton rows={5} /></Card>}

      {history && (
        <>
          <Card className="flex flex-wrap items-end gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="diff-from" className="text-[12px] font-medium text-muted-foreground">{t('diff.from')}</label>
              <Select
                id="diff-from"
                className="min-w-[120px] font-mono"
                value={from}
                onChange={(event) => setParam('from', event.target.value)}
              >
                {builds.map((build) => <option key={build} value={build}>{build}</option>)}
              </Select>
            </div>
            <span className="pb-2.5 text-muted-foreground" aria-hidden="true">→</span>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="diff-to" className="text-[12px] font-medium text-muted-foreground">{t('diff.to')}</label>
              <Select
                id="diff-to"
                className="min-w-[120px] font-mono"
                value={to}
                onChange={(event) => setParam('to', event.target.value)}
              >
                {builds.map((build) => <option key={build} value={build}>{build}</option>)}
              </Select>
            </div>
            <span className="ml-auto pb-2.5 text-[13px] text-muted-foreground" role="status" aria-live="polite">
              {t('diff.summary', { keys: keyCount, files: files.length })}
            </span>
            {from !== to && (
              <div className="flex w-full flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
                <span className={cn('rounded-[5px] px-2 py-0.5 font-mono text-[11px] font-semibold', SIDE.old.row, SIDE.old.label)}>
                  {SIDE.old.sign} {from} {t('diff.old')}
                </span>
                <span className={cn('rounded-[5px] px-2 py-0.5 font-mono text-[11px] font-semibold', SIDE.new.row, SIDE.new.label)}>
                  {SIDE.new.sign} {to} {t('diff.new')}
                </span>
                <span>{t('diff.legend')}</span>
              </div>
            )}
          </Card>

          {files.length === 0 && (
            <Card><p className="m-0 text-[13px] text-muted-foreground">{t('diff.none', { from, to })}</p></Card>
          )}

          {files.map((file) => (
            <Card key={file.file} className="flex flex-col gap-3">
              <div className="flex items-baseline justify-between gap-4">
                <h2 className="font-mono text-[14px] font-medium text-ink">{file.file.split('/')[0]}</h2>
                <Tag tone="accent">{t('diff.keysMoved', { count: file.differences.length })}</Tag>
              </div>
              <div className="flex flex-col divide-y divide-[color:var(--rule-soft)]">
                {file.differences.map((difference) => (
                  <div key={difference.key} className="grid items-start gap-x-5 gap-y-2 py-2.5 lg:grid-cols-[minmax(0,260px)_minmax(0,1fr)]">
                    <code className="min-w-0 break-all font-mono text-[12.5px] text-ink">{difference.key}</code>
                    <div className="flex min-w-0 flex-col gap-2.5">
                      {(['linux', 'windows'] as const).map((platform, index) => {
                        const before = difference.before?.[index]
                        const after = difference.after?.[index]
                        if (JSON.stringify(before) === JSON.stringify(after)) return null
                        return (
                          <div className="flex flex-col gap-1" key={platform}>
                            <span className="text-[10px] uppercase tracking-wide text-faint">{platform}</span>
                            <Change before={before} after={after} from={from} to={to} />
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </>
      )}
    </div>
  )
}
