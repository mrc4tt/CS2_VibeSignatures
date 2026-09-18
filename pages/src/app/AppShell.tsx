import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { Link, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiSettingsDrawer } from '../components/ApiSettingsDrawer'
import { CommandPalette } from '../components/CommandPalette'
import { ConnectionGate } from '../components/ConnectionGate'
import { APP_LANGUAGES, changeLanguage, resolveLanguage, type AppLanguage } from '../i18n'
import { ThemeToggle } from '../theme/ThemeToggle'
import { useApiConfig } from './apiContext'
import { forgetStoredView, persistExplain, readExplain, VIEW_PATHS, viewFromPath, type AppView } from './appViews'
import { onNavigation } from './navigate'
import { ApiIcon, BookIcon, ChartIcon, FileCheckIcon, OverviewIcon, SearchIcon, SettingsIcon, TableIcon, type IconProps } from '../ui/icons'
import { Dot, Select } from '../ui/primitives'

const RunListPage = lazy(() => import('../features/runs/RunListPage').then((module) => ({ default: module.RunListPage })))
const RunDetailPage = lazy(() => import('../features/run-detail/RunDetailPage').then((module) => ({ default: module.RunDetailPage })))
const FindSymbolPage = lazy(() => import('../features/symbols/FindSymbolPage').then((module) => ({ default: module.FindSymbolPage })))
const GameDataPage = lazy(() => import('../features/gamedata/GameDataPage').then((module) => ({ default: module.GameDataPage })))
const DiffPage = lazy(() => import('../features/diff/DiffPage').then((module) => ({ default: module.DiffPage })))
const CheckFilePage = lazy(() => import('../features/checkfile/CheckFilePage').then((module) => ({ default: module.CheckFilePage })))
const RunReportPage = lazy(() => import('../features/runs2/RunReportPage').then((module) => ({ default: module.RunReportPage })))
const StartPage = lazy(() => import('../features/start/StartPage').then((module) => ({ default: module.StartPage })))
const WordsPage = lazy(() => import('../features/words/WordsPage').then((module) => ({ default: module.WordsPage })))

const NAV_ICONS: Record<AppView, (props: IconProps) => React.ReactElement> = {
  start: OverviewIcon,
  symbols: SearchIcon,
  gamedata: TableIcon,
  diff: ChartIcon,
  check: FileCheckIcon,
  runs: ChartIcon,
  'runs-live': ChartIcon,
  words: BookIcon,
}

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
  const [explain, setExplain] = useState<boolean>(readExplain)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const selectedLanguage = resolveLanguage(i18n.resolvedLanguage)

  useEffect(() => {
    document.body.classList.toggle('noexplain', !explain)
  }, [explain])

  useEffect(forgetStoredView, [])

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

  const tabs: AppView[] = ['start', 'symbols', 'gamedata', 'diff', 'check', 'runs', 'words']
  const loading = <div className="page-spinner">{t('app.loadingPage')}</div>

  return (
    <div className="app-layout">
      {/*
        A rail rather than a top bar: the nav is a fixed six, the pages below are
        wide data surfaces, and vertical space is the scarce one on a page of
        tables. Below lg it lies down into the old horizontal bar, because 244px
        of chrome on a phone is most of the screen.
      */}
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
            {tabs.map((tab) => {
              const Icon = NAV_ICONS[tab]
              return (
                <Link
                  key={tab}
                  to={VIEW_PATHS[tab]}
                  aria-current={view === tab ? 'page' : undefined}
                  onClick={() => window.scrollTo({ top: 0 })}
                >
                  <Icon size={16} className="nav-icon" />
                  <span>{t(`nav2.${tab}`)}</span>
                </Link>
              )
            })}
          </nav>
          <div className="railtools">
            <button type="button" className="btn small" onClick={() => setPaletteOpen(true)}>
              <SearchIcon size={14} /> <span className="sw-label">{t('shell.search')}</span>
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
            <div className="railtools-row">
              <Select
                aria-label={t('language.selector')}
                value={selectedLanguage}
                onChange={(event) => void changeLanguage(event.target.value as AppLanguage)}
                className="min-w-0 flex-grow px-2 py-1 text-[12.5px]"
              >
                {APP_LANGUAGES.map((language) => (
                  <option key={language} value={language}>{LANGUAGE_LABELS[language]}</option>
                ))}
              </Select>
              <ThemeToggle />
            </div>
          </div>
        </div>
        {view === 'runs-live' && (
          <div className="apibar">
            <Dot tone={connected ? 'ok' : 'neutral'} />
            <span className="flex min-w-0 items-center gap-1.5 truncate text-[13px] text-muted" title={baseUrl}>
              <ApiIcon size={14} /> {baseUrl}
            </span>
            <button type="button" className="btn small" onClick={() => setSettingsOpen(true)}>
              <SettingsIcon size={14} /> {t('app.apiSettings')}
            </button>
          </div>
        )}
      </header>

      <main className="app-content">
        {view === 'start' && <Suspense fallback={loading}><StartPage onGo={go} /></Suspense>}
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
      <ApiSettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}
