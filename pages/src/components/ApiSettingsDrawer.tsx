import { Alert, Button, Drawer, Form, Input, Space, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useApiConfig } from '../app/apiContext'

interface Props {
  open: boolean
  onClose(): void
}

export function ApiSettingsDrawer({ open, onClose }: Props) {
  const { baseUrl, changeBaseUrl, disconnect } = useApiConfig()
  const [value, setValue] = useState(baseUrl)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => setValue(baseUrl), [baseUrl, open])

  function save() {
    try {
      changeBaseUrl(value)
      setError(null)
      onClose()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'API 地址无效')
    }
  }

  return (
    <Drawer title="API 连接设置" open={open} onClose={onClose} width={440}>
      <Form layout="vertical">
        <Form.Item label="FastAPI Base URL">
          <Input value={value} onChange={(event) => setValue(event.target.value)} />
        </Form.Item>
        {error && <Alert type="error" message={error} showIcon />}
        <Typography.Paragraph type="secondary" className="settings-help">
          公网 Pages 中的请求由当前浏览器发起。默认地址只会访问当前电脑的
          127.0.0.1，不能访问另一台机器的 localhost。
        </Typography.Paragraph>
        <Space>
          <Button type="primary" onClick={save}>
            保存并重新连接
          </Button>
          <Button onClick={disconnect}>断开当前连接</Button>
        </Space>
      </Form>
    </Drawer>
  )
}
