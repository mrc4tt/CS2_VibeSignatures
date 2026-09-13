export const APP_VIEWS = ['start', 'symbols', 'gamedata', 'check', 'runs', 'runs-live', 'words'] as const
export type AppView = (typeof APP_VIEWS)[number]

const LEGACY_VIEW_KEY = 'cs2vibe.view'

export function resolveView(value?: string | null): AppView {
  return APP_VIEWS.includes(value as AppView) ? (value as AppView) : 'start'
}

/**
 * The app no longer remembers which page you were on.
 *
 * It used to open wherever you left off, which meant a link to the site landed
 * people in the middle of Game Data or Check my file with no explanation. Start
 * is the page that says what this is, so every visit begins there. This clears
 * the key one last time for anyone who still has it stored.
 */
export function forgetStoredView(): void {
  try {
    localStorage.removeItem(LEGACY_VIEW_KEY)
  } catch {
    // a private window is not a reason to fail a load
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
