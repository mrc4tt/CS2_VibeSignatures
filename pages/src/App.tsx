import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { ApiProvider } from './app/ApiProvider'
import { AppShell } from './app/AppShell'
import './App.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 1000, refetchOnWindowFocus: false },
  },
})

/**
 * No ConfigProvider any more: theming is CSS variables on <html data-theme>,
 * which the pre-paint script in index.html sets before React mounts, so there
 * is no flash and no provider to keep in sync with the toggle. The antd locale
 * bundles went with it - nothing left renders dates or pagination text from a
 * component library, so i18next is the only translation layer.
 */
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ApiProvider>
        <BrowserRouter basename={import.meta.env.BASE_URL}>
          <AppShell />
        </BrowserRouter>
      </ApiProvider>
    </QueryClientProvider>
  )
}
