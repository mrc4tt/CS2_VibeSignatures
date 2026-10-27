import { useTranslation } from 'react-i18next'
import { Alert, Button, ChipGroup, Dot, Select } from '../../ui/primitives'
import { DEEP_SCAN_API, DeepScanError, type DeepScanResult, type Platform } from './deepScan'
import type { GameDataFormat } from './parse'
import type { KeyState } from './verdict'

export type ScanPlatform = Platform | 'both'

interface Props {
  plugin?: string
  format: GameDataFormat
  keys: number
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
  plugin, format, keys, platform, onPlatform, builds, build, onBuild,
  pending, error, result, onScan, summary, problems, onNext,
}: Props) {
  const { t } = useTranslation()
  const failure = error instanceof DeepScanError ? error : null
  const host = new URL(DEEP_SCAN_API).host

  return (
    <aside className="scanpanel flex flex-col gap-4 self-start rounded-[12px] border border-rule-strong bg-card p-4">
      <strong className="font-display text-[15px] text-ink">{t('check.side.h')}</strong>

      <div className="flex flex-col gap-1.5">
        <span className="text-[12px] uppercase tracking-wide text-muted-foreground">{t('check.side.platform')}</span>
        <ChipGroup
          label={t('check.side.platform')}
          value={platform}
          onValueChange={(next) => onPlatform(next as ScanPlatform)}
          items={[
            { value: 'both', label: t('check.side.both') },
            { value: 'linux', label: t('check.platform.linux') },
            { value: 'windows', label: t('check.platform.windows') },
          ]}
        />
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

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
        <dt className="text-muted-foreground">{t('check.side.plugin')}</dt>
        <dd className="m-0 truncate text-ink">{result?.matched?.plugin ?? plugin ?? t('check.side.unknown')}</dd>
        <dt className="text-muted-foreground">{t('check.side.format')}</dt>
        <dd className="m-0 text-ink">{format.toUpperCase()}</dd>
        <dt className="text-muted-foreground">{t('check.side.entries')}</dt>
        <dd className="m-0 text-ink">{keys}</dd>
      </dl>

      <div className="flex flex-col gap-1.5">
        <Button variant="primary" disabled={pending} onClick={onScan}>
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
