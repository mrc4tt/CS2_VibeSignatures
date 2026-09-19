import { describe, expect, it } from 'vitest'
import { changedEntries } from './entries'

const JSON_FILE = `{
  "ClientPrint": {
    "signatures": { "library": "server", "linux": "55 48", "windows": "40 53" }
  },
  "JoinTeam": {
    "signatures": { "library": "server", "linux": "55 48 89", "windows": "48 89" }
  }
}`

const KEYVALUES_FILE = `"Games"
{
  "csgo"
  {
    "Signatures"
    {
      "ClientPrint"
      {
        "library"  "server"
        "linux"    "\\x55\\x48"
      }
    }
  }
}`

describe('changedEntries', () => {
  it('cuts each block out verbatim, nested braces included, and nothing next to it', () => {
    const result = changedEntries(JSON_FILE, ['JoinTeam'])
    expect(result.text).toBe(`"JoinTeam": {
    "signatures": { "library": "server", "linux": "55 48 89", "windows": "48 89" }
  }`)
    expect(result.text).not.toContain('ClientPrint')
  })

  it('keeps the KeyValues spelling', () => {
    const result = changedEntries(KEYVALUES_FILE, ['ClientPrint'])
    expect(result.text).toContain('"linux"    "\\x55\\x48"')
    expect(result.text.startsWith('"ClientPrint"')).toBe(true)
  })

  it('reports keys the file does not have', () => {
    const result = changedEntries(JSON_FILE, ['ClientPrint', 'Gone'])
    expect(result.found).toEqual(['ClientPrint'])
    expect(result.missing).toEqual(['Gone'])
  })
})
