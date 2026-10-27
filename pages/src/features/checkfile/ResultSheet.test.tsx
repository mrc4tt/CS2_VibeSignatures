import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../../i18n'
import type { DeepScanResult } from './deepScan'
import { ResultSheet } from './ResultSheet'
import { readAutoOpen, scanLog } from './sheetModel'

const clean: DeepScanResult = {
  build: '14192',
  platforms: ['windows'],
  results: [{ name: 'A', kind: 'signature', platforms: { windows: { status: 'ok', at: '0x10', verification: 'verified' } } }],
}

describe('ResultSheet', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en')
  })
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('says ready in the bar when nothing is wrong', () => {
    render(<ResultSheet result={clean} text={'{"A":{"signatures":{"windows":"x"}}}'} name="a.json" fixed={null} size="min" onSize={() => undefined} onJump={() => undefined} />)
    const sheet = screen.getByRole('region', { name: 'Scan result' })
    expect(sheet.textContent).toContain('Ready for 14192. 1 entry confirmed.')
    expect(sheet.querySelector('.rsheet-verdict.ok')).not.toBeNull()
  })

  it('renders nothing before a scan', () => {
    render(<ResultSheet result={clean} text="{}" name="a.json" fixed={null} size="closed" onSize={() => undefined} onJump={() => undefined} />)
    expect(screen.queryByRole('region')).toBeNull()
  })

  it('reads storage that throws as "do not open by itself"', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    expect(readAutoOpen()).toBe(false)
  })

  it('writes the raw log in the scanner\'s own format', () => {
    expect(scanLog({ ...clean, results: [{ ...clean.results[0], module: 'server' }] }))
      .toBe('[A]\n  ✓ Windows (server): ok at 0x10')
  })
})
