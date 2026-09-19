import { useTranslation } from 'react-i18next'
import { Key, Modal } from '../ui/primitives'

/** macOS spells the modifier ⌘; everywhere else it is Ctrl. */
const MOD = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent) ? '⌘' : 'Ctrl'

/**
 * Every keyboard shortcut the site has, in one place. They existed before this
 * list did, and nothing on the page said so.
 */
export function ShortcutHelp({ open, onClose }: { open: boolean; onClose(): void }) {
  const { t } = useTranslation()
  const rows: Array<[string[], string]> = [
    [[MOD, 'K'], t('shortcuts.palette')],
    [['/'], t('shortcuts.search')],
    [['?'], t('shortcuts.help')],
    [['Esc'], t('shortcuts.close')],
    [['↑', '↓'], t('shortcuts.move')],
    [['Enter'], t('shortcuts.open')],
  ]
  return (
    <Modal open={open} onClose={onClose} title={t('shortcuts.title')}>
      <dl className="m-0 grid grid-cols-[auto_1fr] items-center gap-x-5 gap-y-2.5">
        {rows.map(([keys, what]) => (
          <div key={what} className="contents">
            <dt className="flex gap-1">{keys.map((key) => <Key key={key}>{key}</Key>)}</dt>
            <dd className="m-0 text-[13.5px] text-ink-2">{what}</dd>
          </div>
        ))}
      </dl>
    </Modal>
  )
}
