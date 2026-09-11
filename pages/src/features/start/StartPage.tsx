import { useQuery } from '@tanstack/react-query'
import { Skeleton } from 'antd'
import { useTranslation } from 'react-i18next'
import { getSiteMeta } from '../../api/siteMeta'
import { Explain } from '../../components/Explain'
import type { AppView } from '../../app/appViews'

function formatWhen(iso: string, language: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  try {
    // dateStyle/timeStyle cannot be combined with timeZoneName, so name the
    // components: mixing them throws and silently loses the zone.
    return new Intl.DateTimeFormat(language, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
    }).format(date)
  } catch {
    return date.toLocaleString()
  }
}

function formatAgo(iso: string, language: string): string {
  const elapsed = Date.now() - new Date(iso).getTime()
  if (!Number.isFinite(elapsed)) return ''
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['minute', 60], ['hour', 24], ['day', 30], ['month', 12], ['year', Number.POSITIVE_INFINITY],
  ]
  let value = Math.round(elapsed / 60_000)
  let index = 0
  while (index < units.length - 1 && Math.abs(value) >= units[index][1]) {
    value = Math.round(value / units[index][1])
    index += 1
  }
  try {
    return new Intl.RelativeTimeFormat(language, { numeric: 'auto' }).format(-value, units[index][0])
  } catch {
    return ''
  }
}

export function StartPage({ onGo }: { onGo(view: AppView): void }) {
  const { t, i18n } = useTranslation()
  const language = i18n.resolvedLanguage ?? 'en'
  const metaQuery = useQuery({
    queryKey: ['site-meta'],
    queryFn: ({ signal }) => getSiteMeta(signal),
    staleTime: 5 * 60 * 1000,
  })
  const meta = metaQuery.data

  const tasks: Array<{ view: AppView; q: string; d: string }> = [
    { view: 'symbols', q: t('start.t1q'), d: t('start.t1d') },
    { view: 'gamedata', q: t('start.t2q'), d: t('start.t2d') },
    { view: 'gamedata', q: t('start.t3q'), d: t('start.t3d') },
    { view: 'words', q: t('start.t4q'), d: t('start.t4d') },
  ]
  const gap = meta ? meta.latest.pluginKeys - meta.latest.pluginKeysCovered : 0

  return (
    <div className="handbook">
      <div className="hero">
        <h1>{t('start.h1')}</h1>
        <p className="lede">{t('start.lede', { build: meta?.latest.gameVersion ?? '…' })}</p>
      </div>

      {meta && (
        <p className="buildline">
          <span>
            {t('start.read')} <b>{formatWhen(meta.latest.lastPublishTime, language)}</b>{' '}
            <span className="ago">{formatAgo(meta.latest.lastPublishTime, language)}</span>
          </span>
          <span>{t('start.fingerprint')} <b>{meta.latest.configSha256.replace(/^sha256:/, '').slice(0, 8)}</b></span>
        </p>
      )}

      <div className="tasks">
        {tasks.map((task) => (
          <button key={task.q} type="button" className="task" onClick={() => onGo(task.view)}>
            <span className="q">{task.q}</span>
            <span className="d">{task.d}</span>
          </button>
        ))}
      </div>

      <section className="panel">
        <header>
          <h2>{t('start.glanceH')}</h2>
          <span className="sub">{t('start.glanceSub')}</span>
        </header>
        {metaQuery.isLoading && <div className="panel-body"><Skeleton active paragraph={{ rows: 2 }} title={false} /></div>}
        {metaQuery.error && <div className="panel-body"><p className="plain">{metaQuery.error.message}</p></div>}
        {meta && (
          <div className="statgrid">
            <div className="stat">
              <span className="v">{meta.latest.symbolRecords}</span>
              <span className="l">{t('start.statSymbols')}</span>
            </div>
            <div className="stat okv">
              <span className="v">{meta.latest.pluginKeysCovered}</span>
              <span className="l">{t('start.statKeys', { total: meta.latest.pluginKeys })}</span>
            </div>
            <div className={gap > 0 ? 'stat warnv' : 'stat okv'}>
              <span className="v">{gap}</span>
              <span className="l">{t('start.statGap')}</span>
            </div>
            <div className="stat">
              <span className="v">{meta.builds.length}</span>
              <span className="l">{t('start.statBuilds')}</span>
            </div>
          </div>
        )}
        <div className="panel-body">
          <Explain html={t('start.explain')} />
        </div>
      </section>

      <section className="panel">
        <header><h2>{t('start.stepsH')}</h2></header>
        <div className="panel-body">
          <div className="steps">
            {[1, 2, 3, 4].map((step) => (
              <div className="step" key={step}>
                <span className="i">{step}</span>
                <span dangerouslySetInnerHTML={{ __html: t(`start.s${step}`) }} />
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
