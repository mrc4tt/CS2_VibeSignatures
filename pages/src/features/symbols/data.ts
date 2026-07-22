import type { GameSymbolDataset, GameSymbolIndex } from './types'

const SYMBOL_ASSET_ROOT = `${import.meta.env.BASE_URL}gamesymbols/`

async function requestJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal })
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  return response.json() as Promise<T>
}

export function getGameSymbolIndex(signal?: AbortSignal): Promise<GameSymbolIndex> {
  return requestJson<GameSymbolIndex>(`${SYMBOL_ASSET_ROOT}index.json`, signal)
}

export function getGameSymbolDataset(assetUrl: string, signal?: AbortSignal): Promise<GameSymbolDataset> {
  return requestJson<GameSymbolDataset>(`${SYMBOL_ASSET_ROOT}${assetUrl}`, signal)
}
