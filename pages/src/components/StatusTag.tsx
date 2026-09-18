import { useTranslation } from 'react-i18next'
import type { RunStatus, TaskStatus } from '../api/types'
import { Dot, Tag } from '../ui/primitives'
import { statusLabel } from './status'

/**
 * antd mapped these onto its preset colours; the tones are the site's own
 * vocabulary now, so "succeeded" and a passing signature read the same green.
 */
const TONES = {
  queued: 'neutral',
  starting: 'accent',
  pending: 'neutral',
  running: 'accent',
  succeeded: 'ok',
  failed: 'bad',
  skipped: 'warn',
  aborted: 'neutral',
  stale: 'warn',
} as const

export function StatusTag({ status }: { status: RunStatus | TaskStatus }) {
  const tone = TONES[status as keyof typeof TONES] ?? 'neutral'
  const { t } = useTranslation()
  return (
    <Tag tone={tone} className={status === 'running' ? 'status-running' : undefined}>
      <Dot tone={tone} />
      {statusLabel(status, t)}
    </Tag>
  )
}
