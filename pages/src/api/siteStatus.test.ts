import { describe, expect, it } from 'vitest'
import { compareBuilds, pendingBuild, type SiteStatus } from './siteStatus'

const now = Date.parse('2026-10-23T12:00:00Z')
const status = (build: string, state: SiteStatus['state'], startedAt = '2026-10-23T11:00:00Z'): SiteStatus =>
  ({ schemaVersion: 1, build, state, startedAt })

describe('the "gamedata on the way" banner', () => {
  it('orders re-release letters after their build', () => {
    expect(compareBuilds('14178b', '14178')).toBeGreaterThan(0)
    expect(compareBuilds('14179', '14178b')).toBeGreaterThan(0)
  })

  it('announces a build newer than every published one', () => {
    expect(pendingBuild(status('14193', 'started'), ['14191', '14192'], now)?.build).toBe('14193')
    expect(pendingBuild(status('14193', 'failed'), ['14192'], now)?.state).toBe('failed')
  })

  it('hides once the build is published, for a finished run, and for a stale one', () => {
    expect(pendingBuild(status('14192', 'started'), ['14192'], now)).toBeUndefined()
    expect(pendingBuild(status('14193', 'done'), ['14192'], now)).toBeUndefined()
    expect(pendingBuild(status('14193', 'started', '2026-10-10T00:00:00Z'), ['14192'], now)).toBeUndefined()
    expect(pendingBuild(undefined, ['14192'], now)).toBeUndefined()
  })
})
