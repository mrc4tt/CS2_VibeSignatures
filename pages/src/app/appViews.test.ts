import { describe, expect, it } from 'vitest'
import { APP_VIEWS, forgetStoredView, resolveView } from './appViews'

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
