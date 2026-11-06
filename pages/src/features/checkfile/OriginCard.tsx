import { useTranslation } from 'react-i18next'
import { Dot } from '../../ui/primitives'
import { pluginLabel } from '../gamedata/pluginLabel'
import { latestUrl } from '../plugins/pluginModel'
import type { Origin } from './origin'
import { coverageAnswer } from './originText'

/**
 * Which plugin the file belongs to, what loads it, where that plugin reads it, and
 * whether CounterStrikeSharp's updater will keep it current. Laid out like the
 * Details card beside it; every row says what it rests on.
 */
export function OriginCard({ origin }: { origin: Origin }) {
  const { t } = useTranslation()
  const { answer, tone } = coverageAnswer(origin)
  const base = import.meta.env.BASE_URL
  const plugin = origin.plugin
    ? pluginLabel(origin.plugin)
    : origin.candidates?.length
      ? t('scan.origin.either', { first: pluginLabel(origin.candidates[0]!), second: origin.candidates.slice(1).map(pluginLabel).join(', ') })
      : t('scan.origin.unknown')
  const readFrom = origin.reads === 'source'
    ? t('scan.origin.compiledIn', { file: origin.sourceFile })
    : origin.install
      ? origin.install
      : origin.framework && origin.framework !== 'cssharp' ? t('scan.origin.ownFolder') : t('scan.origin.notRecorded')

  return (
    <section className="flex flex-col gap-2 rounded-[10px] bg-card-2 p-3.5" aria-label={t('scan.origin.h')}>
      <strong className="text-[13px] text-ink">{t('scan.origin.h')}</strong>
      <dl className="origin-rows grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[13px]">
        <dt className="text-muted-foreground">{t('scan.origin.plugin')}</dt>
        <dd className="m-0 text-right font-mono text-ink [overflow-wrap:anywhere]">{plugin}</dd>
        <dt className="text-muted-foreground">{t('scan.origin.framework')}</dt>
        <dd className="m-0 text-right text-ink">
          {origin.framework ? t(`scan.origin.frameworks.${origin.framework}`) : t('scan.origin.unknown')}
        </dd>
        <dt className="text-muted-foreground">{t('scan.origin.readFrom')}</dt>
        <dd className={`m-0 text-right text-ink [overflow-wrap:anywhere] ${origin.install && origin.reads !== 'source' ? 'font-mono' : ''}`}>{readFrom}</dd>
        {origin.evidence && (
          <>
            <dt className="text-muted-foreground">{t('scan.origin.evidence')}</dt>
            <dd className="m-0 text-right text-ink">
              {origin.evidence === 'layout' && origin.layout
                ? t(`scan.origin.layouts.${origin.layout}`)
                : t(`scan.origin.evidenceKind.${origin.evidence}`, { build: origin.build })}
            </dd>
          </>
        )}
        <dt className="mt-1.5 border-t border-rule pt-1.5 text-muted-foreground">{t('scan.origin.update')}</dt>
        <dd className="m-0 mt-1.5 inline-flex items-center justify-end gap-1.5 border-t border-rule pt-1.5 text-right font-semibold text-ink">
          <Dot tone={tone} />
          {answer === 'unknown' ? t('scan.origin.unknown') : t(`scan.origin.${answer}`)}
        </dd>
      </dl>
      <p className="m-0 text-[12px] leading-relaxed text-muted-foreground">
        {t(`scan.origin.coverage.${origin.coverage}`, { file: origin.sourceFile })}
      </p>
      {origin.feeds.length > 0 && (
        <div className="flex flex-col gap-1 text-[12px]">
          <span className="text-muted-foreground">{t(origin.reads === 'source' ? 'scan.origin.latestReference' : 'scan.origin.latest')}</span>
          {origin.feeds.map((feed) => {
            const url = latestUrl({ descriptor: feed }, window.location.origin, base)
            return (
              <a key={url} className="font-mono text-[color:var(--accent-text)] [overflow-wrap:anywhere] hover:underline" href={url}>
                {`latest/${feed.plugin}/${feed.fileName}`}
              </a>
            )
          })}
        </div>
      )}
    </section>
  )
}
