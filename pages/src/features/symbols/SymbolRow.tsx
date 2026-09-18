import { useTranslation } from 'react-i18next'
import { Dot, Tag } from '../../ui/primitives'
import { adviceKind, slotPair, verdictOf, type SymbolEntry } from './pivot'

const VERDICT_TONE = { checked: 'ok', caveat: 'warn', onePlatform: 'neutral' } as const

/**
 * One line in the result list of the split view.
 *
 * Deliberately not a SymbolCard: the list is for scanning, so it carries only
 * what tells two symbols apart at a glance - the name, what kind of thing it is,
 * and whether it holds on both platforms. Everything else is in the detail pane.
 */
export function SymbolRow({
  entry,
  selected,
  onSelect,
}: {
  entry: SymbolEntry
  selected: boolean
  onSelect(key: string): void
}) {
  const { t } = useTranslation()
  const verdict = verdictOf(entry)
  const advice = adviceKind(entry)
  const slots = slotPair(entry)

  return (
    <button
      type="button"
      aria-current={selected || undefined}
      onClick={() => onSelect(entry.key)}
      className={[
        'rescard flex w-full flex-col gap-1.5 rounded-[10px] border px-3.5 py-3 text-left',
        selected ? 'border-rule-strong bg-card-2' : 'border-rule-soft bg-transparent hover:border-rule',
      ].join(' ')}
    >
      <span className="flex items-center gap-2">
        <span className="min-w-0 truncate font-mono text-[13px] text-ink">{entry.symbolName}</span>
      </span>
      <span className="flex flex-wrap items-center gap-2">
        {advice === 'vfunc' && slots ? (
          <Tag tone="qualify">
            {t('symbols2.slot')} {slots.linux ?? '—'}/{slots.windows ?? '—'}
          </Tag>
        ) : (
          <Tag tone="neutral">{t(`symbols2.kind.${advice}`, { defaultValue: advice })}</Tag>
        )}
        <span className="flex items-center gap-1.5 text-[11.5px] text-muted">
          <Dot tone={VERDICT_TONE[verdict]} />
          {entry.module}
        </span>
      </span>
    </button>
  )
}
