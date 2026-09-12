import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../../i18n'
import type { SiteHistory } from '../../api/siteData'
import { CheckFilePage } from './CheckFilePage'

const MATCHZY = 'matchzy/gamedata/matchzy.json'

const history: SiteHistory = {
  schemaVersion: 1,
  gameVersion: '14181',
  builds: [
    { gameVersion: '14180', keyChanges: 0 },
    { gameVersion: '14181', keyChanges: 1 },
  ],
  files: {
    [MATCHZY]: {
      JoinTeam: { points: [['14180', 'OLD-L', 'OLD-W'], ['14181', 'NEW-L', 'OLD-W']], changes: ['14181'] },
      PostCleanUp: { points: [['14180', 'SAME-L', 'SAME-W']], changes: [] },
      SelectItem: { points: [['14180', 31, 30]], changes: [] },
      Untouched: { points: [['14180', 'U-L', 'U-W']], changes: [] },
    },
  },
  keyToSymbol: {},
  symbolToKeys: {},
}

vi.mock('../../api/siteData', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../api/siteData')>()
  return { ...original, getSiteHistory: vi.fn(async () => history) }
})

function paint() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CheckFilePage />
    </QueryClientProvider>,
  )
}

/** A matchzy file that is one build behind: JoinTeam's linux value is stale. */
const behindFile = JSON.stringify({
  JoinTeam: { signatures: { linux: 'OLD-L', windows: 'OLD-W' } },
  PostCleanUp: { signatures: { linux: 'SAME-L', windows: 'SAME-W' } },
  SelectItem: { offsets: { linux: 31, windows: 30 } },
  MyOwnKey: { signatures: { linux: 'AA', windows: 'BB' } },
})

async function drop(contents: string, name = 'matchzy.json') {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement
  await userEvent.upload(input, new File([contents], name, { type: 'application/json' }))
}

describe('Check my file', () => {
  // The shared setup renders in Chinese and never unmounts, so this suite pins
  // English (the only language these strings exist in) and cleans up itself.
  beforeEach(async () => {
    vi.clearAllMocks()
    await i18n.changeLanguage('en')
  })
  afterEach(() => cleanup())

  it('leads with what to do, against one build, and names the file it identified', async () => {
    paint()
    await screen.findByText('Check your own Game Data file')
    await drop(behindFile)

    // One baseline: the headline counts keys to fix for the NEWEST build. The
    // build the file matches is context in the same box, not a rival number -
    // showing "46 of 47 match 14168b" beside "35 need updating" was the
    // confusion this layout replaced.
    await waitFor(() => expect(screen.getByText('1 key(s) need updating for build 14181')).toBeInTheDocument())
    expect(screen.getByText('matchzy')).toBeInTheDocument()
    expect(screen.getByText(/matches build 14180, 1 build\(s\) back/)).toBeInTheDocument()
    // and no raw markdown leaking into the page
    expect(document.body.textContent).not.toContain('**')
  })

  it('counts every key exactly once across the four groups', async () => {
    paint()
    await screen.findByText('Check your own Game Data file')
    await drop(behindFile)

    await waitFor(() => expect(screen.getByText('Needs updating')).toBeInTheDocument())
    const count = (label: string) =>
      Number(screen.getByText(label).parentElement!.querySelector('.v')!.textContent)
    expect(count('Needs updating')).toBe(1)
    expect(count('Current')).toBe(2)
    expect(count('Not published')).toBe(1)
    expect(count('Missing from your file')).toBe(1)
  })

  it('keeps a signature folded away until the row is opened', async () => {
    paint()
    await screen.findByText('Check your own Game Data file')
    await drop(behindFile)

    const row = await waitFor(() => {
      const found = document.querySelector('details.krow[data-state="outdated"]') as HTMLDetailsElement
      expect(found).toBeTruthy()
      return found
    })
    expect(row.open).toBe(false)
    expect(row.querySelector('.kname')!.textContent).toBe('JoinTeam')

    // The badge says which platform is wrong before anything is expanded, so a
    // reader does not have to open a row to find out.
    expect(row.querySelector('.pbadge.bad')!.textContent).toBe('linux')
    expect(row.querySelector('.pbadge.ok')!.textContent).toBe('windows')

    await userEvent.click(row.querySelector('summary')!)
    expect(row.open).toBe(true)
    const linuxLine = [...row.querySelectorAll('.kline')].find((line) => line.textContent?.startsWith('linux'))!
    expect(linuxLine.querySelector('.was')!.textContent).toContain('OLD-L')
    expect(linuxLine.querySelector('.now')!.textContent).toContain('NEW-L')
  })

  it('says so plainly when a file cannot be placed', async () => {
    paint()
    await screen.findByText('Check your own Game Data file')
    await drop(JSON.stringify({ Nothing: { signatures: { linux: 'ZZ', windows: 'YY' } } }), 'mystery.txt')
    await waitFor(() =>
      expect(screen.getByText('Cannot tell which plugin this file belongs to')).toBeInTheDocument(),
    )
  })

  it('says a file carries no gamedata rather than offering to compare it', async () => {
    // The KeyValues reader never throws, so plain prose parses "successfully"
    // with nothing in it. Offering a plugin picker for that was misleading.
    paint()
    await screen.findByText('Check your own Game Data file')
    await drop('this is not gamedata', 'notes.txt')
    await waitFor(() => expect(screen.getByText(/No gamedata entries found/)).toBeInTheDocument())
    expect(screen.queryByText('Cannot tell which plugin this file belongs to')).not.toBeInTheDocument()
  })
})
