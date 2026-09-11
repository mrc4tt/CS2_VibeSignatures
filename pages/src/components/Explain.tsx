import type { ReactNode } from 'react'

/**
 * A note for someone meeting this data for the first time. Hidden in one place
 * by the Explain everything switch in the top bar, so the page reads clean once
 * the notes stop being useful.
 */
export function Explain({ children, html }: { children?: ReactNode; html?: string }) {
  return (
    <p className="explain">
      {html ? <span dangerouslySetInnerHTML={{ __html: html }} /> : <span>{children}</span>}
    </p>
  )
}
