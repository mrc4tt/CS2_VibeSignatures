import { describe, expect, it } from 'vitest'
import {
  adviceKind, factsOf, filterEntries, memberOffset, patternOf, pivotRecords, slotPair, verdictOf,
} from './pivot'
import type { GameSymbolRecord } from './types'

function record(
  artifact: string,
  platform: 'linux' | 'windows',
  payload: Record<string, unknown>,
  extra: Partial<GameSymbolRecord> = {},
): GameSymbolRecord {
  return {
    id: `server/${artifact}.${platform}.yaml`,
    module: 'server',
    artifact,
    symbolName: artifact,
    platform,
    kind: 'function',
    payload,
    ...extra,
  }
}

describe('pivoting the snapshot into one entry per symbol', () => {
  it('pairs the two platforms of the same symbol', () => {
    const entries = pivotRecords([
      record('ClientPrint', 'linux', { func_sig: '55 48 89 E5', func_size: '0xf2' }),
      record('ClientPrint', 'windows', { func_sig: '48 89 5C 24 ??', func_size: '0x7c' }),
    ])
    expect(entries).toHaveLength(1)
    expect(entries[0].linux?.platform).toBe('linux')
    expect(entries[0].windows?.platform).toBe('windows')
    expect(verdictOf(entries[0])).toBe('checked')
  })

  it('keeps a symbol that only one platform publishes, and says so', () => {
    const entries = pivotRecords([record('CNetworkGameServer_IsMapValid', 'linux', { func_size: '0x25' })])
    expect(verdictOf(entries[0])).toBe('onePlatform')
    expect(entries[0].windows).toBeUndefined()
  })

  it('flags a pattern that runs past the end of a short function', () => {
    const entries = pivotRecords([
      record('SetBeamOrigin', 'linux', { func_sig: '45 31 C0', func_sig_allow_across_function_boundary: true, func_size: '0x0' }),
      record('SetBeamOrigin', 'windows', { func_sig: '48 83 EC', func_size: '0x19' }),
    ])
    expect(verdictOf(entries[0])).toBe('caveat')
  })

  it('collects aliases from both platforms without repeating them', () => {
    const entries = pivotRecords([
      record('ClientPrintToController', 'linux', {}, { aliases: ['ClientPrint'] }),
      record('ClientPrintToController', 'windows', {}, { aliases: ['ClientPrint', 'PrintToChat'] }),
    ])
    expect(entries[0].aliases).toEqual(['ClientPrint', 'PrintToChat'])
  })

  it('reads the class from whichever platform carries it', () => {
    const entries = pivotRecords([
      record('CBaseTrigger_EndTouch', 'linux', { vfunc_index: 149 }),
      record('CBaseTrigger_EndTouch', 'windows', { vfunc_index: 150, vtable_name: 'CBaseTrigger' }),
    ])
    expect(entries[0].className).toBe('CBaseTrigger')
    expect(slotPair(entries[0])).toEqual({ linux: 149, windows: 150 })
    expect(adviceKind(entries[0])).toBe('vfunc')
  })

  it('prefers a real pattern field over none, in priority order', () => {
    expect(patternOf(record('a', 'linux', { vfunc_sig: '4C 8B', func_sig: '55 48' }))).toBe('55 48')
    expect(patternOf(record('a', 'linux', { vfunc_sig: '4C 8B' }))).toBe('4C 8B')
    expect(patternOf(record('a', 'linux', { func_sig: '   ' }))).toBeUndefined()
    expect(patternOf(undefined)).toBeUndefined()
  })

  it('reads a struct member as an offset, not a function', () => {
    const entries = pivotRecords([
      record('CBaseEntity_m_iTeamNum', 'linux', { struct_name: 'CBaseEntity', member_name: 'm_iTeamNum', offset: '0xaf0' },
        { kind: 'structMember', symbolName: 'CBaseEntity.m_iTeamNum' }),
    ])
    expect(adviceKind(entries[0])).toBe('member')
    expect(memberOffset(entries[0])).toBe('0xaf0')
  })

  it('pulls out only the facts a card shows', () => {
    const facts = factsOf(record('x', 'linux', {
      func_va: '0xd3ed90', func_rva: '0xd3ed90', func_size: '0x11',
      vfunc_index: 149, vfunc_offset: '0x4a8', vtable_name: 'CBaseTrigger', junk: 'ignored',
    }))
    expect(facts).toEqual({
      address: '0xd3ed90', rva: '0xd3ed90', size: '0x11',
      slot: 149, slotOffset: '0x4a8', offset: undefined, className: 'CBaseTrigger',
    })
  })
})

describe('filtering', () => {
  const entries = pivotRecords([
    record('ClientPrint', 'linux', { func_sig: '55', func_size: '0x1' }),
    record('ClientPrint', 'windows', { func_sig: '48', func_size: '0x1' }),
    record('CBaseTrigger_EndTouch', 'linux', { vfunc_index: 149, func_size: '0x11' }),
    { ...record('SDL_GetMouse', 'windows', { func_size: '0x8' }), module: 'SDL3' },
  ])

  it('searches name, module, class and aliases', () => {
    expect(filterEntries(entries, { query: 'touch' }).map((e) => e.symbolName)).toEqual(['CBaseTrigger_EndTouch'])
    expect(filterEntries(entries, { query: 'sdl3' })).toHaveLength(1)
    expect(filterEntries(entries, { query: 'nothing here' })).toHaveLength(0)
  })

  it('narrows to one module', () => {
    expect(filterEntries(entries, { query: '', module: 'SDL3' })).toHaveLength(1)
  })

  it('narrows to the symbols only one platform publishes', () => {
    const single = filterEntries(entries, { query: '', state: 'onePlatform' }).map((e) => e.symbolName)
    expect(single).toEqual(['CBaseTrigger_EndTouch', 'SDL_GetMouse'])
  })

  it('sorts by module when asked', () => {
    const sorted = filterEntries(entries, { query: '', sort: 'module' }).map((e) => e.module)
    expect(sorted[0]).toBe('SDL3')
  })
})
