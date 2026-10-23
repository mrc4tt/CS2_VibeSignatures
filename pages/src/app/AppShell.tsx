import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { Link, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiSettingsDrawer } from '../components/ApiSettingsDrawer'
import { CommandPalette } from '../components/CommandPalette'
import { ShortcutHelp } from '../components/ShortcutHelp'
import { ConnectionGate } from '../components/ConnectionGate'
import { APP_LANGUAGES, changeLanguage, resolveLanguage, type AppLanguage } from '../i18n'
import { ThemeToggle } from '../theme/ThemeToggle'
import { useApiConfig } from './apiContext'
import { forgetStoredView, pluginFromPath, VIEW_PATHS, viewFromPath, type AppView } from './appViews'
import { onNavigation } from './navigate'
import { ApiIcon, SearchIcon, SettingsIcon } from '../ui/icons'
import { Button, Dot, Key, Select, Toaster } from '../ui/primitives'
import { BuildStatusBanner } from '../components/BuildStatusBanner'

const RunListPage = lazy(() => import('../features/runs/RunListPage').then((module) => ({ default: module.RunListPage })))
const RunDetailPage = lazy(() => import('../features/run-detail/RunDetailPage').then((module) => ({ default: module.RunDetailPage })))
const FindSymbolPage = lazy(() => import('../features/symbols/FindSymbolPage').then((module) => ({ default: module.FindSymbolPage })))
const GameDataPage = lazy(() => import('../features/gamedata/GameDataPage').then((module) => ({ default: module.GameDataPage })))
const DiffPage = lazy(() => import('../features/diff/DiffPage').then((module) => ({ default: module.DiffPage })))
const CheckFilePage = lazy(() => import('../features/checkfile/CheckFilePage').then((module) => ({ default: module.CheckFilePage })))
const RunReportPage = lazy(() => import('../features/runs2/RunReportPage').then((module) => ({ default: module.RunReportPage })))
const StartPage = lazy(() => import('../features/start/StartPage').then((module) => ({ default: module.StartPage })))
const PluginPage = lazy(() => import('../features/plugins/PluginPage').then((module) => ({ default: module.PluginPage })))
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
  const navigate = useNavigate()
  // The URL is the single source of truth for which view is showing, which is
  // what makes Back and Forward work and a link to a page shareable.
  const view = viewFromPath(location.pathname)
  const plugin = pluginFromPath(location.pathname)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const selectedLanguage = resolveLanguage(i18n.resolvedLanguage)

  useEffect(forgetStoredView, [])

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((current) => !current)
        return
      }
      const active = document.activeElement
      const tag = (active?.tagName ?? '').toUpperCase()
      const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) || (active instanceof HTMLElement && active.isContentEditable)
      if (event.key === '?' && !typing) {
        event.preventDefault()
        setHelpOpen(true)
        return
      }
      if (event.key === '/' && !typing) {
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
    const search = new URLSearchParams()
    if (params) for (const [key, value] of Object.entries(params)) if (value) search.set(key, value)
    const query = search.toString()
    navigate(`${VIEW_PATHS[next]}${query ? `?${query}` : ''}`)
    window.scrollTo({ top: 0 })
  }), [navigate])

  function go(next: AppView): void {
    navigate(VIEW_PATHS[next])
    window.scrollTo({ top: 0 })
  }

  // Three destinations a server owner comes for. Everything else is a footer
  // link: still one click away, no longer competing for the top bar.
  const tabs: AppView[] = ['start', 'symbols', 'check']
  const footer: AppView[] = ['gamedata', 'diff', 'runs', 'words']
  const section: AppView = plugin || view === 'gamedata' ? 'start' : view
  const loading = <div className="page-spinner">{t('app.loadingPage')}</div>

  return (
    <div className="app-layout">
      <header className="topbar">
        <div className="topbar-inner">
          <Link className="brand" to={VIEW_PATHS.start} onClick={() => window.scrollTo({ top: 0 })}>
            <span className="mark">◆</span>
            <span className="brand-name">{t('brand')}</span>
          </Link>
          <nav className="nav" aria-label={t('shell2.main')}>
            {tabs.map((tab) => (
              <Link
                key={tab}
                to={VIEW_PATHS[tab]}
                aria-current={section === tab ? 'page' : undefined}
                onClick={() => window.scrollTo({ top: 0 })}
              >
                {t(`shell2.nav.${tab}`)}
              </Link>
            ))}
          </nav>
          <div className="topbar-tools">
            <Button className="searchbtn" onClick={() => setPaletteOpen(true)} aria-label={t('shell.search')}>
              <SearchIcon size={15} /> <span className="sw-label">{t('shell.search')}</span>
              <span className="sw-label"><Key>Ctrl K</Key></span>
            </Button>
            <ThemeToggle />
          </div>
        </div>
        {view === 'runs-live' && (
          <div className="apibar">
            <Dot tone={connected ? 'ok' : 'neutral'} />
            <span className="flex min-w-0 items-center gap-1.5 truncate text-[13px] text-muted-foreground" title={baseUrl}>
              <ApiIcon size={14} /> {baseUrl}
            </span>
            <Button size="small" onClick={() => setSettingsOpen(true)}>
              <SettingsIcon size={14} /> {t('app.apiSettings')}
            </Button>
          </div>
        )}
      </header>

      <main className="app-content">
        <BuildStatusBanner />
        {plugin && <Suspense fallback={loading}><PluginPage plugin={plugin} /></Suspense>}
        {!plugin && view === 'start' && <Suspense fallback={loading}><StartPage onGo={go} /></Suspense>}
        {view === 'symbols' && <Suspense fallback={loading}><FindSymbolPage /></Suspense>}
        {view === 'gamedata' && <Suspense fallback={loading}><GameDataPage /></Suspense>}
        {view === 'diff' && <Suspense fallback={loading}><DiffPage /></Suspense>}
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
      <footer className="sitefoot">
        <div className="sitefoot-inner">
          <nav className="footnav" aria-label={t('shell2.more')}>
            {footer.map((item) => (
              <Link
                key={item}
                to={VIEW_PATHS[item]}
                aria-current={view === item && !plugin ? 'page' : undefined}
                onClick={() => window.scrollTo({ top: 0 })}
              >
                {t(`shell2.nav.${item}`)}
              </Link>
            ))}
            <a href="https://github.com/mrc4tt/CS2_VibeSignatures" target="_blank" rel="noopener noreferrer">GitHub</a>
          </nav>
          <Select
            aria-label={t('language.selector')}
            value={selectedLanguage}
            onChange={(event) => void changeLanguage(event.target.value as AppLanguage)}
            wrapperClassName="w-auto"
            className="px-2 py-1 text-[13px]"
          >
            {APP_LANGUAGES.map((language) => (
              <option key={language} value={language}>{LANGUAGE_LABELS[language]}</option>
            ))}
          </Select>
        </div>
      </footer>
      <ApiSettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onHelp={() => { setPaletteOpen(false); setHelpOpen(true) }}
      />
      <ShortcutHelp open={helpOpen} onClose={() => setHelpOpen(false)} />
      <Toaster />
    </div>
  )
}
