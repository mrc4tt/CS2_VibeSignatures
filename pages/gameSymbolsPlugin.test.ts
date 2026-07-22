import { describe, expect, it } from 'vitest'
import { createGameSymbolIndex, normalizeGameSymbolSnapshot } from './gameSymbolsPlugin'

function snapshot(files: Record<string, Record<string, unknown>>, gameVersion = '14168b') {
  return {
    schema_version: 3,
    config_digest_version: 2,
    analysis_output_contract_version: 1,
    config_sha256: 'sha256:test',
    file_count: Object.keys(files).length,
    files,
    game_version: gameVersion,
  }
}

describe('gameSymbolsPlugin normalization', () => {
  it('normalizes module, platform, kind, and display names', () => {
    const dataset = normalizeGameSymbolSnapshot(snapshot({
      'server/CBaseEntity_Teleport.windows.yaml': { func_name: 'CBaseEntity_Teleport', func_rva: '0x123' },
      'server/CBaseEntity_m_iHealth.linux.yaml': { struct_name: 'CBaseEntity', member_name: 'm_iHealth', offset: '0x344' },
      'client/CEntityInstance_vtable.windows.yaml': { vtable_class: 'CEntityInstance', vtable_entries: { 0: '0x1' } },
    }), '14168b', 'snapshot.yaml')

    expect(dataset.source.gameVersion).toBe('14168b')
    expect(dataset.modules).toEqual([
      { name: 'client', count: 1, windowsCount: 1, linuxCount: 0 },
      { name: 'server', count: 2, windowsCount: 1, linuxCount: 1 },
    ])
    expect(dataset.records).toEqual(expect.arrayContaining([
      expect.objectContaining({ module: 'server', platform: 'windows', kind: 'function', symbolName: 'CBaseEntity_Teleport' }),
      expect.objectContaining({ module: 'server', platform: 'linux', kind: 'structMember', symbolName: 'CBaseEntity.m_iHealth' }),
      expect.objectContaining({ module: 'client', kind: 'vtable', symbolName: 'CEntityInstance' }),
    ]))
  })

  it('rejects inconsistent file counts and game versions', () => {
    const value = snapshot({ 'server/Test.windows.yaml': { func_name: 'Test' } })
    expect(() => normalizeGameSymbolSnapshot({ ...value, file_count: 2 }, '14168b', 'snapshot.yaml')).toThrow(/file_count/)
    expect(() => normalizeGameSymbolSnapshot(value, '14169', 'snapshot.yaml')).toThrow(/does not match filename/)
    expect(() => normalizeGameSymbolSnapshot(snapshot({ 'server\\nested/Test.windows.yaml': { func_name: 'Test' } }), '14168b', 'snapshot.yaml')).toThrow(/invalid symbol path/)
  })

  it('sorts versions newest first without treating suffixes as numbers', () => {
    const older = normalizeGameSymbolSnapshot(snapshot({}, '14168'), '14168', '14168.yaml')
    const revision = normalizeGameSymbolSnapshot(snapshot({}, '14168b'), '14168b', '14168b.yaml')
    const latest = normalizeGameSymbolSnapshot(snapshot({}, '14169'), '14169', '14169.yaml')
    expect(createGameSymbolIndex([older, latest, revision]).versions.map((entry) => entry.gameVersion)).toEqual(['14169', '14168b', '14168'])
  })
})
