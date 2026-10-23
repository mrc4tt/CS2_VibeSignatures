import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * A note for someone meeting this data for the first time, folded away by
 * default. It used to be an open callout on every page behind a site-wide
 * "Explain everything" switch; folded, it costs one line and needs no switch.
 */
export function Explain({ children, html, summary }: { children?: ReactNode; html?: string; summary?: string }) {
  const { t } = useTranslation()
  return (
    <details className="explain">
      <summary>{summary ?? t('shell2.whatIsThis')}</summary>
      {html ? <p dangerouslySetInnerHTML={{ __html: html }} /> : <p>{children}</p>}
    </details>
  )
}
