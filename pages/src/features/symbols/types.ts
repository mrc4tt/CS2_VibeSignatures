export type GameSymbolPlatform = 'windows' | 'linux'

export interface GameSymbolIndex {
  schemaVersion: 1
  versions: Array<{
    gameVersion: string
    url: string
    snapshotSchemaVersion: number
    fileCount: number
  }>
}

export interface GameSymbolRecord {
  id: string
  module: string
  artifact: string
  symbolName: string
  platform: GameSymbolPlatform
  kind: string
  payload: Record<string, unknown>
}

export interface GameSymbolDataset {
  schemaVersion: 1
  source: {
    gameVersion: string
    snapshotSchemaVersion: number
    configDigestVersion: number
    analysisOutputContractVersion: number
    configSha256: string
    fileCount: number
  }
  modules: Array<{
    name: string
    count: number
    windowsCount: number
    linuxCount: number
  }>
  records: GameSymbolRecord[]
}

export interface SymbolFilters {
  module?: string
  query: string
  platform?: GameSymbolPlatform
}
