import { afterEach, describe, expect, it, vi } from 'vitest'
import { DeepScanError, platformTone, requestDeepScan, rowTone, sortRows, type DeepRow } from './deepScan'

const row = (name: string, linux: string | undefined, windows?: string): DeepRow => ({
  name,
  platforms: {
    ...(linux === undefined ? {} : { linux: { status: 'x', verification: linux as never } }),
    ...(windows === undefined ? {} : { windows: { status: 'x', verification: windows as never } }),
  },
})

function reply(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn(async () => new Response(typeof body === 'string' ? body : JSON.stringify(body), { status, headers }))
}

describe('deep scan verdicts', () => {
  it('reads the pipeline\'s verification, not the raw status', () => {
    expect(platformTone({ status: 'ok', verification: 'verified' })).toBe('ok')
    // "ok" with a vtable that disagrees is contradicted, and that is what counts
    expect(platformTone({ status: 'ok', vtable: 'mismatch', verification: 'contradicted' })).toBe('bad')
    expect(platformTone({ status: 'ok', verification: 'unverified' })).toBe('warn')
    expect(platformTone({ status: 'no-binary' })).toBe('neutral')
  })

  it('puts the worst rows first', () => {
    const rows = [row('B', 'verified', 'verified'), row('A', 'verified', 'contradicted'), row('C', 'unverified')]
    expect(rowTone(rows[1]!)).toBe('bad')
    expect(sortRows(rows).map((r) => r.name)).toEqual(['A', 'C', 'B'])
  })
})

describe('asking the scan server', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('posts the text and the file name', async () => {
    const fetch = reply(200, { build: '14192', results: [] })
    vi.stubGlobal('fetch', fetch)
    await requestDeepScan('{"A":1}', 'matchzy.json', undefined, 'https://api.test/api')
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('https://api.test/api/verify')
    expect(JSON.parse(init.body as string)).toEqual({ gamedata: '{"A":1}', filename: 'matchzy.json' })
  })

  it.each([
    [429, {}, 'rateLimited'],
    [429, { 'Retry-After': '5' }, 'busy'],
    [413, {}, 'tooBig'],
    [400, {}, 'rejected'],
    [504, {}, 'busy'],
    [500, {}, 'failed'],
  ])('names a %i the way a visitor can act on', async (status, headers, reason) => {
    vi.stubGlobal('fetch', reply(status, { error: 'nope' }, headers))
    const error = await requestDeepScan('x', 'x.json').catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(DeepScanError)
    expect((error as DeepScanError).reason).toBe(reason)
  })

  it('keeps the server\'s reason for a rejected file', async () => {
    vi.stubGlobal('fetch', reply(400, { error: 'build 1 cannot be scanned here' }))
    const error = (await requestDeepScan('x', 'x.json').catch((caught: unknown) => caught)) as DeepScanError
    expect(error.detail).toBe('build 1 cannot be scanned here')
  })

  it('says offline when the request never lands', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const error = (await requestDeepScan('x', 'x.json').catch((caught: unknown) => caught)) as DeepScanError
    expect(error.reason).toBe('offline')
  })
})
