import { useTranslation } from 'react-i18next'

export const GLOSSARY_TERMS = [
  'signature', 'wildcard', 'vfunc', 'slot', 'member', 'funcsize',
  'module', 'address', 'build', 'snapshot', 'alias', 'notproduced',
] as const

export type GlossaryTerm = (typeof GLOSSARY_TERMS)[number]

export interface GlossaryEntry {
  title: string
  body: string
}

/** Plain meanings live in the translations, so a term reads in every language. */
export function useGlossary(): (term: GlossaryTerm) => GlossaryEntry {
  const { t } = useTranslation()
  return (term) => {
    const entry = t(`glossary.${term}`, { returnObjects: true }) as unknown
    if (Array.isArray(entry) && typeof entry[0] === 'string' && typeof entry[1] === 'string') {
      return { title: entry[0], body: entry[1] }
    }
    return { title: term, body: '' }
  }
}
