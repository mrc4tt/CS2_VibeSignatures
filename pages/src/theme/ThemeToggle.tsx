import { useTranslation } from 'react-i18next'
import { MoonIcon, SunIcon } from '../ui/icons'
import { Button, Tooltip } from '../ui/primitives'
import { useTheme } from './themeContext'

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  const { t } = useTranslation()
  const isDark = theme === 'dark'
  const label = isDark ? t('theme.switchToLight') : t('theme.switchToDark')
  return (
    <Tooltip title={label}>
      <Button className="theme-toggle" aria-label={label} icon={isDark ? <SunIcon /> : <MoonIcon />} onClick={toggleTheme} />
    </Tooltip>
  )
}
