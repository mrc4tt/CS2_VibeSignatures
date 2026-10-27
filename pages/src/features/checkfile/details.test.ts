import { describe, expect, it } from 'vitest'
import { fileDetails } from './details'
import { parseGameData } from './parse'

describe('file details', () => {
  it('counts each kind of entry and names the libraries', () => {
    const text = JSON.stringify({
      A: { signatures: { library: 'server', linux: '55 48', windows: '40 53' } },
      B: { signatures: { library: 'engine2', linux: '55', windows: '48' } },
      C: { offsets: { linux: 31, windows: 30 } },
      D: { signatures: { library: 'server', linux: '55', windows: '40' }, vtable: { class: 'X', linux_index: 3, windows_index: 4 } },
    }, null, 2)
    const details = fileDetails(text, parseGameData(text).values)
    expect(details).toEqual({ signatures: 3, offsets: 1, vtables: 1, libraries: ['engine2', 'server'] })
  })

  it('reads KeyValues libraries too', () => {
    const text = '"Games"\n{\n  "csgo"\n  {\n    "Signatures"\n    {\n      "A"\n      {\n        "library"  "server"\n        "linux"  "\\x55"\n      }\n    }\n  }\n}'
    expect(fileDetails(text, parseGameData(text).values).libraries).toEqual(['server'])
  })
})
