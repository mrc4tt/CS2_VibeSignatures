import { ApiOutlined, DashboardOutlined, GlobalOutlined, SettingOutlined } from '@ant-design/icons'
import { Badge, Button, Layout, Select, Space, Typography } from 'antd'
import { lazy, Suspense, useState } from 'react'
import { Link, Navigate, Route, Routes } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiSettingsDrawer } from '../components/ApiSettingsDrawer'
import { ConnectionGate } from '../components/ConnectionGate'
import { APP_LANGUAGES, changeLanguage, resolveLanguage, type AppLanguage } from '../i18n'
import { useApiConfig } from './apiContext'

const { Header, Content } = Layout
const RunListPage = lazy(() => import('../features/runs/RunListPage').then((module) => ({ default: module.RunListPage })))
const RunDetailPage = lazy(() => import('../features/run-detail/RunDetailPage').then((module) => ({ default: module.RunDetailPage })))

export function AppShell() {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { baseUrl, connected } = useApiConfig()
  const { t, i18n } = useTranslation()
  const selectedLanguage = resolveLanguage(i18n.resolvedLanguage)
  return (
    <Layout className="app-layout">
      <Header className="app-header">
        <Link to="/" className="app-brand">
          <DashboardOutlined />
          <Typography.Text strong>CS2 VibeSignatures</Typography.Text>
        </Link>
        <Space className="api-summary">
          <Badge status={connected ? 'success' : 'default'} />
          <Typography.Text type="secondary" ellipsis title={baseUrl}>
            <ApiOutlined /> {baseUrl}
          </Typography.Text>
          <Button icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)}>
            {t('app.apiSettings')}
          </Button>
          <Select
            aria-label={t('language.selector')}
            value={selectedLanguage}
            onChange={(language: AppLanguage) => void changeLanguage(language)}
            options={APP_LANGUAGES.map((language) => ({
              value: language,
              label: <><GlobalOutlined /> {t(`language.${language === 'en' ? 'english' : language === 'zh-CN' ? 'simplifiedChinese' : 'traditionalChinese'}`)}</>,
            }))}
            style={{ width: 158 }}
          />
        </Space>
      </Header>
      <Content className="app-content">
        {connected ? (
          <Suspense fallback={<div className="page-spinner">{t('app.loadingPage')}</div>}>
            <Routes>
              <Route path="/" element={<RunListPage />} />
              <Route path="/runs/:runId" element={<RunDetailPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        ) : (
          <ConnectionGate onSettings={() => setSettingsOpen(true)} />
        )}
      </Content>
      <ApiSettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </Layout>
  )
}
