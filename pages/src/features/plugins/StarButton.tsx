import { useTranslation } from 'react-i18next'
import { StarIcon } from '../../ui/icons'
import { Button } from '../../ui/primitives'

/** Pins a plugin to the top of the list for this viewer; see readStarred. */
export function StarButton({ starred, plugin, onToggle }: { starred: boolean; plugin: string; onToggle(): void }) {
  const { t } = useTranslation()
  const label = starred ? t('home.unstar', { plugin }) : t('home.star', { plugin })
  return (
    <Button
      variant="text"
      className={starred ? 'starbtn on' : 'starbtn'}
      aria-pressed={starred}
      aria-label={label}
      title={label}
      onClick={onToggle}
    >
      <StarIcon size={18} filled={starred} />
    </Button>
  )
}
