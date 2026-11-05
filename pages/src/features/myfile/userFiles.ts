/**
 * Stored user files: a server owner's own gamedata file, kept on the scan server and
 * brought up to date after every CS2 build (user_files.py / user_gamedata.py).
 *
 * Two secrets, no account. The read link (`/api/files/<id>/<name>`) is what a game
 * server fetches; the manage token changes or deletes the file and travels only in
 * the X-Manage-Token header and in the URL fragment of /my-file, which no server and
 * no access log ever sees.
 */

import { DEEP_SCAN_API } from '../checkfile/deepScan'

export interface StoredChange {
  key: string
  platform: 'linux' | 'windows'
  from: string | number
  to: string | number
  how: string
}

export interface StoredUnresolved {
  key: string
  platform: string
  why: string
}

export interface StoredHistory {
  build: string
  at: number
  event: 'update' | 'replaced'
  changes: StoredChange[]
  unresolved: StoredUnresolved[]
}

export interface StoredFile {
  id: string
  filename: string
  format?: string | null
  created: number
  updated: number
  baseline_build: string | null
  last_fetch: number | null
  history: StoredHistory[]
  webhook: boolean
  url: string
  current: string
}

export interface CreatedFile {
  id: string
  manage: string
  filename: string
  url: string
  build: string
}

export class StoreError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'StoreError'
    this.status = status
  }
}

/** The read link as a server fetches it: absolute, on the API's own host. */
export function readLink(url: string, base: string = DEEP_SCAN_API): string {
  return new URL(url, new URL(base).origin).toString()
}

/** The manage page for a token; the token sits in the fragment, never sent to a server. */
export function manageLink(token: string, origin: string = window.location.origin): string {
  return `${origin}/my-file#${token}`
}

async function call<T>(path: string, init: RequestInit, base: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${base}${path}`, init)
  } catch {
    throw new StoreError(0, 'offline')
  }
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // nginx's own error pages are not JSON
  }
  if (!response.ok) {
    const message = (body as { error?: string } | null)?.error ?? `HTTP ${response.status}`
    throw new StoreError(response.status, message)
  }
  return body as T
}

export function storeFile(
  text: string,
  filename: string,
  build?: string,
  webhook?: string,
  base: string = DEEP_SCAN_API,
): Promise<CreatedFile> {
  return call<CreatedFile>('/files', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ gamedata: text, filename, ...(build ? { build } : {}), ...(webhook ? { webhook } : {}) }),
  }, base)
}

function manageInit(token: string, method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: {
      'X-Manage-Token': token,
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  }
}

export function getStoredFile(token: string, base: string = DEEP_SCAN_API): Promise<StoredFile> {
  return call<StoredFile>('/files/manage', manageInit(token, 'GET'), base)
}

export function updateStoredFile(
  token: string,
  change: { gamedata?: string; filename?: string; build?: string; webhook?: string | null },
  base: string = DEEP_SCAN_API,
): Promise<StoredFile> {
  return call<StoredFile>('/files/manage', manageInit(token, 'PUT', change), base)
}

export function deleteStoredFile(token: string, base: string = DEEP_SCAN_API): Promise<{ deleted: boolean }> {
  return call<{ deleted: boolean }>('/files/manage', manageInit(token, 'DELETE'), base)
}

/** This browser's own list of files it stored, so the manage links are not lost. */
const LOCAL_KEY = 'cs2vibe.myfiles'

export interface LocalFile {
  token: string
  filename: string
  created: number
}

export function readLocalFiles(): LocalFile[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(LOCAL_KEY) ?? '[]') as unknown
    return Array.isArray(parsed)
      ? parsed.filter((row): row is LocalFile => typeof row?.token === 'string' && typeof row?.filename === 'string')
      : []
  } catch {
    return []
  }
}

export function rememberLocalFile(row: LocalFile): void {
  try {
    const rows = readLocalFiles().filter((other) => other.token !== row.token)
    localStorage.setItem(LOCAL_KEY, JSON.stringify([row, ...rows].slice(0, 20)))
  } catch {
    // private mode: the links on screen are all there is
  }
}

export function forgetLocalFile(token: string): void {
  try {
    localStorage.setItem(LOCAL_KEY, JSON.stringify(readLocalFiles().filter((row) => row.token !== token)))
  } catch {
    // nothing kept, nothing to forget
  }
}

/** The token a /my-file URL carries in its fragment, if it looks like one. */
export function tokenFromHash(hash: string): string | null {
  const token = hash.replace(/^#/, '').trim()
  return /^[A-Za-z0-9_-]{43}$/.test(token) ? token : null
}
