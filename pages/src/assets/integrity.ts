export interface IntegrityReference {
  sha256: string
  size: number
}

export async function requestJson(url: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(url, { signal, cache: 'no-cache' })
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  return response.json() as Promise<unknown>
}

export async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new Uint8Array(bytes))
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('')
}

const ASSET_CACHE = 'cs2vibe.assets.v1'

/**
 * Every asset here is content-addressed, so a cache hit can never be stale: a
 * changed file gets a new name. Read-through cache, and every failure path just
 * falls back to the network.
 */
async function cachedFetch(url: string, signal?: AbortSignal): Promise<Response> {
  if (typeof caches === 'undefined') return fetch(url, { signal })
  let cache: Cache
  try {
    cache = await caches.open(ASSET_CACHE)
  } catch {
    return fetch(url, { signal })
  }
  try {
    const hit = await cache.match(url)
    if (hit) return hit
  } catch {
    // an unreadable cache is not an error, it just means a network read
  }
  const response = await fetch(url, { signal })
  if (response.ok) {
    try {
      await cache.put(url, response.clone())
    } catch {
      // quota or an opaque response: keep the fetched copy, skip the cache
    }
  }
  return response
}

export async function fetchVerifiedBytes(
  url: string,
  reference: IntegrityReference,
  signal?: AbortSignal,
): Promise<ArrayBuffer> {
  const response = await cachedFetch(url, signal)
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  const bytes = await response.arrayBuffer()
  if (bytes.byteLength !== reference.size) {
    await forgetCachedAsset(url)
    throw new Error(`Asset size mismatch: expected ${reference.size}, received ${bytes.byteLength}`)
  }
  const actualSha256 = await sha256Hex(bytes)
  if (actualSha256 !== reference.sha256) {
    await forgetCachedAsset(url)
    throw new Error(`Asset SHA-256 mismatch: expected ${reference.sha256}, received ${actualSha256}`)
  }
  return bytes
}

async function forgetCachedAsset(url: string): Promise<void> {
  if (typeof caches === 'undefined') return
  try {
    const cache = await caches.open(ASSET_CACHE)
    await cache.delete(url)
  } catch {
    // nothing to clean up
  }
}

export function decodeUtf8(bytes: ArrayBuffer): string {
  return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
}
