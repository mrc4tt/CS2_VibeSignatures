import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntApp, ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { BrowserRouter } from 'react-router-dom'
import { ApiProvider } from './app/ApiProvider'
import { AppShell } from './app/AppShell'
import './App.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 1000, refetchOnWindowFocus: false },
  },
})

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: { colorPrimary: '#3b82f6', borderRadius: 8, colorBgBase: '#080d18' },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <ApiProvider>
            <BrowserRouter>
              <AppShell />
            </BrowserRouter>
          </ApiProvider>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  )
}
