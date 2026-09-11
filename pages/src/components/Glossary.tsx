import type { ReactNode } from 'react'
import { useGlossary, type GlossaryTerm } from './glossaryTerms'

/** A term with its plain meaning one hover or one tab-stop away. */
export function Term({ term, children }: { term: GlossaryTerm; children?: ReactNode }) {
  const glossary = useGlossary()
  const { title, body } = glossary(term)
  return (
    <abbr className="term" tabIndex={0} title={`${title}: ${body}`}>
      {children ?? title}
    </abbr>
  )
}
