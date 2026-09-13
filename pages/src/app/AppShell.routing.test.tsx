import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import i18n from '../i18n'
import { AppShell } from './AppShell'
import { ApiProvider } from './ApiProvider'
import { ThemeProvider } from '../theme/ThemeProvider'
import { requestNavigation } from './navigate'

function paint() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
      <ApiProvider>
        <BrowserRouter>
          <AppShell />
        </BrowserRouter>
      </ApiProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

describe('the browser Back button', () => {
  beforeEach(async () => {
    window.history.pushState({}, '', '/')
    await i18n.changeLanguage('en')
  })
  afterEach(() => cleanup())

  it('gives each page its own URL, so Back goes back a page instead of leaving', async () => {
    paint()
    // The navigation is anchors, not buttons: a destination should survive
    // middle-click, ctrl-click and "copy link address".
    expect(screen.getByRole('link', { name: 'Game Data' })).toHaveAttribute('href', '/gamedata')
    // Views used to be shell state on a single route: nothing was pushed, so the
    // first Back took you off the site altogether.
    await userEvent.click(screen.getByRole('link', { name: 'Game Data' }))
    await waitFor(() => expect(window.location.pathname).toBe('/gamedata'))

    await userEvent.click(screen.getByRole('link', { name: 'Check my file' }))
    await waitFor(() => expect(window.location.pathname).toBe('/check'))

    window.history.back()
    await waitFor(() => expect(window.location.pathname).toBe('/gamedata'))
    window.history.back()
    await waitFor(() => expect(window.location.pathname).toBe('/'))
  })

  it('carries the parameters of a cross-page link into the URL', async () => {
    paint()
    // A symbol linking to the Game Data key that ships it: the target has to be
    // shareable, not just rendered.
    requestNavigation({ view: 'gamedata', params: { file: 'matchzy/gamedata/matchzy.json', key: 'JoinTeam' } })
    await waitFor(() => expect(window.location.pathname).toBe('/gamedata'))
    expect(new URLSearchParams(window.location.search).get('key')).toBe('JoinTeam')
  })

  it('opens a pasted deep link on that page', async () => {
    window.history.pushState({}, '', '/words')
    paint()
    await waitFor(() => expect(screen.getByRole('link', { name: 'Words' })).toHaveAttribute('aria-current', 'page'))
  })

  it('shows Start for a path it does not know, rather than nothing at all', async () => {
    window.history.pushState({}, '', '/no-such-page')
    paint()
    await waitFor(() => expect(screen.getByRole('link', { name: 'Start here' })).toHaveAttribute('aria-current', 'page'))
  })
})
