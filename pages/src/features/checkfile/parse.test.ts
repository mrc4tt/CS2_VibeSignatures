import { describe, expect, it } from 'vitest'
import { keyName, parseGameData, stripJsonc } from './parse'

describe('reading a dropped gamedata file', () => {
  it('takes the entry name from the innermost segment that is not a kind word', () => {
    expect(keyName(['Signatures', 'ClientPrint'])).toBe('ClientPrint')
    expect(keyName(['ClientPrint', 'signatures'])).toBe('ClientPrint')
    expect(keyName(['Patches', 'FixWaterFloorJump', 'patch'])).toBe('FixWaterFloorJump')
  })

  it('reads plain JSON with platforms nested under a kind word', () => {
    const { format, values } = parseGameData(JSON.stringify({
      ClientPrint: { signatures: { library: 'server', linux: '55 48', windows: '40 53' } },
    }))
    expect(format).toBe('json')
    expect(values.get('ClientPrint')).toEqual({ linux: '55 48', windows: '40 53' })
    // "library" is a kind word, not an entry of its own
    expect(values.size).toBe(1)
  })

  it('reads a sectioned JSONC file, comments and trailing commas included', () => {
    const text = `{
      // CS2Fixes style
      "Signatures": {
        "UTIL_Remove": { "linux": "AA BB", "windows": "CC DD" },
      },
      "Offsets": {
        "CCSPlayer_WeaponServices::DropWeapon": { "linux": 29, "windows": 28 }
      }
    }`
    const { format, values } = parseGameData(text)
    expect(format).toBe('jsonc')
    expect(values.get('UTIL_Remove')).toEqual({ linux: 'AA BB', windows: 'CC DD' })
    expect(values.get('CCSPlayer_WeaponServices::DropWeapon')).toEqual({ linux: 29, windows: 28 })
  })

  it('reads a file saved under the wrong name by trying every format', () => {
    // JSONC content, .json name: the strict parse fails and the JSONC one wins
    const { format } = parseGameData('{ /* hi */ "A": { "linux": "AA", "windows": "BB" } }')
    expect(format).toBe('jsonc')
  })

  it('reads Valve KeyValues the way the pipeline does, outer block and all', () => {
    const text = `"Games"
{
\t"csgo"
\t{
\t\t"Signatures"
\t\t{
\t\t\t"Host_Say"
\t\t\t{
\t\t\t\t"library"  "server"
\t\t\t\t"linux"    "55 48 89"
\t\t\t\t"windows"  "40 53 48"
\t\t\t}
\t\t}
\t}
}`
    const { format, values } = parseGameData(text)
    expect(format).toBe('vdf')
    // The pipeline's reader is crude here and this one matches it on purpose:
    // the OUTER block becomes the entry, carrying the first platform values
    // found inside it. Verified against publish_site_data.read_values on this
    // exact text - it returns {'Games': ['55 48 89', '40 53 48']} - and on real
    // published .games.txt files, whose first key is literally "Games". Naming
    // the inner function here would disagree with history.json and report every
    // key as unknown.
    expect(values.get('Games')).toEqual({ linux: '55 48 89', windows: '40 53 48' })
    expect(values.has('Host_Say')).toBe(false)
  })

  it('treats a readable file with no entries as an answer, not a failure', () => {
    // CS2FOW's games.txt really does carry no platform entries. Verified against
    // publish_site_data.read_values on the real file: 0 keys, no error.
    const { format, values } = parseGameData('server_binary "libserver"\n')
    expect(format).toBe('vdf')
    expect(values.size).toBe(0)
  })

  it('reads an empty KeyValues block the way the pipeline does', () => {
    // read_values yields {"Games": [None, None]} for this, so this reader must
    // too - the two have to name the same keys or every key reads as unknown.
    const { values } = parseGameData('"Games"\n{\n}\n')
    expect(values.get('Games')).toEqual({ linux: null, windows: null })
  })

  it('strips block comments, line comments and trailing commas', () => {
    expect(stripJsonc('{"a":1, /* x */ "b":2,}').replace(/\s+/g, '')).toBe('{"a":1,"b":2}')
  })
})
