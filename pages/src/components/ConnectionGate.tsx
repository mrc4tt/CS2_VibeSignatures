import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { ApiError } from '../api/client'
import { useApiConfig } from '../app/apiContext'
import { ApiIcon, SettingsIcon } from '../ui/icons'
import { Alert, Button, Card, Paragraph, Space, Title } from '../ui/primitives'

function connectionHint(error: Error, t: TFunction): string {
  if (error instanceof ApiError && error.detail.code === 'redis_unavailable') {
    return t('connection.redisUnavailable')
  }
  return t('connection.hint')
}

export function ConnectionGate({ onSettings }: { onSettings(): void }) {
  const { baseUrl, connect, connecting, connectionError } = useApiConfig()
  const { t } = useTranslation()
  return (
    <div className="connection-wrap">
      <Card className="connection-card p-7">
          <Space direction="vertical" size="large" className="full-width" align="start">
            <div className="flex flex-col gap-2">
              <Title level={2}>{t('connection.title')}</Title>
              <Paragraph className="text-muted-foreground">
                {t('connection.descriptionBefore')}
                <code className="mx-1 rounded bg-sunk px-1.5 py-0.5 text-[13px] text-ink">{baseUrl}</code>
                {t('connection.descriptionAfter')}
              </Paragraph>
            </div>
            {connectionError && (
              <Alert tone="bad" title={connectionError.message} description={connectionHint(connectionError, t)} />
            )}
            <Space>
              <Button
                variant="primary"
                size="large"
                icon={<ApiIcon />}
                loading={connecting}
                onClick={() => void connect().catch(() => undefined)}
              >
                {t('connection.connect')}
              </Button>
              <Button size="large" icon={<SettingsIcon />} onClick={onSettings}>
                {t('connection.changeAddress')}
              </Button>
            </Space>
          </Space>
      </Card>
    </div>
  )
}
