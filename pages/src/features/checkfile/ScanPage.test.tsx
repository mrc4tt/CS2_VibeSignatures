import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../../i18n'
import type { SiteHistory } from '../../api/siteData'
import { getGameDataFile } from '../gamedata/data'
import { clearHandoff, handOff } from './handoff'
import { ScanPage } from './ScanPage'

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
      <ScanPage />
    </QueryClientProvider>,
  )
}

/** A matchzy file that is one build behind: JoinTeam's linux value is stale. */
const behindFile = JSON.stringify({
  JoinTeam: { signatures: { linux: 'OLD-L', windows: 'OLD-W' } },
  PostCleanUp: { signatures: { linux: 'SAME-L', windows: 'SAME-W' } },
  SelectItem: { offsets: { linux: 31, windows: 30 } },
  MyOwnKey: { signatures: { linux: 'AA', windows: 'BB' } },
}, null, 2)

async function drop(contents: string, name = 'matchzy.json') {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement
  await userEvent.upload(input, new File([contents], name, { type: 'application/json' }))
}

describe('Scanner', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    await i18n.changeLanguage('en')
  })
  afterEach(() => {
    clearHandoff()
    cleanup()
  })

  it('opens on a published example in the editor, and lets it be edited and checked', async () => {
    vi.mocked(getGameDataFile).mockResolvedValueOnce(behindFile)
    paint()
    await screen.findByText('Example: matchzy 14181')
    // the editor view, filled, with the browser check's marks on it
    await waitFor(() => expect(document.querySelector('.annotated .rl.m-bad .st')?.getAttribute('title')).toBe('linux: should be NEW-L'))
    // the details read off the file itself
    await waitFor(() => expect([...document.querySelectorAll('.details dd')].map((n) => n.textContent)).toEqual(['matchzy (mrc4tt fork)', '14192', 'JSON', '3', '1', '-', '0 / 24 busy']))

    // typed straight into, no edit mode: the marks step aside until the pause re-checks it
    fireEvent.change(screen.getByLabelText('The file, editable'), {
      target: { value: JSON.stringify({ JoinTeam: { signatures: { linux: 'NEW-L', windows: 'OLD-W' } } }, null, 2) },
    })
    expect(document.querySelector('.annotated .rl.m-bad')).toBeNull()
    expect(screen.getByText('Edited: checked again when you pause')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText(/^Example:/)).toBeNull(), { timeout: 2000 })
    expect(screen.queryByText('Edited: checked again when you pause')).toBeNull()
    expect(document.querySelector('.annotated .rl.m-bad')).toBeNull()
  })

  it('points at the line of a JSON slip, in the editor while typing and above the page on a drop', async () => {
    vi.mocked(getGameDataFile).mockResolvedValueOnce(behindFile)
    paint()
    await screen.findByText('Example: matchzy 14181')
    fireEvent.change(screen.getByLabelText('The file, editable'), {
      target: { value: '{\n  "A": { "linux": "55", "windows": "40" }\n  "B": { "linux": "1", "windows": "2" }\n}' },
    })
    const said = 'Invalid JSON at line 3, column 3: a comma is missing before this.'
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(said), { timeout: 2000 })
    expect(document.querySelector('.annotated .rl.m-bad')?.getAttribute('data-line')).toBe('3')
    expect(screen.queryByRole('alert')).toBeNull()

    await drop('{ "A": { "linux": "55" }', 'broken.json')
    expect(await screen.findByText('Invalid JSON at line 1, column 25: the file ends too early, a closing } or ] is missing.')).toBeInTheDocument()
  })

  it('offers the replacement for the marked line the cursor is on, and puts in only that value', async () => {
    vi.mocked(getGameDataFile).mockResolvedValueOnce(behindFile)
    paint()
    await screen.findByText('Example: matchzy 14181')
    await waitFor(() => expect(document.querySelector('.annotated .rl.m-bad')).not.toBeNull())
    expect(screen.getByText('Put the cursor on a marked line for suggestions')).toBeInTheDocument()

    const editor = screen.getByLabelText('The file, editable') as HTMLTextAreaElement
    // a line that holds offers nothing
    editor.setSelectionRange(behindFile.indexOf('SAME-L'), behindFile.indexOf('SAME-L'))
    fireEvent.select(editor)
    expect(document.querySelector('.linepop')).toBeNull()

    editor.setSelectionRange(behindFile.indexOf('OLD-L'), behindFile.indexOf('OLD-L'))
    fireEvent.select(editor)
    const card = await screen.findByRole('group', { name: 'Verdicts on line 4' })
    expect(card).toHaveTextContent('JoinTeam')
    await userEvent.click(screen.getByRole('button', { name: 'Use NEW-L' }))

    await waitFor(() => expect(editor.value).toContain('"linux": "NEW-L"'))
    // windows was right and stays exactly as it was
    expect(editor.value).toContain('"windows": "OLD-W"')
    expect(document.querySelector('.annotated .rl.m-bad')).toBeNull()
  })

  it('closes the card on Escape', async () => {
    vi.mocked(getGameDataFile).mockResolvedValueOnce(behindFile)
    paint()
    await waitFor(() => expect(document.querySelector('.annotated .rl.m-bad')).not.toBeNull())
    const editor = screen.getByLabelText('The file, editable') as HTMLTextAreaElement
    editor.setSelectionRange(behindFile.indexOf('OLD-L'), behindFile.indexOf('OLD-L'))
    fireEvent.select(editor)
    expect(await screen.findByRole('group', { name: 'Verdicts on line 4' })).toBeInTheDocument()
    fireEvent.keyDown(editor, { key: 'Escape' })
    expect(document.querySelector('.linepop')).toBeNull()
  })

  it('opens on the file handed over from Check my file, not the example', async () => {
    handOff(behindFile, 'mine.json')
    paint()
    await waitFor(() => expect(document.querySelector('.scanbar')?.textContent).toContain('mine.json'))
    expect(screen.queryByText(/^Example:/)).toBeNull()
    expect(getGameDataFile).not.toHaveBeenCalled()
  })

  it('never puts the example over a file someone dropped', async () => {
    let release: (text: string) => void = () => undefined
    vi.mocked(getGameDataFile).mockImplementationOnce(() => new Promise((resolve) => { release = resolve }))
    paint()
    await drop(behindFile, 'mine.json')
    release(behindFile)
    await waitFor(() => expect(document.querySelector('.scanbar')?.textContent).toContain('mine.json'))
    expect(screen.queryByText(/^Example:/)).toBeNull()
  })

  it('opens the editor empty for a paste', async () => {
    handOff(behindFile, 'mine.json')
    paint()
    await waitFor(() => expect(document.querySelector('.scanbar')?.textContent).toContain('mine.json'))
    await userEvent.click(screen.getByRole('button', { name: 'Paste' }))
    expect(screen.getByLabelText('The file, editable')).toHaveValue('')
  })

  it('runs the deep scan only when asked, and keeps the result in a bar until asked for', async () => {
    const verifyReply = JSON.stringify({
      build: '14192',
      platforms: ['linux', 'windows'],
      matched: { plugin: 'matchzy', file: 'gamedata/14192/matchzy/gamedata/matchzy.json' },
      unhealthy: 1,
      verification: { verified: 3, contradicted: 1, unverified: 0, upstream: 0 },
      results: [
        { name: 'SelectItem', kind: 'offset', platforms: {
          linux: { status: 'mismatch', reference: 32, verification: 'contradicted' },
          windows: { status: 'match', value: 30, verification: 'verified' } } },
        { name: 'PostCleanUp', kind: 'signature', platforms: {
          linux: { status: 'ok', verification: 'verified' }, windows: { status: 'ok', verification: 'verified' } } },
      ],
      fixes: [{ key: 'SelectItem', platform: 'linux', from: 31, to: 32, source: 'shipped' }],
    })
    const fetch = vi.fn(async (url: string) => new Response(
      url.endsWith('/builds') ? JSON.stringify({ builds: ['14192', '14191'] }) : verifyReply,
      { status: 200 },
    ))
    const scans = () => fetch.mock.calls.filter(([url]) => String(url).endsWith('/verify')).length
    vi.stubGlobal('fetch', fetch)
    try {
      handOff(behindFile, 'matchzy.json')
      paint()
      await screen.findByRole('button', { name: 'Scan it' })
      // opening a file sends nothing anywhere
      expect(scans()).toBe(0)

      await userEvent.click(screen.getByRole('button', { name: 'Scan it' }))
      // the file view shows the scan's marks, on the very line that is wrong
      await waitFor(() => expect(document.querySelector('.annotated .rl.m-bad .st')?.getAttribute('title')).toBe('linux: should be 32'))
      expect(scans()).toBe(1)
      const bad = document.querySelector<HTMLElement>('.annotated .rl.m-bad')!
      expect(bad.textContent).toContain('"linux"')
      expect(screen.getByText('Marks from the deep scan')).toBeInTheDocument()
      // the bar says what the scan said
      expect(document.querySelector('.scanverdict')?.textContent).toBe('1 value is wrong for build 14192')

      // nothing opens by itself: the bar says the verdict and waits
      const sheet = screen.getByRole('region', { name: 'Scan result' })
      expect(sheet).toHaveAttribute('data-size', 'min')
      expect(sheet.textContent).toContain('Not ready for 14192.')
      expect(sheet.textContent).toContain('1 error. It can be fixed automatically.')
      expect(screen.getByRole('button', { name: 'Download fixed file' })).toBeInTheDocument()

      await userEvent.click(screen.getByRole('button', { name: 'Show result' }))
      expect(sheet).toHaveAttribute('data-size', 'half')
      // worst first, with the reason in plain words and the value that fixes it
      expect([...sheet.querySelectorAll('.rsheet-item .nm')].map((n) => n.textContent)).toEqual(['SelectItem', 'PostCleanUp'])
      expect(sheet.querySelector('.rsheet-why')?.textContent).toContain('The value no longer matches this build.')
      expect(sheet.querySelector('.rsheet-fix code')?.textContent).toBe('32')

      // a row marks its line in the file
      await userEvent.click(screen.getByRole('button', { name: /^SelectItem: show line/ }))
      expect(document.querySelector('.annotated .rl.foc')?.textContent).toContain('"linux"')

      // the filter narrows, the raw log speaks the scanner's own words
      await userEvent.click(screen.getByRole('radio', { name: /^OK/ }))
      expect([...sheet.querySelectorAll('.rsheet-item .nm')].map((n) => n.textContent)).toEqual(['PostCleanUp'])
      await userEvent.click(screen.getByRole('radio', { name: 'Raw log' }))
      expect(sheet.querySelector('.rsheet-log')?.textContent).toContain('[SelectItem]')

      fireEvent.keyDown(sheet, { key: 'Escape' })
      expect(sheet).toHaveAttribute('data-size', 'min')
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('says which build a stale value is from, and places the fixes and scans again on one click', async () => {
    const reply = (fixed: boolean) => JSON.stringify({
      build: '14192',
      platforms: ['linux', 'windows'],
      matched: { plugin: 'matchzy', file: 'gamedata/14192/matchzy/gamedata/matchzy.json' },
      unhealthy: fixed ? 0 : 1,
      results: [
        { name: 'JoinTeam', kind: 'signature', platforms: {
          linux: fixed ? { status: 'ok', verification: 'verified' } : { status: 'mismatch', verification: 'contradicted' },
          windows: { status: 'ok', verification: 'verified' } } },
      ],
      fixes: fixed ? [] : [{ key: 'JoinTeam', platform: 'linux', from: 'OLD-L', to: 'NEW-L', source: 'shipped' }],
    })
    const sent: string[] = []
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/builds')) return new Response(JSON.stringify({ builds: ['14192'] }), { status: 200 })
      const text = JSON.parse(String(init?.body)).gamedata as string
      sent.push(text)
      return new Response(reply(text.includes('NEW-L')), { status: 200 })
    })
    vi.stubGlobal('fetch', fetch)
    try {
      handOff(behindFile, 'matchzy.json')
      paint()
      await userEvent.click(await screen.findByRole('button', { name: 'Scan it' }))
      await userEvent.click(await screen.findByRole('button', { name: 'Show result' }))
      const sheet = screen.getByRole('region', { name: 'Scan result' })
      expect(sheet.querySelector('.rsheet-aged')?.textContent).toBe('Your value is the one from build 14180; it changed in 14181.')

      await userEvent.click(screen.getByRole('button', { name: 'Use fixed file' }))
      await waitFor(() => expect(sent).toHaveLength(2))
      expect(sent[1]).toContain('"NEW-L"')
      await waitFor(() => expect(screen.getByRole('region', { name: 'Scan result' }).textContent).toContain('Ready for 14192.'))
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('scans for the platform picked in the filled segments', async () => {
    const fetch = vi.fn(async (url: string) => new Response(
      url.endsWith('/verify') ? JSON.stringify({ build: '14192', results: [] }) : JSON.stringify({ builds: ['14192'] }),
      { status: 200 },
    ))
    vi.stubGlobal('fetch', fetch)
    try {
      handOff(behindFile, 'matchzy.json')
      paint()
      await userEvent.click(await screen.findByRole('radio', { name: 'Linux' }))
      expect(screen.getByRole('radio', { name: 'Linux' })).toHaveAttribute('aria-checked', 'true')
      await userEvent.click(screen.getByRole('button', { name: 'Scan it' }))
      await waitFor(() => expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/verify'))).toBe(true))
      const [, init] = fetch.mock.calls.find(([url]) => String(url).endsWith('/verify')) as unknown as [string, RequestInit]
      expect(JSON.parse(init.body as string)).toMatchObject({ platform: 'linux' })
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
