import { describe, expect, it } from 'vitest'
import { APP_VIEWS, forgetStoredView, resolveView, VIEW_PATHS, viewFromPath } from './appViews'

describe('which page the app opens on', () => {
  it('resolves anything unknown to Start', () => {
    expect(resolveView(null)).toBe('start')
    expect(resolveView('nonsense')).toBe('start')
    expect(resolveView('gamedata')).toBe('gamedata')
  })

  it('clears the key that used to reopen the last page', () => {
    // A visit no longer lands wherever the previous one ended, and anyone who
    // still has the old value stored has it removed on load.
    localStorage.setItem('cs2vibe.view', 'check')
    forgetStoredView()
    expect(localStorage.getItem('cs2vibe.view')).toBeNull()
  })

  it('lists Check my file among the views', () => {
    expect(APP_VIEWS).toContain('check')
  })
})

describe('every view has its own URL', () => {
  it('gives each view a distinct path', () => {
    const paths = APP_VIEWS.map((view) => VIEW_PATHS[view])
    expect(new Set(paths).size).toBe(paths.length)
    expect(VIEW_PATHS.start).toBe('/')
  })

  it('reads the view back out of a pathname', () => {
    expect(viewFromPath('/')).toBe('start')
    expect(viewFromPath('/gamedata')).toBe('gamedata')
    expect(viewFromPath('/check')).toBe('check')
    expect(viewFromPath('/words')).toBe('words')
    expect(viewFromPath('/analysis')).toBe('runs')
  })

  it('tolerates a trailing slash, because a pasted link often has one', () => {
    expect(viewFromPath('/check/')).toBe('check')
    expect(viewFromPath('gamedata')).toBe('gamedata')
  })

  it('keeps /runs and its run pages on the live view, where existing links point', () => {
    expect(viewFromPath('/runs')).toBe('runs-live')
    expect(viewFromPath('/runs/abc123')).toBe('runs-live')
  })

  it('falls back to Start for anything it does not know', () => {
    expect(viewFromPath('/nope')).toBe('start')
    expect(viewFromPath('/gamedata/extra')).toBe('start')
  })
})
