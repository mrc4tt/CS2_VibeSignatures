import { useTranslation } from 'react-i18next'
import { PlayIcon } from '../../ui/icons'
import { Alert, Button, Dot, Select } from '../../ui/primitives'
import { DEEP_SCAN_API, DeepScanError, type DeepScanResult, type Platform, type ScanHealth } from './deepScan'
import type { FileDetails } from './details'
import type { GameDataFormat } from './parse'
import type { KeyState } from './verdict'

export type ScanPlatform = Platform | 'both'

interface Props {
  plugin?: string
  format: GameDataFormat
  details: FileDetails
  /** The scan server's load; the row hides when it cannot be reached. */
  health?: ScanHealth
  platform: ScanPlatform
  onPlatform(next: ScanPlatform): void
  /** Builds the scan server holds binaries for, newest first; the picker hides without them. */
  builds: string[]
  build: string
  onBuild(next: string): void
  pending: boolean
  error: unknown
  result?: DeepScanResult
  onScan(): void
  /** The browser check's counts, shown until a scan replaces them. */
  summary?: Record<KeyState, number>
  problems: number
  onNext(): void
}

const VERIFICATION_TONE = { verified: 'ok', contradicted: 'bad', unverified: 'warn', upstream: 'neutral' } as const

/**
 * What a scan will be run with and what came back, in one column beside the
 * file. The settings are few on purpose: the service defaults to its newest
 * build and both platforms, which is what almost every visitor wants.
 */
export function ScanPanel({
  plugin, format, details, health, platform, onPlatform, builds, build, onBuild,
  pending, error, result, onScan, summary, problems, onNext,
}: Props) {
  const { t } = useTranslation()
  const failure = error instanceof DeepScanError ? error : null
  const host = new URL(DEEP_SCAN_API).host

  return (
    <aside className="scanpanel flex flex-col gap-4 self-start rounded-[12px] border border-rule-strong bg-card p-4">
      <strong className="font-display text-[15px] text-ink">{t('check.side.h')}</strong>

      <div className="flex flex-col gap-1.5">
        <span id="scan-platform" className="text-[12px] uppercase tracking-wide text-muted-foreground">{t('check.side.platform')}</span>
        {/* Three filled segments rather than chips: it is one setting with
            three answers, and the chosen one should be unmissable. */}
        <div role="radiogroup" aria-labelledby="scan-platform" className="grid grid-cols-3 overflow-hidden rounded-[9px] border border-rule-strong">
          {(['windows', 'linux', 'both'] as const).map((value) => (
            <button
              type="button"
              role="radio"
              aria-checked={platform === value}
              key={value}
              onClick={() => onPlatform(value)}
              className={[
                'border-l border-rule-strong px-2 py-2.5 text-[13px] transition-colors first:border-l-0',
                platform === value ? 'bg-ink font-semibold text-card' : 'bg-card-2 text-ink-2 hover:text-ink',
              ].join(' ')}
            >
              {t(`check.side.${value}`)}
            </button>
          ))}
        </div>
      </div>

      {builds.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <label htmlFor="scan-build" className="text-[12px] uppercase tracking-wide text-muted-foreground">
            {t('check.side.build')}
          </label>
          <Select id="scan-build" value={build} onChange={(event) => onBuild(event.target.value)}>
            <option value="">{t('check.side.newest', { build: builds[0] })}</option>
            {builds.slice(1).map((entry) => <option key={entry} value={entry}>{entry}</option>)}
          </Select>
        </div>
      )}

      <div className="flex flex-col gap-2 rounded-[10px] bg-card-2 p-3.5">
        <strong className="text-[13px] text-ink">{t('check.side.details')}</strong>
        <dl className="details grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 text-[13px]">
          <dt className="text-muted-foreground">{t('check.side.plugin')}</dt>
          <dd className="m-0 truncate text-right font-mono text-ink">{result?.matched?.plugin ?? plugin ?? t('check.side.unknown')}</dd>
          <dt className="text-muted-foreground">{t('check.side.version')}</dt>
          <dd className="m-0 text-right font-mono text-ink">{result?.build ?? (build || builds[0] || '-')}</dd>
          <dt className="text-muted-foreground">{t('check.side.format')}</dt>
          <dd className="m-0 text-right font-mono text-ink">{format.toUpperCase()}</dd>
          <dt className="text-muted-foreground">{t('check.side.signatures')}</dt>
          <dd className="m-0 text-right font-mono text-ink">{details.signatures}</dd>
          <dt className="text-muted-foreground">{t('check.side.offsets')}</dt>
          <dd className="m-0 text-right font-mono text-ink">{details.offsets}</dd>
          {details.vtables > 0 && (
            <>
              <dt className="text-muted-foreground">{t('check.side.vtables')}</dt>
              <dd className="m-0 text-right font-mono text-ink">{details.vtables}</dd>
            </>
          )}
          <dt className="text-muted-foreground">{t('check.side.libraries')}</dt>
          <dd className="m-0 truncate text-right font-mono text-ink">{details.libraries.join(', ') || '-'}</dd>
          {health && health.capacity > 0 && (
            <>
              <dt className="mt-1.5 border-t border-rule pt-1.5 text-muted-foreground">{t('check.side.server')}</dt>
              <dd className="m-0 mt-1.5 border-t border-rule pt-1.5 text-right font-mono text-ink">
                {t('check.side.load', { inflight: health.inflight, capacity: health.capacity })}
              </dd>
            </>
          )}
        </dl>
      </div>

      <div className="flex flex-col gap-1.5">
        <Button variant="primary" size="large" className="w-full" disabled={pending} onClick={onScan}>
          <PlayIcon size={14} />
          {pending ? t('check.deep.running') : result ? t('check.deep.again') : t('check.deep.run')}
        </Button>
        <span className="text-[12px] leading-relaxed text-muted-foreground">{t('check.deep.what')}</span>
        <span className="text-[12px] leading-relaxed text-muted-foreground">{t('check.deep.privacy', { host })}</span>
      </div>

      {Boolean(error) && (
        <Alert
          tone="bad"
          title={t(`check.deep.error.${failure?.reason ?? 'failed'}`)}
          description={failure?.reason === 'rejected' ? failure.detail : undefined}
        />
      )}

      {result && !result.note ? (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-2">
          {(['verified', 'contradicted', 'unverified', 'upstream'] as const).map((state) =>
            result.verification?.[state] ? (
              <span className="inline-flex items-center gap-1.5" key={state}>
                <Dot tone={VERIFICATION_TONE[state]} />
                {result.verification[state]} {t(`check.deep.verification.${state}`)}
              </span>
            ) : null,
          )}
        </div>
      ) : summary ? (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-2">
          {(['outdated', 'current', 'unknown'] as const).map((state) =>
            summary[state] ? (
              <span className="inline-flex items-center gap-1.5" key={state}>
                <Dot tone={state === 'outdated' ? 'bad' : state === 'current' ? 'ok' : 'warn'} />
                {summary[state]} {t(`check.state.${state}`)}
              </span>
            ) : null,
          )}
        </div>
      ) : null}

      {problems > 0 && <Button onClick={onNext}>{t('check.side.next', { count: problems })}</Button>}
    </aside>
  )
}
