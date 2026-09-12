import { describe, expect, it } from 'vitest'
import type { SiteHistory } from '../../api/siteData'
import type { FileValue } from './parse'
import { bestFit, identifyFile, keyVerdicts, scoreBuilds, summarise } from './verdict'

const MATCHZY = 'matchzy/gamedata/matchzy.json'
const CSS = 'CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json'

const history: SiteHistory = {
  schemaVersion: 1,
  gameVersion: '14181',
  builds: [
    { gameVersion: '14178b', keyChanges: 0 },
    { gameVersion: '14180', keyChanges: 1 },
    { gameVersion: '14181', keyChanges: 1 },
  ],
  files: {
    [MATCHZY]: {
      JoinTeam: { points: [['14178b', 'OLD', 'W-OLD'], ['14181', 'NEW', 'W-NEW']], changes: ['14181'] },
      PostCleanUp: { points: [['14178b', 'SAME', 'W-SAME']], changes: [] },
      SelectItem: { points: [['14178b', 31, 30]], changes: [] },
      DropWeapon: { points: [['14180', 29, 28]], changes: ['14180'] },
    },
    [CSS]: {
      JoinTeam: { points: [['14178b', 'OLD', 'W-OLD'], ['14181', 'NEW', 'W-NEW']], changes: ['14181'] },
      SetStateChanged: { points: [['14178b', 29, 28]], changes: [] },
    },
  },
  keyToSymbol: {},
  symbolToKeys: {},
}

const values = (entries: Record<string, FileValue>): Map<string, FileValue> => new Map(Object.entries(entries))

describe('identifying which published file an upload is', () => {
  it('names the file when one candidate is clearly ahead', () => {
    const result = identifyFile(values({
      JoinTeam: { linux: 'NEW', windows: 'W-NEW' },
      PostCleanUp: { linux: 'SAME', windows: 'W-SAME' },
      SelectItem: { linux: 31, windows: 30 },
      DropWeapon: { linux: 29, windows: 28 },
    }), history)
    expect(result.decisive).toBe(true)
    expect(result.best?.plugin).toBe('matchzy')
    expect(result.best?.shared).toBe(4)
  })

  it('refuses to guess when the only shared key is one both plugins ship', () => {
    const result = identifyFile(values({ JoinTeam: { linux: 'NEW', windows: 'W-NEW' } }), history)
    expect(result.decisive).toBe(false)
  })

  it('has nothing to say about an empty file', () => {
    expect(identifyFile(new Map(), history)).toEqual({ decisive: false, ranked: [] })
  })
})

describe('working out which build a file is', () => {
  it('puts the newest build first and scores it best for a current file', () => {
    const scores = scoreBuilds(values({
      JoinTeam: { linux: 'NEW', windows: 'W-NEW' },
      PostCleanUp: { linux: 'SAME', windows: 'W-SAME' },
      DropWeapon: { linux: 29, windows: 28 },
    }), history, MATCHZY)
    expect(scores.map((score) => score.build)).toEqual(['14181', '14180', '14178b'])
    expect(scores[0]).toMatchObject({ build: '14181', matched: 3, comparable: 3 })
    // the same file scores worse against 14180, where JoinTeam held its old value
    expect(scores[1]!.matched).toBe(2)
  })

  it('identifies an out-of-date file as the build it actually is', () => {
    const scores = scoreBuilds(values({
      JoinTeam: { linux: 'OLD', windows: 'W-OLD' },
      PostCleanUp: { linux: 'SAME', windows: 'W-SAME' },
      DropWeapon: { linux: 29, windows: 28 },
    }), history, MATCHZY)
    const best = scores.reduce((left, right) => (right.share > left.share ? right : left))
    expect(best.build).toBe('14180')
    // and 14178b is worse still, because DropWeapon did not exist there yet
    expect(scores.find((score) => score.build === '14181')!.matched).toBe(2)
  })

  it('ignores keys the file does not carry rather than counting them against it', () => {
    const scores = scoreBuilds(values({ PostCleanUp: { linux: 'SAME', windows: 'W-SAME' } }), history, MATCHZY)
    expect(scores[0]).toMatchObject({ matched: 1, comparable: 1, share: 1 })
  })
})

describe('per-key verdicts', () => {
  const verdicts = keyVerdicts(values({
    JoinTeam: { linux: 'OLD', windows: 'W-OLD' },
    PostCleanUp: { linux: 'SAME', windows: 'W-SAME' },
    MyOwnKey: { linux: 'AA', windows: 'BB' },
  }), history, MATCHZY, '14181')

  it('marks a stale value outdated and carries what it should be', () => {
    const joinTeam = verdicts.find((verdict) => verdict.key === 'JoinTeam')!
    expect(joinTeam.state).toBe('outdated')
    expect(joinTeam.expected).toEqual(['NEW', 'W-NEW'])
  })

  it('marks an unchanged value current', () => {
    expect(verdicts.find((verdict) => verdict.key === 'PostCleanUp')!.state).toBe('current')
  })

  it('separates keys the published file has from keys only the upload has', () => {
    expect(verdicts.find((verdict) => verdict.key === 'SelectItem')!.state).toBe('absent')
    expect(verdicts.find((verdict) => verdict.key === 'MyOwnKey')!.state).toBe('unknown')
  })

  it('counts one state per key', () => {
    const summary = summarise(verdicts)
    expect(summary.current + summary.outdated + summary.unknown + summary.absent).toBe(verdicts.length)
    expect(summary).toMatchObject({ current: 1, outdated: 1, unknown: 1 })
  })

  it('does not fault a file for a platform it does not ship', () => {
    const linuxOnly = keyVerdicts(values({ JoinTeam: { linux: 'NEW', windows: null } }), history, MATCHZY, '14181')
    expect(linuxOnly.find((verdict) => verdict.key === 'JoinTeam')!.state).toBe('current')
  })
})

describe('picking which build a file is when several fit', () => {
  it('names the newest fitting build and reports the tie', () => {
    // PostCleanUp never changed, so this file fits every build equally
    const fit = bestFit(scoreBuilds(values({ PostCleanUp: { linux: 'SAME', windows: 'W-SAME' } }), history, MATCHZY))
    expect(fit).toMatchObject({ build: '14181', oldest: '14178b', tied: true, share: 1 })
  })

  it('prefers the build that explains more of the file over an equally scoring older one', () => {
    // 14180 and 14178b both score 100%, because DropWeapon did not exist at
    // 14178b and so cannot be compared there. 14180 compares two keys against
    // one, so it is the better explanation and the file is not called older
    // than the evidence supports.
    const fit = bestFit(scoreBuilds(values({
      JoinTeam: { linux: 'OLD', windows: 'W-OLD' },
      DropWeapon: { linux: 29, windows: 28 },
    }), history, MATCHZY))
    expect(fit).toMatchObject({ build: '14180', oldest: '14180', tied: false, comparable: 2 })
  })

  it('has no answer without scores', () => {
    expect(bestFit([])).toBeUndefined()
  })
})
