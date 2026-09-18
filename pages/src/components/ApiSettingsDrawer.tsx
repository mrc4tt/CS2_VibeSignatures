import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useApiConfig } from '../app/apiContext'
import { Alert, Button, Drawer, Field, Input, Paragraph, Space } from '../ui/primitives'

interface Props {
  open: boolean
  onClose(): void
}

export function ApiSettingsDrawer({ open, onClose }: Props) {
  const { baseUrl, changeBaseUrl, disconnect } = useApiConfig()
  const { t } = useTranslation()
  const [value, setValue] = useState(baseUrl)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => setValue(baseUrl), [baseUrl, open])

  function save() {
    try {
      changeBaseUrl(value)
      setError(null)
      onClose()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('errors.invalidApiAddress'))
    }
  }

  return (
    <Drawer title={t('settings.title')} open={open} onClose={onClose} width={440}>
      <Field label={t('settings.baseUrl')} htmlFor="api-base-url">
        <Input id="api-base-url" value={value} onChange={(event) => setValue(event.target.value)} />
      </Field>
      {error && <Alert tone="bad" title={error} />}
      <Paragraph className="settings-help text-[13px] text-muted">{t('settings.help')}</Paragraph>
      <Space>
        <Button variant="primary" onClick={save}>{t('settings.saveAndReconnect')}</Button>
        <Button onClick={disconnect}>{t('settings.disconnect')}</Button>
      </Space>
    </Drawer>
  )
}
