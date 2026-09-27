import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../../i18n'
import type { SiteDiagnostics, SiteHistory } from '../../api/siteData'
import { PluginChecksPanel } from './PluginChecksPanel'

const CSS = 'CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json'
const FOW = 'CS2FOW/gamedata/cs2fow.games.txt'

function diagnostics(build: string, files: NonNullable<SiteDiagnostics['plugins']>['files']): SiteDiagnostics {
  return { schemaVersion: 1, gameVersion: build, validator: { ran: false }, plugins: { ran: true, files }, run: [] }
}

const current = diagnostics('14185', [
  { plugin: 'CounterStrikeSharp', path: CSS, ran: true, entries: 52, statuses: { match: 34, ok: 68 }, unhealthy: 0, problems: [] },
  {
    plugin: 'CS2FOW', path: FOW, ran: true, entries: 17, statuses: { 'ambiguous-reference': 1, broken: 1 }, unhealthy: 1,
    problems: [
      { name: 'smoke_storage_offset', platform: 'linux', status: 'ambiguous-reference' },
      { name: 'SomeSig', platform: 'windows', status: 'broken' },
    ],
  },
])
const previous = diagnostics('14184', [
  { plugin: 'CounterStrikeSharp', path: CSS, ran: true, entries: 52, statuses: { ok: 102 }, unhealthy: 0, problems: [] },
  { plugin: 'CS2FOW', path: FOW, ran: true, entries: 17, statuses: { ok: 34 }, unhealthy: 0, problems: [] },
])

const history: SiteHistory = {
  schemaVersion: 1,
  gameVersion: '14185',
  builds: [{ gameVersion: '14184', keyChanges: 0 }, { gameVersion: '14185', keyChanges: 1 }],
  files: {},
  keyToSymbol: {},
  symbolToKeys: {},
}

vi.mock('../../api/siteData', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/siteData')>()
  return {
    ...original,
    getSiteHistory: vi.fn(async () => history),
    getSiteDiagnostics: vi.fn(async (build: string) => (build === '14184' ? previous : undefined)),
  }
})

function paint(value: SiteDiagnostics) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <PluginChecksPanel diagnostics={value} />
    </QueryClientProvider>,
  )
}

describe('PluginChecksPanel', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
  })
  afterEach(cleanup)

  it('shows each file with this build and the build before side by side', async () => {
    paint(current)
    expect(screen.getByText(CSS)).toBeTruthy()
    expect(screen.getByText('1 do not hold')).toBeTruthy()
    await waitFor(() => expect(screen.getByText('build 14184')).toBeTruthy())
    // 14185: CSS holds, FOW does not; 14184: both hold.
    await waitFor(() => expect(screen.getAllByText('holds')).toHaveLength(3))
  })

  it('lists the entries that are not a plain pass, defects apart from unchecked ones', () => {
    paint(current)
    expect(screen.getByText('SomeSig')).toBeTruthy()
    expect(screen.getByText('broken')).toBeTruthy()
    expect(screen.getByText('ambiguous-reference')).toBeTruthy()
  })

  it('renders nothing for diagnostics published before the check existed', () => {
    const { container } = paint({ schemaVersion: 1, gameVersion: '14181', validator: { ran: false }, run: [] })
    expect(container.textContent).toBe('')
  })
})
