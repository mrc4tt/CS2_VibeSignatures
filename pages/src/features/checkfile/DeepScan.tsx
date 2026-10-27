import { useMutation } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { copyText } from '../../ui/clipboard'
import { saveText } from '../../ui/download'
import { Alert, Button, Dot, Tag } from '../../ui/primitives'
import { ValueChange } from '../../components/ValueChange'
import {
  DEEP_SCAN_API,
  DeepScanError,
  platformTone,
  requestDeepScan,
  rowTone,
  sortRows,
  type DeepPlatform,
  type DeepRow,
} from './deepScan'
import { applyFixes } from './patch'

/** Every verdict is a few words; the bad and doubtful ones are what this panel is for. */
const ROWS = 40

function PlatformLine({ platform, info }: { platform: 'linux' | 'windows'; info: DeepPlatform }) {
  const { t } = useTranslation()
  const extra = info.status === 'mismatch' && info.reference !== undefined
    ? t('check.deep.expected', { value: info.reference })
    : info.status === 'ambiguous' && info.count
      ? t('check.deep.hits', { count: info.count })
      : info.vtable && info.vtable !== 'ok'
        ? t('check.deep.vtable', { state: info.vtable })
        : ''
  return (
    <div className="kline">
      <span className="pl">{t(`check.platform.${platform}`)}</span>
      <span className="vals flex flex-wrap items-center gap-2">
        <Tag tone={platformTone(info) === 'neutral' ? 'neutral' : platformTone(info)}>{info.status}</Tag>
        {info.verification && <span className="text-[12px] text-muted-foreground">{t(`check.deep.verification.${info.verification}`)}</span>}
        {extra && <span className="text-[12px] text-ink-2">{extra}</span>}
      </span>
    </div>
  )
}

function Row({ row }: { row: DeepRow }) {
  const { t } = useTranslation()
  const tone = rowTone(row)
  return (
    <details className="krow" data-state={tone}>
      <summary>
        <code className="kname">{row.name}</code>
        <span className="kindbadge">{row.kind ?? ''}</span>
        <span className="pbadges">
          {(['linux', 'windows'] as const).map((platform) => {
            const info = row.platforms[platform]
            if (!info) return null
            const each = platformTone(info)
            return (
              <span className={`pbadge ${each === 'ok' ? 'ok' : each === 'bad' ? 'bad' : ''}`} key={platform}>
                {t(`check.platform.${platform}`)}
              </span>
            )
          })}
        </span>
      </summary>
      <div className="kdiff">
        {(['linux', 'windows'] as const).map((platform) => {
          const info = row.platforms[platform]
          return info ? <PlatformLine key={platform} platform={platform} info={info} /> : null
        })}
      </div>
    </details>
  )
}

export function DeepScan({ text, name }: { text: string; name: string }) {
  const { t } = useTranslation()
  const [showAll, setShowAll] = useState(false)
  const [copied, setCopied] = useState(false)
  const scan = useMutation({ mutationFn: () => requestDeepScan(text, name) })
  const result = scan.data
  const rows = useMemo(() => sortRows(result?.results ?? []), [result])
  const flagged = rows.filter((row) => rowTone(row) !== 'ok')
  const listed = showAll ? rows : flagged.slice(0, ROWS)
  const patched = useMemo(
    () => (result?.fixes?.length ? applyFixes(text, result.fixes) : null),
    [text, result],
  )
  const host = new URL(DEEP_SCAN_API).host
  const failure = scan.error instanceof DeepScanError ? scan.error : null

  return (
    <div className="deepscan flex flex-col gap-3 rounded-[12px] border border-rule-strong bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <strong className="font-display text-[15px] text-ink">{t('check.deep.h')}</strong>
          <span className="text-[12.5px] leading-relaxed text-ink-2">{t('check.deep.what')}</span>
          <span className="text-[12px] text-muted-foreground">{t('check.deep.privacy', { host })}</span>
        </div>
        <Button variant="primary" disabled={scan.isPending} onClick={() => { setCopied(false); scan.mutate() }}>
          {scan.isPending ? t('check.deep.running') : result ? t('check.deep.again') : t('check.deep.run')}
        </Button>
      </div>

      {scan.isError && (
        <Alert
          tone="bad"
          title={t(`check.deep.error.${failure?.reason ?? 'failed'}`)}
          description={failure?.reason === 'rejected' ? failure.detail : undefined}
        />
      )}

      {result?.note && <Alert tone="warn" title={t('check.deep.unreadable')} description={result.note} />}

      {result && !result.note && (
        <>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-ink-2">
            <span>{t('check.deep.build', { build: result.build })}</span>
            <span>
              {result.matched
                ? t('check.deep.matched', { plugin: result.matched.plugin })
                : t('check.deep.unmatched')}
            </span>
            {(['verified', 'contradicted', 'unverified', 'upstream'] as const).map((state) =>
              result.verification?.[state] ? (
                <span className="inline-flex items-center gap-1.5" key={state}>
                  <Dot tone={state === 'verified' ? 'ok' : state === 'contradicted' ? 'bad' : state === 'unverified' ? 'warn' : 'neutral'} />
                  {result.verification[state]} {t(`check.deep.verification.${state}`)}
                </span>
              ) : null,
            )}
          </div>

          <Alert
            tone={result.unhealthy ? 'bad' : 'ok'}
            title={result.unhealthy
              ? t('check.deep.unhealthy', { count: result.unhealthy, build: result.build })
              : t('check.deep.healthy', { build: result.build })}
          />

          {patched && patched.applied > 0 && (
            <div className="fixit">
              <div className="fixhead">
                <strong>{t('check.deep.fixH')}</strong>
                <span>{t('check.fixSub', { applied: patched.applied })}</span>
              </div>
              <div className="flex flex-col gap-1">
                {result.fixes!.filter((fix) => !patched.skipped.some((s) => s.key === fix.key && s.platform === fix.platform)).map((fix) => (
                  <div className="kline" key={`${fix.key}-${fix.platform}`}>
                    <span className="pl"><code>{fix.key}</code> {t(`check.platform.${fix.platform}`)}</span>
                    <span className="vals">
                      <ValueChange
                        before={fix.from}
                        after={fix.to}
                        beforeLabel={t('check.yours')}
                        afterLabel={t(`check.deep.source.${fix.source}`)}
                        oldClassName="was"
                        newClassName="now"
                      />
                    </span>
                  </div>
                ))}
              </div>
              <div className="pactions">
                <Button variant="primary" onClick={() => saveText(patched.text, `${result.build}-${name}`)}>
                  {t('check.download')}
                </Button>
                <Button
                  onClick={() => {
                    void copyText(patched.text, { ok: t('clipboard.ok'), failed: t('clipboard.failed') }).then(setCopied)
                  }}
                >
                  {copied ? t('check.copied') : t('check.copy')}
                </Button>
              </div>
              {patched.skipped.length > 0 && (
                <p className="dznote">
                  {t('check.manual', { count: patched.skipped.length })}{' '}
                  {[...new Set(patched.skipped.map((entry) => entry.key))].join(', ')}
                </p>
              )}
            </div>
          )}

          {result.unhealthy && !patched?.applied ? <p className="dznote">{t('check.deep.noFix')}</p> : null}

          <div className="krowhead" aria-hidden="true">
            <span>{t('check.col.entry')}</span>
            <span>{t('check.col.kind')}</span>
            <span>{t('check.col.platform')}</span>
          </div>
          <div className="krows">
            {listed.map((row) => <Row row={row} key={row.name} />)}
            {listed.length === 0 && <p className="plain">{t('check.deep.allVerified')}</p>}
          </div>
          {!showAll && rows.length > listed.length && (
            <Button onClick={() => setShowAll(true)}>{t('check.deep.showAll', { count: rows.length })}</Button>
          )}
        </>
      )}
    </div>
  )
}
