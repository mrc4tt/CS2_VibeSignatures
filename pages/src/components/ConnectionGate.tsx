import { ApiOutlined, SettingOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Space, Typography } from 'antd'
import { ApiError } from '../api/client'
import { useApiConfig } from '../app/apiContext'

function connectionHint(error: Error): string {
  if (error instanceof ApiError && error.detail.code === 'redis_unavailable') {
    return 'FastAPI 已启动，但 Redis 尚未就绪。请检查 Redis 地址和服务状态。'
  }
  return '请确认 FastAPI 已启动、Pages Origin 已加入 CORS allowlist，并允许浏览器访问本地网络。'
}

export function ConnectionGate({ onSettings }: { onSettings(): void }) {
  const { baseUrl, connect, connecting, connectionError } = useApiConfig()
  return (
    <div className="connection-wrap">
      <Card className="connection-card">
        <Space orientation="vertical" size="large" className="full-width">
          <div>
            <Typography.Title level={2}>连接本地进度 API</Typography.Title>
            <Typography.Paragraph type="secondary">
              页面将从当前浏览器连接 <Typography.Text code>{baseUrl}</Typography.Text>，并检查 FastAPI
              与 Redis readiness。
            </Typography.Paragraph>
          </div>
          {connectionError && (
            <Alert
              type="error"
              showIcon
              message={connectionError.message}
              description={connectionHint(connectionError)}
            />
          )}
          <Space>
            <Button
              type="primary"
              size="large"
              icon={<ApiOutlined />}
              loading={connecting}
              onClick={() => void connect().catch(() => undefined)}
            >
              连接本地 API
            </Button>
            <Button size="large" icon={<SettingOutlined />} onClick={onSettings}>
              修改地址
            </Button>
          </Space>
        </Space>
      </Card>
    </div>
  )
}
