import { useTranslation } from 'react-i18next'
import { GLOSSARY_TERMS, useGlossary } from '../../components/glossaryTerms'

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
          <div className="steps">
            {['words.kb1', 'words.kb2', 'words.kb3'].map((key, index) => (
              <div className="step" key={key}>
                <span className="i">{index + 1}</span>
                <span>{t(key)}</span>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
