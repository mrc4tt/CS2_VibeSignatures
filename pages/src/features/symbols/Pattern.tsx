import { useTranslation } from 'react-i18next'

function tokens(pattern: string): string[] {
  return pattern.trim().split(/\s+/)
}

function isWildcard(token: string): boolean {
  return token === '??' || token === '?'
}

/**
 * A byte pattern read as a pattern, not as a string: the wildcards are dimmed so
 * its shape is visible at a glance, and the fixed bytes carry the contrast.
 */
export function Pattern({ pattern, limit }: { pattern: string; limit?: number }) {
  const { t } = useTranslation()
  const all = tokens(pattern)
  const shown = limit ? all.slice(0, limit) : all
  const rest = all.length - shown.length
  return (
    <span className="pat">
      {shown.map((token, index) => (
        <span key={index} className={isWildcard(token) ? 'wc' : undefined}>
          {token}
          {index < shown.length - 1 ? ' ' : ''}
        </span>
      ))}
      {rest > 0 && <span className="more"> {t('symbols2.more', { count: rest })}</span>}
    </span>
  )
}

/** The same bytes laid out sixteen to a line, with a count of what is fixed. */
export function PatternDump({ pattern }: { pattern: string }) {
  const { t } = useTranslation()
  const all = tokens(pattern)
  const rows: string[][] = []
  for (let index = 0; index < all.length; index += 16) rows.push(all.slice(index, index + 16))
  const wildcards = all.filter(isWildcard).length
  const fixed = Math.round((100 * (all.length - wildcards)) / Math.max(1, all.length))
  return (
    <div>
      <div className="hexdump">
        {rows.map((row, rowIndex) => (
          <div className="hexrow" key={rowIndex}>
            <span className="off">{(rowIndex * 16).toString(16).padStart(4, '0')}</span>
            <span>
              {row.map((token, index) => (
                <span key={index} className={isWildcard(token) ? 'wc' : undefined}>
                  {token}
                  {index < row.length - 1 ? ' ' : ''}
                </span>
              ))}
            </span>
          </div>
        ))}
      </div>
      <div className="hexfoot">
        <span>{t('symbols2.bytes', { count: all.length })}</span>
        <span>{t('symbols2.anything', { count: wildcards })}</span>
        <span>{t('symbols2.fixed', { percent: fixed })}</span>
      </div>
    </div>
  )
}
