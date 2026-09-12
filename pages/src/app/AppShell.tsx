import { ApiOutlined, SettingOutlined } from '@ant-design/icons'
import { Badge, Select, Typography } from 'antd'
import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { Route, Routes, useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiSettingsDrawer } from '../components/ApiSettingsDrawer'
import { CommandPalette } from '../components/CommandPalette'
import { ConnectionGate } from '../components/ConnectionGate'
import { APP_LANGUAGES, changeLanguage, resolveLanguage, type AppLanguage } from '../i18n'
import { ThemeToggle } from '../theme/ThemeToggle'
import { useApiConfig } from './apiContext'
import { persistExplain, persistView, readExplain, readStoredView, type AppView } from './appViews'
import { onNavigation } from './navigate'

const RunListPage = lazy(() => import('../features/runs/RunListPage').then((module) => ({ default: module.RunListPage })))
const RunDetailPage = lazy(() => import('../features/run-detail/RunDetailPage').then((module) => ({ default: module.RunDetailPage })))
const FindSymbolPage = lazy(() => import('../features/symbols/FindSymbolPage').then((module) => ({ default: module.FindSymbolPage })))
const GameDataPage = lazy(() => import('../features/gamedata/GameDataPage').then((module) => ({ default: module.GameDataPage })))
const CheckFilePage = lazy(() => import('../features/checkfile/CheckFilePage').then((module) => ({ default: module.CheckFilePage })))
const RunReportPage = lazy(() => import('../features/runs2/RunReportPage').then((module) => ({ default: module.RunReportPage })))
const StartPage = lazy(() => import('../features/start/StartPage').then((module) => ({ default: module.StartPage })))
const WordsPage = lazy(() => import('../features/words/WordsPage').then((module) => ({ default: module.WordsPage })))

const LANGUAGE_LABELS: Record<AppLanguage, string> = {
  en: 'English',
  da: 'Dansk',
  'zh-CN': '简体中文',
  'zh-TW': '繁體中文',
}

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
  const [, setSearchParams] = useSearchParams()
  const [view, setView] = useState<AppView>(() => (location.pathname.startsWith('/runs') ? 'runs-live' : readStoredView()))
  const [explain, setExplain] = useState<boolean>(readExplain)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const selectedLanguage = resolveLanguage(i18n.resolvedLanguage)

  useEffect(() => {
    document.body.classList.toggle('noexplain', !explain)
  }, [explain])

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((current) => !current)
        return
      }
      const tag = (document.activeElement?.tagName ?? '').toUpperCase()
      if (event.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) {
        const box = document.querySelector<HTMLInputElement>('.bigsearch input, .findbox input')
        if (box) {
          event.preventDefault()
          box.focus()
        } else {
          event.preventDefault()
          setPaletteOpen(true)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => onNavigation(({ view: next, params }) => {
    if (params) {
      const search = new URLSearchParams()
      for (const [key, value] of Object.entries(params)) if (value) search.set(key, value)
      setSearchParams(search, { replace: true })
    }
    setView(next)
    persistView(next)
    window.scrollTo({ top: 0 })
  }), [setSearchParams])

  function go(next: AppView): void {
    setView(next)
    persistView(next)
    window.scrollTo({ top: 0 })
  }

  const tabs: AppView[] = ['start', 'symbols', 'gamedata', 'check', 'runs', 'words']
  const loading = <div className="page-spinner">{t('app.loadingPage')}</div>

  return (
    <div className="app-layout">
      <header className="rail">
        <div className="rail-inner">
          <a
            className="brand"
            href="https://github.com/mrc4tt/CS2_VibeSignatures"
            target="_blank"
            rel="noopener noreferrer"
          >
            <span className="mark">◆</span>
            <span className="brand-name">{t('brand')}</span>
          </a>
          <nav className="nav" aria-label={t('brand')}>
            {tabs.map((tab) => (
              <button
                key={tab}
                type="button"
                aria-current={view === tab ? 'page' : undefined}
                onClick={() => go(tab)}
              >
                {t(`nav2.${tab}`)}
              </button>
            ))}
          </nav>
          <div className="railtools">
            <button type="button" className="btn small" onClick={() => setPaletteOpen(true)}>
              ⌕ <span className="sw-label">{t('shell.search')}</span>
            </button>
            <label className="sw" data-on={explain}>
              <input
                id="explain-everything"
                type="checkbox"
                checked={explain}
                onChange={(event) => {
                  setExplain(event.target.checked)
                  persistExplain(event.target.checked)
                }}
              />
              <span className="sw-label">{t('shell.explain')}</span>
            </label>
            <Select
              aria-label={t('language.selector')}
              value={selectedLanguage}
              onChange={(language: AppLanguage) => void changeLanguage(language)}
              options={APP_LANGUAGES.map((language) => ({ value: language, label: LANGUAGE_LABELS[language] }))}
              popupMatchSelectWidth={false}
              size="small"
            />
            <ThemeToggle />
          </div>
        </div>
        {view === 'runs' && (
          <div className="apibar">
            <Badge status={connected ? 'success' : 'default'} />
            <Typography.Text type="secondary" ellipsis title={baseUrl}>
              <ApiOutlined /> {baseUrl}
            </Typography.Text>
            <button type="button" className="btn small" onClick={() => setSettingsOpen(true)}>
              <SettingOutlined /> {t('app.apiSettings')}
            </button>
          </div>
        )}
      </header>

      <main className="app-content">
        {view === 'start' && <Suspense fallback={loading}><StartPage onGo={go} /></Suspense>}
        {view === 'symbols' && <Suspense fallback={loading}><FindSymbolPage /></Suspense>}
        {view === 'gamedata' && <Suspense fallback={loading}><GameDataPage /></Suspense>}
        {view === 'check' && <Suspense fallback={loading}><CheckFilePage /></Suspense>}
        {view === 'words' && <Suspense fallback={loading}><WordsPage /></Suspense>}
        {view === 'runs' && <Suspense fallback={loading}><RunReportPage /></Suspense>}
        {view === 'runs-live' && (
          <Routes>
            <Route path="/runs" element={<ApiGate connected={connected} onSettings={() => setSettingsOpen(true)}><RunListPage /></ApiGate>} />
            <Route path="/runs/:runId" element={<ApiGate connected={connected} onSettings={() => setSettingsOpen(true)}><RunDetailPage /></ApiGate>} />
            <Route path="*" element={<ApiGate connected={connected} onSettings={() => setSettingsOpen(true)}><RunListPage /></ApiGate>} />
          </Routes>
        )}
      </main>
      <ApiSettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}
