export const APP_VIEWS = ['start', 'symbols', 'gamedata', 'diff', 'check', 'runs', 'runs-live', 'words'] as const
export type AppView = (typeof APP_VIEWS)[number]

const LEGACY_VIEW_KEY = 'cs2vibe.view'

/**
 * One path per view, so the browser's own Back button works.
 *
 * Until now every view was shell state on a single route: clicking a card on
 * Start changed what was rendered without adding a history entry, so Back left
 * the site entirely. The live run pages keep /runs, which is where their links
 * already point.
 */
export const VIEW_PATHS: Record<AppView, string> = {
  start: '/',
  symbols: '/symbols',
  // NOT /gamedata: that is a directory of published assets at the site root, and
  // GitHub Pages serves its index.json as the directory index - so visiting the
  // route and reloading printed raw JSON instead of the page.
  gamedata: '/game-data',
  diff: '/diff',
  check: '/check',
  words: '/words',
  runs: '/analysis',
  'runs-live': '/runs',
}

/**
 * Names the built site occupies at its root, which a route therefore cannot use.
 *
 * The published data is emitted beside index.html - gamedata/, gamesymbols/,
 * diagnostics/, badge/, assets/ - and a static host answers those before any
 * SPA fallback. A route sharing a name is not a routing bug that shows up in
 * development; it is a page that works until someone reloads it.
 */
export const RESERVED_PATHS = [
  'assets', 'badge', 'diagnostics', 'gamedata', 'gamesymbols',
  'history.json', 'latest.json', 'vite.svg',
]

/** Which view a pathname names; anything unrecognised is Start. */
export function viewFromPath(pathname: string): AppView {
  const path = `/${pathname.replace(/^\/+|\/+$/g, '')}`
  if (path === '/runs' || path.startsWith('/runs/')) return 'runs-live'
  // /symbols/<key> is a permalink to one symbol, so it is still the symbols view.
  if (path.startsWith('/symbols/')) return 'symbols'
  const found = (Object.keys(VIEW_PATHS) as AppView[]).find(
    (view) => view !== 'runs-live' && VIEW_PATHS[view] === path,
  )
  return found ?? 'start'
}

/**
 * The symbol a /symbols/<key> permalink names, or undefined for the plain list.
 *
 * A link someone can paste into a plugin channel has to survive being read by
 * something that does not run JavaScript, which is why the key lives in the path
 * and not only in ?symbol=.
 */
export function symbolFromPath(pathname: string): string | undefined {
  const path = `/${pathname.replace(/^\/+|\/+$/g, '')}`
  if (!path.startsWith('/symbols/')) return undefined
  const key = decodeURIComponent(path.slice('/symbols/'.length))
  return key.length > 0 ? key : undefined
}

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
