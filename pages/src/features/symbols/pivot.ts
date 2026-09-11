import type { GameSymbolRecord } from './types'

export type SymbolPlatform = 'linux' | 'windows'

/**
 * One entry per symbol rather than one per record. The snapshot stores a record
 * per platform, which makes 3763 rows out of roughly 2000 symbols and hides the
 * thing people actually want to see: what Linux says next to what Windows says,
 * and whether one of them is missing.
 */
export interface SymbolEntry {
  key: string
  module: string
  artifact: string
  symbolName: string
  kind: string
  aliases: string[]
  className?: string
  linux?: GameSymbolRecord
  windows?: GameSymbolRecord
}

export type Verdict = 'checked' | 'caveat' | 'onePlatform'

export function pivotRecords(records: GameSymbolRecord[]): SymbolEntry[] {
  const entries = new Map<string, SymbolEntry>()
  for (const record of records) {
    const key = `${record.module}/${record.artifact}`
    let entry = entries.get(key)
    if (!entry) {
      entry = {
        key,
        module: record.module,
        artifact: record.artifact,
        symbolName: record.symbolName,
        kind: record.kind,
        aliases: [],
      }
      entries.set(key, entry)
    }
    entry[record.platform] = record
    for (const alias of record.aliases ?? []) {
      if (!entry.aliases.includes(alias)) entry.aliases.push(alias)
    }
    const owner = record.payload as Record<string, unknown>
    const className = owner.vtable_name ?? owner.struct_name ?? owner.vtable_class
    if (typeof className === 'string' && className.length > 0) entry.className = className
    // A record with a payload describes the symbol better than an empty one.
    if (Object.keys(owner).length > 0 && entry.kind === 'unknown') entry.kind = record.kind
  }
  return [...entries.values()].sort((left, right) => left.symbolName.localeCompare(right.symbolName))
}

function payloadOf(record?: GameSymbolRecord): Record<string, unknown> {
  return (record?.payload as Record<string, unknown>) ?? {}
}

export function patternOf(record?: GameSymbolRecord): string | undefined {
  const payload = payloadOf(record)
  for (const field of ['func_sig', 'vfunc_sig', 'offset_sig', 'gv_sig'] as const) {
    const value = payload[field]
    if (typeof value === 'string' && value.trim().length > 0) return value
  }
  return undefined
}

export function verdictOf(entry: SymbolEntry): Verdict {
  if (!entry.linux || !entry.windows) return 'onePlatform'
  const soft = [entry.linux, entry.windows].some((record) => {
    const payload = payloadOf(record)
    const size = payload.func_size
    const acrossBoundary = payload.func_sig_allow_across_function_boundary
    return acrossBoundary === true || acrossBoundary === 'true' || size === undefined || size === '0x0'
  })
  return soft ? 'caveat' : 'checked'
}

export interface SlotPair {
  linux?: number
  windows?: number
}

export function slotPair(entry: SymbolEntry): SlotPair | undefined {
  const linux = payloadOf(entry.linux).vfunc_index
  const windows = payloadOf(entry.windows).vfunc_index
  if (!Number.isInteger(linux) && !Number.isInteger(windows)) return undefined
  return {
    linux: Number.isInteger(linux) ? (linux as number) : undefined,
    windows: Number.isInteger(windows) ? (windows as number) : undefined,
  }
}

export function memberOffset(entry: SymbolEntry): string | undefined {
  const value = payloadOf(entry.linux).offset ?? payloadOf(entry.windows).offset
  return typeof value === 'string' || typeof value === 'number' ? String(value) : undefined
}

/** Which of the four "what do I do with this" answers applies. */
export function adviceKind(entry: SymbolEntry): 'member' | 'global' | 'vfunc' | 'function' {
  if (entry.kind === 'structMember') return 'member'
  if (entry.kind === 'global') return 'global'
  if (slotPair(entry)) return 'vfunc'
  return 'function'
}

export interface SymbolFacts {
  address?: string
  rva?: string
  size?: string
  slot?: number
  slotOffset?: string
  offset?: string
  className?: string
}

export function factsOf(record?: GameSymbolRecord): SymbolFacts {
  const payload = payloadOf(record)
  const text = (value: unknown): string | undefined =>
    typeof value === 'string' && value.length > 0 ? value : typeof value === 'number' ? String(value) : undefined
  return {
    address: text(payload.func_va ?? payload.gv_va),
    rva: text(payload.func_rva),
    size: text(payload.func_size),
    slot: Number.isInteger(payload.vfunc_index) ? (payload.vfunc_index as number) : undefined,
    slotOffset: text(payload.vfunc_offset),
    offset: text(payload.offset),
    className: text(payload.vtable_name ?? payload.struct_name ?? payload.vtable_class),
  }
}

export interface SymbolFilters {
  query: string
  module?: string
  state?: 'all' | 'onePlatform' | 'caveat'
  sort?: 'name' | 'module'
}

export function filterEntries(entries: SymbolEntry[], filters: SymbolFilters): SymbolEntry[] {
  const query = filters.query.trim().toLowerCase()
  const matched = entries.filter((entry) => {
    if (filters.module && entry.module !== filters.module) return false
    if (filters.state === 'onePlatform' && verdictOf(entry) !== 'onePlatform') return false
    if (filters.state === 'caveat' && verdictOf(entry) !== 'caveat') return false
    if (!query) return true
    const haystack = [
      entry.symbolName, entry.artifact, entry.module, entry.className ?? '', entry.aliases.join(' '),
    ].join(' ').toLowerCase()
    return haystack.includes(query)
  })
  if (filters.sort === 'module') {
    return matched
      .slice()
      .sort((left, right) => left.module.localeCompare(right.module) || left.symbolName.localeCompare(right.symbolName))
  }
  return matched
}
