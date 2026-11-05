import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  deleteStoredFile, forgetLocalFile, getStoredFile, manageLink, readLink, readLocalFiles, rememberLocalFile,
  storeFile, StoreError, tokenFromHash,
} from './userFiles'

const TOKEN = 'a'.repeat(43)

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('user files', () => {
  it('reads a token only from a well-formed fragment', () => {
    expect(tokenFromHash(`#${TOKEN}`)).toBe(TOKEN)
    expect(tokenFromHash('#short')).toBeNull()
    expect(tokenFromHash(`#${TOKEN}/x`)).toBeNull()
  })

  it('builds absolute read links on the API host and keeps the token in the fragment', () => {
    expect(readLink('/api/files/abc/gamedata.json', 'https://sig-api.miksen.me/api'))
      .toBe('https://sig-api.miksen.me/api/files/abc/gamedata.json')
    expect(manageLink(TOKEN, 'https://sig.miksen.me')).toBe(`https://sig.miksen.me/my-file#${TOKEN}`)
  })

  it('sends the manage token as a header, never in the URL', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ deleted: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await deleteStoredFile(TOKEN, 'https://api.test/api')
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('https://api.test/api/files/manage')
    expect(url).not.toContain(TOKEN)
    expect((init.headers as Record<string, string>)['X-Manage-Token']).toBe(TOKEN)
    expect(init.method).toBe('DELETE')
  })

  it('turns an error answer into a StoreError with the service message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'unknown manage token' }), { status: 404 })))
    await expect(getStoredFile(TOKEN, 'https://api.test/api')).rejects.toEqual(new StoreError(404, 'unknown manage token'))
  })

  it('stores with the build and webhook only when given', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 'x' }), { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)
    await storeFile('{}', 'g.json', undefined, undefined, 'https://api.test/api')
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(JSON.parse(init.body as string)).toEqual({ gamedata: '{}', filename: 'g.json' })
  })

  it('remembers, de-duplicates and forgets this browser’s files', () => {
    rememberLocalFile({ token: TOKEN, filename: 'a.json', created: 1 })
    rememberLocalFile({ token: TOKEN, filename: 'b.json', created: 2 })
    expect(readLocalFiles()).toEqual([{ token: TOKEN, filename: 'b.json', created: 2 }])
    forgetLocalFile(TOKEN)
    expect(readLocalFiles()).toEqual([])
  })
})
