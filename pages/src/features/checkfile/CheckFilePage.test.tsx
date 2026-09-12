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

const PUBLISHED = { id: MATCHZY, plugin: 'matchzy', fileName: 'matchzy.json', language: 'json', content: { url: 'payloads/x.json', sha256: 'a'.repeat(64), size: 9 } }

vi.mock('../gamedata/data', () => ({
  getGameDataIndex: vi.fn(async () => ({
    schemaVersion: 1,
    versions: [{ gameVersion: '14181', fileCount: 1, metadataFileCount: 0, files: [PUBLISHED] }],
  })),
  getGameDataFile: vi.fn(async () => '{"published":"file"}'),
}))

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

  it('offers uploading and pasting as equal choices, and the paste path works', async () => {
    paint()
    await screen.findByText('Check your own Game Data file')

    // Both ways in are real buttons of the same weight. Pasting used to be a
    // collapsed line of grey text under the drop zone.
    const upload = screen.getByRole('tab', { name: 'Upload a file' })
    const paste = screen.getByRole('tab', { name: 'Paste the text' })
    expect(upload).toHaveAttribute('aria-selected', 'true')
    expect(paste).toHaveAttribute('aria-selected', 'false')

    await userEvent.click(paste)
    expect(paste).toHaveAttribute('aria-selected', 'true')
    expect(document.querySelector('input[type="file"]')).toBeNull()

    const box = screen.getByLabelText('Paste the contents of the file')
    const check = screen.getByRole('button', { name: 'Check it' })
    // Nothing is checked until asked: typing no longer fires a parse mid-edit.
    expect(check).toBeDisabled()
    await userEvent.click(box)
    await userEvent.paste(behindFile)
    await waitFor(() => expect(screen.getByText('1 key(s) need updating for build 14181')).toBeInTheDocument())
  })

  it('offers a fixed file before any hex, and the fix actually holds', async () => {
    paint()
    await screen.findByText('Check your own Game Data file')
    await drop(behindFile)

    await waitFor(() => expect(screen.getByText('Get the file fixed for you')).toBeInTheDocument())
    expect(screen.getByText(/1 value\(s\) replaced/)).toBeInTheDocument()
    // Three plain steps, so it is clear what to do with the download.
    expect(screen.getByText('Download the fixed file')).toBeInTheDocument()
    expect(screen.getByText('Put it where your old one was, on the server.')).toBeInTheDocument()

    // The copy button hands over the patched text, not the original.
    const written: string[] = []
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: (text: string) => { written.push(text); return Promise.resolve() } },
    })
    await userEvent.click(screen.getByRole('button', { name: 'Copy it instead' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument())
    expect(written).toHaveLength(1)
    expect(written[0]).toContain('NEW-L')
    expect(written[0]).not.toContain('OLD-L')
    // and the untouched windows value survives
    expect(written[0]).toContain('OLD-W')
  })

  it('offers the published file as it is, and labels each key signature or offset', async () => {
    paint()
    await screen.findByText('Check your own Game Data file')
    await drop(behindFile)

    // (1) take ours wholesale - for a badly out-of-date file that beats patching
    const takeOurs = await waitFor(() => screen.getByRole('button', { name: 'download matchzy.json' }))
    const clicks: string[] = []
    const created = vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
      clicks.push(String((blob as Blob).size))
      return 'blob:x'
    })
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    await userEvent.click(takeOurs)
    await waitFor(() => expect(clicks).toHaveLength(1))
    created.mockRestore()

    // (2) a reader should not have to know that a number means a vtable slot.
    // SelectItem and PostCleanUp are both current, so switch group first.
    await userEvent.click(screen.getByText('Current'))
    await waitFor(() => {
      const current = [...document.querySelectorAll('details.krow')]
      const numeric = current.find((row) => row.querySelector('.kname')?.textContent === 'SelectItem')
      expect(numeric?.querySelector('.kindbadge')?.textContent).toBe('offset')
      const hex = current.find((row) => row.querySelector('.kname')?.textContent === 'PostCleanUp')
      expect(hex?.querySelector('.kindbadge')?.textContent).toBe('signature')
    })
  })

  it('warns when a value matches no published build at all', async () => {
    paint()
    await screen.findByText('Check your own Game Data file')
    // JoinTeam carries a value this site has never published: not 14181's and
    // not 14180's either.
    await drop(JSON.stringify({
      JoinTeam: { signatures: { linux: 'HAND-EDITED', windows: 'OLD-W' } },
      PostCleanUp: { signatures: { linux: 'SAME-L', windows: 'SAME-W' } },
      SelectItem: { offsets: { linux: 31, windows: 30 } },
    }))
    await waitFor(() =>
      expect(screen.getByText('Some values in your file have never been published here')).toBeInTheDocument(),
    )
    expect(screen.getByText(/were edited by hand/)).toBeInTheDocument()
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
