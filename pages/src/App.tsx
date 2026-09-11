import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntApp, ConfigProvider, theme } from 'antd'
import daDK from 'antd/locale/da_DK'
import enUS from 'antd/locale/en_US'
import zhCN from 'antd/locale/zh_CN'
import zhTW from 'antd/locale/zh_TW'
import { BrowserRouter } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiProvider } from './app/ApiProvider'
import { AppShell } from './app/AppShell'
import { resolveLanguage } from './i18n'
import { useTheme } from './theme/themeContext'
import './App.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 1000, refetchOnWindowFocus: false },
  },
})

const ANT_DESIGN_LOCALES = { en: enUS, da: daDK, 'zh-CN': zhCN, 'zh-TW': zhTW }

export default function App() {
  const { i18n } = useTranslation()
  const { theme: colorTheme } = useTheme()
  const isDark = colorTheme === 'dark'
  return (
    <ConfigProvider
      locale={ANT_DESIGN_LOCALES[resolveLanguage(i18n.resolvedLanguage)]}
      theme={{
        algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          colorPrimary: isDark ? '#63c3cd' : '#17636e',
          borderRadius: 6,
          fontFamily: '"Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif',
          fontFamilyCode: '"JetBrains Mono", "Cascadia Code", Consolas, ui-monospace, monospace',
          colorBgBase: isDark ? '#0e1115' : '#e9ebef',
          ...(isDark
            ? {
                colorBgLayout: '#0e1115',
                colorBgContainer: '#171b21',
                colorBgElevated: '#1d222a',
              }
            : {
                colorBgLayout: '#e9ebef',
                colorBgContainer: '#ffffff',
                colorBgElevated: '#ffffff',
                colorFillAlter: 'rgba(95, 104, 119, 0.06)',
              }),
        },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <ApiProvider>
            <BrowserRouter basename={import.meta.env.BASE_URL}>
              <AppShell />
            </BrowserRouter>
          </ApiProvider>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  )
}
