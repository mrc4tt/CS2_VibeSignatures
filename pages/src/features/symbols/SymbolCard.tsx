import { useTranslation } from 'react-i18next'
import { requestNavigation } from '../../app/navigate'
import type { ValidatorWarning } from '../../api/siteData'
import { Pattern, PatternDump } from './Pattern'
import {
  adviceKind, factsOf, memberOffset, patternOf, slotPair, verdictOf, type SymbolEntry, type SymbolPlatform,
} from './pivot'

const SOURCE_ROOT = 'https://github.com/mrc4tt/CS2_VibeSignatures/blob/main/bin_artifacts'

function PlatformBox({ entry, platform }: { entry: SymbolEntry; platform: SymbolPlatform }) {
  const { t } = useTranslation()
  const record = entry[platform]
  const className = platform === 'linux' ? 'platbox l' : 'platbox w'
  if (!record) {
    return (
      <div className={className}>
        <span className="ph">{platform}</span>
        <span className="miss">{t('symbols2.noValue')}</span>
      </div>
    )
  }
  const facts = factsOf(record)
  const pattern = patternOf(record)
  const bits: string[] = []
  if (facts.slot !== undefined) bits.push(`${t('symbols2.slot')} ${facts.slot}`)
  if (facts.offset) bits.push(`${t('symbols2.offset')} ${facts.offset}`)
  if (facts.address) bits.push(`${t('symbols2.at')} ${facts.address}`)
  if (facts.size && facts.size !== '0x0') bits.push(`${t('symbols2.size')} ${facts.size}`)
  return (
    <div className={className}>
      <span className="ph">{platform}</span>
      <span className="row">{bits.join('  ·  ')}</span>
      {pattern ? <Pattern pattern={pattern} limit={14} /> : <span className="miss">{t('symbols2.slotOnly')}</span>}
    </div>
  )
}

interface Props {
  entry: SymbolEntry
  gameVersion: string
  warnings?: ValidatorWarning[]
  shippedBy?: Array<[string, string]>
  open: boolean
  detailReady: boolean
  onToggle(key: string): void
}

export function SymbolCard({ entry, gameVersion, warnings, shippedBy, open, detailReady, onToggle }: Props) {
  const { t } = useTranslation()
  const verdict = verdictOf(entry)
  const pattern = patternOf(entry.linux) ?? patternOf(entry.windows)
  const slots = slotPair(entry)
  const advice = adviceKind(entry)
  const adviceText =
    advice === 'member' ? t('symbols2.adviceMember', { offset: memberOffset(entry) ?? '?' })
      : advice === 'global' ? t('symbols2.adviceGlobal')
        : advice === 'vfunc' ? t('symbols2.adviceVfunc', { linux: slots?.linux ?? '?', windows: slots?.windows ?? '?' })
          : t('symbols2.adviceFunction')
  const sourcePlatform: SymbolPlatform = entry.linux ? 'linux' : 'windows'

  return (
    <div
      className="rescard"
      role="button"
      tabIndex={0}
      aria-expanded={open}
      data-key={entry.key}
      onClick={() => onToggle(entry.key)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onToggle(entry.key)
        }
      }}
    >
      <div className="top">
        <span className="nm">{entry.symbolName}</span>
        <span className="tag kind">{t(`symbols.kinds.${entry.kind}`, { defaultValue: entry.kind })}</span>
        <span className="tag mod">{entry.module}</span>
        {entry.aliases.length > 0 && <span className="tag mod">+{entry.aliases.length} alias</span>}
        {(warnings?.length ?? 0) > 0 && <span className="tag warn">{t('symbols2.advisory')}</span>}
      </div>
      <div className={`verdict ${verdict}`}>{t(`symbols2.verdict.${verdict}`)}</div>
      <p className="plain">{t(`symbols2.verdictBody.${verdict}`)}</p>
      <div className="platpair">
        <PlatformBox entry={entry} platform="linux" />
        <PlatformBox entry={entry} platform="windows" />
      </div>

      {open && (
        <div className="detail" onClick={(event) => event.stopPropagation()}>
          <div>
            <h3>{t('symbols2.whatToDo')}</h3>
            <p className="plain">{adviceText}</p>
          </div>

          {!detailReady && <p className="plain">{t('symbols2.loadingDetail')}</p>}

          {detailReady && pattern && (
            <div>
              <h3>{t('symbols2.fullPattern')}</h3>
              <PatternDump pattern={pattern} />
              <button
                type="button"
                className="btn small"
                style={{ marginTop: 8 }}
                onClick={() => void navigator.clipboard?.writeText(pattern)}
              >
                {t('symbols2.copyPattern')}
              </button>
            </div>
          )}

          {(warnings?.length ?? 0) > 0 && (
            <div>
              <h3>{t('symbols2.advisories')}</h3>
              <div className="chiprow">
                {warnings!.map((warning, index) => (
                  <span className="minichip warnc" key={index}>{warning.platform}: {warning.message}</span>
                ))}
              </div>
            </div>
          )}

          {(shippedBy?.length ?? 0) > 0 && (
            <div>
              <h3>{t('symbols2.shippedBy')}</h3>
              <div className="usedby">
                {shippedBy!.map(([file, key]) => (
                  <div className="u" key={`${file}/${key}`}>
                    <b>{file.split('/')[0]}</b>
                    <button
                      type="button"
                      onClick={() => requestNavigation({ view: 'gamedata', params: { file, find: key } })}
                    >
                      {key} &rsaquo;
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {entry.aliases.length > 0 && (
            <div>
              <h3>{t('symbols2.alsoKnownAs')}</h3>
              <div className="chiprow">
                {entry.aliases.map((alias) => (
                  <span className="minichip" key={alias}>{alias}</span>
                ))}
              </div>
            </div>
          )}

          <div>
            <h3>{t('symbols2.origin')}</h3>
            <dl className="kv">
              {entry.linux && <><dt>{t('symbols2.linuxFile')}</dt><dd>{entry.artifact}.linux.yaml</dd></>}
              {entry.windows && <><dt>{t('symbols2.windowsFile')}</dt><dd>{entry.artifact}.windows.yaml</dd></>}
              <dt>{t('symbols.module')}</dt><dd>{entry.module}</dd>
              {entry.className && <><dt>{t('symbols2.class')}</dt><dd>{entry.className}</dd></>}
            </dl>
          </div>

          <div>
            <h3>{t('symbols2.checked')}</h3>
            <div className="checkline">
              <span>{t('symbols2.check1')}</span>
              <span>{t('symbols2.check2')}</span>
              <span>{t('symbols2.check3')}</span>
              {slots && <span>{t('symbols2.check4')}</span>}
            </div>
          </div>

          <div>
            <a
              className="ghlink"
              href={`${SOURCE_ROOT}/${encodeURIComponent(gameVersion)}/${encodeURIComponent(entry.module)}/${encodeURIComponent(`${entry.artifact}.${sourcePlatform}.yaml`)}`}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(event) => event.stopPropagation()}
            >
              {t('symbols2.openSource')} &rsaquo;
            </a>
          </div>
        </div>
      )}
    </div>
  )
}
