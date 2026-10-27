import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, ChipGroup } from '../../ui/primitives'
import { ValueChange } from '../../components/ValueChange'
import { Pattern } from '../symbols/Pattern'
import type { CheckSummary, KeyState, KeyVerdict } from './verdict'

const STATES: KeyState[] = ['outdated', 'current', 'unknown', 'absent']

/** One tone per state, so a number reads the same here as anywhere else on the site. */
const STATE_TONE: Record<KeyState, 'bad' | 'ok' | 'warn' | 'neutral'> = {
  outdated: 'bad',
  current: 'ok',
  unknown: 'warn',
  absent: 'neutral',
}
const STATE_NUMBER = { bad: 'text-bad', ok: 'text-ok', warn: 'text-warn', neutral: 'text-ink' } as const
/** Signatures are long; a page of them at a time keeps the list readable. */
const ROWS = 25

function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <em>—</em>
  const text = typeof value === 'string' ? value : String(value)
  return /^[0-9A-Fa-f?\s\\x]{8,}$/.test(text) ? <Pattern pattern={text} /> : <span>{text}</span>
}

/**
 * Every key of the file in four groups, one group at a time.
 *
 * Four states, and they are this checker's own: it compares your file against
 * published values, so it can say a value is current or out of date, but not
 * the things verify_plugin_gamedata says after scanning the binaries. Naming
 * them its way would claim a distinction this data cannot support.
 */
export function KeyList({ verdicts, summary, newest }: {
  verdicts: KeyVerdict[]
  summary: CheckSummary
  newest?: string
}) {
  const { t } = useTranslation()
  const [show, setShow] = useState<KeyState>('outdated')
  const [limit, setLimit] = useState(ROWS)
  const filtered = verdicts.filter((verdict) => verdict.state === show)
  const shown = filtered.slice(0, limit)

  return (
    <>
      <ChipGroup
        variant="card"
        label={t('check.statesLabel')}
        value={show}
        onValueChange={(state) => { setShow(state as KeyState); setLimit(ROWS) }}
        className="grid w-full grid-cols-2 items-stretch gap-3 lg:grid-cols-4"
        items={STATES.map((state) => ({
          value: state,
          disabled: summary[state] === 0,
          label: (
            <>
              {/* `v` is the hook CheckFilePage.test.tsx reads the count through. */}
              <span className={`v font-display text-[28px] font-bold leading-none ${STATE_NUMBER[STATE_TONE[state]]}`}>
                {summary[state]}
              </span>
              <span className="text-[12px] uppercase tracking-wide text-muted-foreground">{t(`check.state.${state}`)}</span>
            </>
          ),
        }))}
      />

      <p className="plain prose dznote">{t(`check.meaning.${show}`)}</p>

      {/*
        A table's header over a list of <details>, not a real <table>.
        The rows stay disclosures because a signature is 40+ bytes and
        dumping every one inline is what the folding was for; the
        header and the column grid are what make it scannable.
      */}
      <div className="krowhead" aria-hidden="true">
        <span>{t('check.col.entry')}</span>
        <span>{t('check.col.kind')}</span>
        <span>{t('check.col.platform')}</span>
      </div>
      <div className="krows">
        {shown.map((verdict) => (
          <details className="krow" data-state={verdict.state} key={`${verdict.state}-${verdict.key}`}>
            <summary>
              <code className="kname">{verdict.key}</code>
              <span className="kindbadge">
                {t(`check.kind.${
                  typeof (verdict.expected?.[0] ?? verdict.mine?.linux ?? verdict.expected?.[1] ?? verdict.mine?.windows) === 'number'
                    ? 'offset'
                    : 'signature'
                }`)}
              </span>
              {/* One grid cell, so the badges line up down the column. */}
              <span className="pbadges">
                {(['linux', 'windows'] as const).map((platform) => {
                  const ok = platform === 'linux' ? verdict.linuxOk : verdict.windowsOk
                  if (verdict.state !== 'outdated' && verdict.state !== 'current') return null
                  if (ok === undefined) return null
                  return (
                    <span className={`pbadge ${ok ? 'ok' : 'bad'}`} key={platform}>
                      {t(`check.platform.${platform}`)}
                    </span>
                  )
                })}
              </span>
            </summary>
            <div className="kdiff">
              {(['linux', 'windows'] as const).map((platform, index) => {
                const mineValue = verdict.mine?.[platform]
                const theirsValue = verdict.expected?.[index]
                if (mineValue == null && theirsValue == null) return null
                const ok = platform === 'linux' ? verdict.linuxOk : verdict.windowsOk
                return (
                  <div className="kline" key={platform}>
                    <span className="pl">{t(`check.platform.${platform}`)}</span>
                    <span className="vals">
                      {verdict.state === 'outdated' && ok === false ? (
                        // `was`/`now` are the hooks CheckFilePage.test.tsx reads the two values through.
                        <ValueChange
                          before={mineValue}
                          after={theirsValue}
                          beforeLabel={t('check.yours')}
                          afterLabel={`${t('check.published')} ${newest ?? ''}`.trim()}
                          oldClassName="was"
                          newClassName="now"
                          copyable
                        />
                      ) : (
                        <span className="same"><Value value={verdict.state === 'unknown' ? mineValue : theirsValue} /></span>
                      )}
                    </span>
                  </div>
                )
              })}
            </div>
          </details>
        ))}
        {shown.length === 0 && <p className="plain">{t('check.none')}</p>}
      </div>

      {filtered.length > shown.length && (
        <Button onClick={() => setLimit(filtered.length)}>
          {t('check.showAll', { count: filtered.length - shown.length })}
        </Button>
      )}
    </>
  )
}
