import { describe, expect, it } from 'vitest'
import { ROUTE_PAGES, renderRouteShell, renderSymbolShell, summariseRecords } from './symbolPagesPlugin'
import { RESERVED_PATHS, VIEW_PATHS } from './src/app/appViews'
import type { GameSymbolRecord } from './gameSymbolsPlugin'

const SHELL = '<!doctype html><html><head><meta charset="utf-8"><title>CS2 VibeSignatures</title></head><body><div id="root"></div></body></html>'

function record(partial: Partial<GameSymbolRecord>): GameSymbolRecord {
  return {
    id: 'x',
    module: 'server',
    artifact: 'CBaseTrigger_EndTouch',
    symbolName: 'CBaseTrigger_EndTouch',
    platform: 'linux',
    kind: 'func',
    payload: {},
    ...partial,
  } as GameSymbolRecord
}

describe('symbol permalink pages', () => {
  it('folds a symbol’s two platforms into one summary', () => {
    const summaries = summariseRecords([
      record({ platform: 'linux', payload: { func_sig: '48 85 F6 74 ??' } }),
      record({ platform: 'windows', payload: { func_sig: '48 85 D2 0F 84' } }),
    ])
    expect(summaries).toHaveLength(1)
    expect(summaries[0]).toMatchObject({
      key: 'server/CBaseTrigger_EndTouch',
      symbolName: 'CBaseTrigger_EndTouch',
      linux: '48 85 F6 74 ??',
      windows: '48 85 D2 0F 84',
    })
  })

  it('describes a slot-only record by its slot rather than leaving it blank', () => {
    const [summary] = summariseRecords([record({ payload: { vfunc_index: 149 } })])
    expect(summary.linux).toBe('slot 149')
  })

  it('puts the real signature in the meta tags, escaped', () => {
    const [summary] = summariseRecords([record({ payload: { func_sig: '48 85 F6 & <b>' } })])
    const html = renderSymbolShell(SHELL, summary, '14181')
    expect(html).toContain('<title>CBaseTrigger_EndTouch · CS2 14181</title>')
    expect(html).toContain('og:description')
    expect(html).toContain('48 85 F6 &amp; &lt;b&gt;')
    expect(html).not.toContain('<b>')
    // the bundle the shell loads is untouched, so the page is the real app
    expect(html).toContain('<div id="root"></div>')
  })

  /**
   * The reason these pages exist: a static host answers an unknown path with its
   * 404 handler, so every route but "/" used to be a 404 even though a human saw
   * the right page. If a route is added to VIEW_PATHS and not here, it goes back
   * to being one silently.
   */
  it('covers every routable view', () => {
    const emitted = new Set(ROUTE_PAGES.map((route) => `/${route.path}`))
    const missing = Object.entries(VIEW_PATHS)
      .filter(([, path]) => path !== '/')
      .filter(([, path]) => !emitted.has(path))
      .map(([view, path]) => `${view} (${path})`)
    expect(missing).toEqual([])
  })

  it('never takes a path the published assets already own', () => {
    const clashes = ROUTE_PAGES.map((route) => route.path).filter((path) => RESERVED_PATHS.includes(path))
    expect(clashes).toEqual([])
  })

  it('gives a route its own title and description, not the symbol shape', () => {
    const route = ROUTE_PAGES.find((entry) => entry.path === 'diff')!
    const html = renderRouteShell(SHELL, route)
    expect(html).toContain('<title>Between builds</title>')
    expect(html).toContain(route.description)
    expect(html).toContain('content="/diff"')
  })
})
