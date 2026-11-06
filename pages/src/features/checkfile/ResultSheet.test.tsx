import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../../i18n'
import type { DeepScanResult } from './deepScan'
import { ResultSheet } from './ResultSheet'
import { readAutoOpen, scanLog, settleSheet } from './sheetModel'

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

  it('says under the verdict whose file it is and whether CounterStrikeSharp keeps it current', () => {
    render(
      <ResultSheet
        result={clean}
        text={'{"A":{"signatures":{"windows":"x"}}}'}
        name="multiaddonmanager.json"
        fixed={null}
        size="half"
        onSize={() => undefined}
        onJump={() => undefined}
        origin={{ plugin: 'multiaddonmanager', framework: 'metamod', evidence: 'name', reads: 'source', sourceFile: 'src/multiaddonmanager.cpp', coverage: 'compiled', feeds: [] }}
      />,
    )
    const note = screen.getByRole('note')
    expect(note).toHaveTextContent('Metamod:Source plugin: multiaddonmanager')
    expect(note).toHaveTextContent('CounterStrikeSharp auto-update: No')
    expect(note).toHaveTextContent('its signatures are literals in src/multiaddonmanager.cpp')
  })

  it('renders nothing before a scan', () => {
    render(<ResultSheet result={clean} text="{}" name="a.json" fixed={null} size="closed" onSize={() => undefined} onJump={() => undefined} />)
    expect(screen.queryByRole('region')).toBeNull()
  })

  it('opens by itself unless turned off, and reads storage that throws as on', () => {
    expect(readAutoOpen()).toBe(true)
    localStorage.setItem('cs2vibe.scan.autoOpen', '0')
    expect(readAutoOpen()).toBe(false)
    localStorage.removeItem('cs2vibe.scan.autoOpen')
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    expect(readAutoOpen()).toBe(true)
  })

  it('settles a dragged sheet on the nearest size, or the next one when flicked', () => {
    expect(settleSheet(80, 1000, 0)).toBe('min')
    expect(settleSheet(560, 1000, 0)).toBe('half')
    expect(settleSheet(900, 1000, 0)).toBe('full')
    // a short fast flick up from the bar opens it; down from half closes it
    expect(settleSheet(200, 1000, -1)).toBe('half')
    expect(settleSheet(700, 1000, -1)).toBe('full')
    expect(settleSheet(500, 1000, 1)).toBe('min')
    expect(settleSheet(800, 1000, 1)).toBe('half')
  })

  it('writes the raw log in the scanner\'s own format', () => {
    expect(scanLog({ ...clean, results: [{ ...clean.results[0], module: 'server' }] }))
      .toBe('[A]\n  ✓ Windows (server): ok at 0x10')
  })
})
