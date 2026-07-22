import { ApiOutlined, DashboardOutlined, GlobalOutlined, SettingOutlined } from '@ant-design/icons'
import { Badge, Button, Layout, Select, Space, Tabs, Typography } from 'antd'
import { lazy, Suspense, useState, type ReactNode } from 'react'
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiSettingsDrawer } from '../components/ApiSettingsDrawer'
import { ConnectionGate } from '../components/ConnectionGate'
import { APP_LANGUAGES, changeLanguage, resolveLanguage, type AppLanguage } from '../i18n'
import { useApiConfig } from './apiContext'

const { Header, Content } = Layout
const RunListPage = lazy(() => import('../features/runs/RunListPage').then((module) => ({ default: module.RunListPage })))
const RunDetailPage = lazy(() => import('../features/run-detail/RunDetailPage').then((module) => ({ default: module.RunDetailPage })))
const ExploreSymbolsPage = lazy(() => import('../features/symbols/ExploreSymbolsPage').then((module) => ({ default: module.ExploreSymbolsPage })))

function ApiGate({ connected, onSettings, children }: { connected: boolean; onSettings(): void; children: ReactNode }) {
  const { t } = useTranslation()
  if (!connected) return <ConnectionGate onSettings={onSettings} />
  return <Suspense fallback={<div className="page-spinner">{t('app.loadingPage')}</div>}>{children}</Suspense>
}

export function AppShell() {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { baseUrl, connected } = useApiConfig()
  const { t, i18n } = useTranslation()
  const location = useLocation()
  const navigate = useNavigate()
  const selectedLanguage = resolveLanguage(i18n.resolvedLanguage)
  const activeTab = location.pathname.startsWith('/symbols') ? 'symbols' : 'runs'
  return (
    <Layout className="app-layout">
      <Header className="app-header">
        <Link to="/" className="app-brand">
          <DashboardOutlined />
          <Typography.Text strong>CS2 VibeSignatures</Typography.Text>
        </Link>
        <Tabs
          className="app-nav"
          activeKey={activeTab}
          onChange={(key) => void navigate(key === 'symbols' ? '/symbols' : '/')}
          items={[
            { key: 'runs', label: t('navigation.runs') },
            { key: 'symbols', label: t('navigation.symbols') },
          ]}
        />
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
        <Routes>
          <Route path="/symbols" element={<Suspense fallback={<div className="page-spinner">{t('app.loadingPage')}</div>}><ExploreSymbolsPage /></Suspense>} />
          <Route path="/" element={<ApiGate connected={connected} onSettings={() => setSettingsOpen(true)}><RunListPage /></ApiGate>} />
          <Route path="/runs/:runId" element={<ApiGate connected={connected} onSettings={() => setSettingsOpen(true)}><RunDetailPage /></ApiGate>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Content>
      <ApiSettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </Layout>
  )
}
