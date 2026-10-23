import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { getSiteMeta } from '../api/siteMeta'
import { getSiteStatus, pendingBuild } from '../api/siteStatus'
import { formatAgo } from './whenText'

/**
 * "CS2 updated, gamedata is on the way". Says nothing unless autopilot has seen
 * a build newer than every published one, so on an ordinary day it is absent.
 */
export function BuildStatusBanner() {
  const { t, i18n } = useTranslation()
  const language = i18n.resolvedLanguage ?? 'en'
  const statusQuery = useQuery({
    queryKey: ['site-status'],
    queryFn: ({ signal }) => getSiteStatus(signal),
    staleTime: 2 * 60 * 1000,
  })
  const metaQuery = useQuery({
    queryKey: ['site-meta'],
    queryFn: ({ signal }) => getSiteMeta(signal),
    staleTime: 5 * 60 * 1000,
  })
  // Without the published list there is nothing to compare with, and a banner
  // that might be wrong is worse than none.
  const pending = metaQuery.data ? pendingBuild(statusQuery.data, metaQuery.data.builds) : undefined
  if (!pending) return null
  const ago = formatAgo(pending.startedAt, language)
  return (
    <div className="statusbanner" data-state={pending.state} role="status">
      <span className="dotpulse" aria-hidden="true" />
      <span>
        <b>{t('buildStatus.updated', { build: pending.build })}</b>{' '}
        {pending.state === 'failed'
          ? t('buildStatus.failed', { latest: metaQuery.data?.latest.gameVersion ?? '' })
          : t('buildStatus.started', { ago, latest: metaQuery.data?.latest.gameVersion ?? '' })}
      </span>
    </div>
  )
}
