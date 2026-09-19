import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { differencesBetween, getSiteHistory } from '../../api/siteData'
import { Pattern } from '../symbols/Pattern'
import { Card, Select, Skeleton, Tag } from '../../ui/primitives'

function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <em className="text-faint">—</em>
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return /^[0-9A-Fa-f?\s]{8,}$/.test(text) ? <Pattern pattern={text} /> : <span className="font-mono">{text}</span>
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
                    <div className="flex min-w-0 flex-col gap-1 text-[11.5px] leading-relaxed">
                      {(['linux', 'windows'] as const).map((platform, index) => {
                        const before = difference.before?.[index]
                        const after = difference.after?.[index]
                        if (JSON.stringify(before) === JSON.stringify(after)) return null
                        return (
                          <div className="flex flex-col gap-0.5" key={platform}>
                            <span className="text-[10px] uppercase tracking-wide text-faint">{platform}</span>
                            <span className="text-bad"><Value value={before} /></span>
                            <span className="text-ok"><Value value={after} /></span>
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
