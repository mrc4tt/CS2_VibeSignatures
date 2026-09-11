import type { AppView } from './appViews'

export interface NavigateRequest {
  view: AppView
  params?: Record<string, string | undefined>
}

const EVENT = 'handbook:navigate'

/**
 * Views are shell state rather than routes, so a link from a symbol to the
 * Game Data key that ships it needs one hop through the shell. A custom event
 * keeps that hop out of the feature components.
 */
export function requestNavigation(request: NavigateRequest): void {
  window.dispatchEvent(new CustomEvent<NavigateRequest>(EVENT, { detail: request }))
}

export function onNavigation(handler: (request: NavigateRequest) => void): () => void {
  const listener = (event: Event) => handler((event as CustomEvent<NavigateRequest>).detail)
  window.addEventListener(EVENT, listener)
  return () => window.removeEventListener(EVENT, listener)
}
