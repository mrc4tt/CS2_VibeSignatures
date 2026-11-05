import { useTranslation } from 'react-i18next'
import { GLOSSARY_TERMS, useGlossary } from '../../components/glossaryTerms'
import { Key } from '../../ui/primitives'

const SHORTCUTS = [
  ['↑ ↓', 'words.kbArrows'],
  ['Enter', 'words.kbEnter'],
  ['/', 'words.kbSlash'],
  ['Ctrl K', 'words.kbPalette'],
  ['?', 'words.kbHelp'],
  ['Esc', 'words.kbEsc'],
] as const

export function WordsPage() {
  const { t } = useTranslation()
  const glossary = useGlossary()
  const terms = [...GLOSSARY_TERMS]
    .map((term) => ({ term, ...glossary(term) }))
    .sort((left, right) => left.title.localeCompare(right.title))

  return (
    <div className="handbook">
      <div className="hero">
        <h1>{t('words.h1')}</h1>
        <p className="lede">{t('words.sub')}</p>
      </div>

      <section className="panel">
        <div className="panel-body wordlist">
          {terms.map((entry) => (
            <div key={entry.term}>
              <h3 className="wordterm">{entry.title}</h3>
              <p className="plain prose">{entry.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <header><h2>{t('words.kbH')}</h2></header>
        <div className="panel-body">
          <dl className="shortcuts">
            {SHORTCUTS.map(([keys, label]) => (
              <div key={label}>
                <dt><Key>{keys}</Key></dt>
                <dd>{t(label)}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>
    </div>
  )
}
