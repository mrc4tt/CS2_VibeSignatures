export const APP_VIEWS = ['start', 'symbols', 'gamedata', 'check', 'runs', 'runs-live', 'words'] as const
export type AppView = (typeof APP_VIEWS)[number]

const STORAGE_KEY = 'cs2vibe.view'

export function resolveView(value?: string | null): AppView {
  return APP_VIEWS.includes(value as AppView) ? (value as AppView) : 'start'
}

/** Remember where someone was, so a reload does not send them back to Start. */
export function readStoredView(): AppView {
  try {
    return resolveView(localStorage.getItem(STORAGE_KEY))
  } catch {
    return 'start'
  }
}

export function persistView(view: AppView): void {
  try {
    localStorage.setItem(STORAGE_KEY, view)
  } catch {
    // a private window is not a reason to fail a click
  }
}

const EXPLAIN_KEY = 'cs2vibe.explain'

export function readExplain(): boolean {
  try {
    return localStorage.getItem(EXPLAIN_KEY) !== '0'
  } catch {
    return true
  }
}

export function persistExplain(enabled: boolean): void {
  try {
    localStorage.setItem(EXPLAIN_KEY, enabled ? '1' : '0')
  } catch {
    // same
  }
}
