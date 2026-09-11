import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getSiteHistory } from '../api/siteData'
import { requestNavigation } from '../app/navigate'
import { getGameDataIndex } from '../features/gamedata/data'
import { getGameSymbolIndex, getGameSymbolLightDataset } from '../features/symbols/data'

interface Hit {
  group: 'symbols' | 'keys' | 'files'
  title: string
  detail: string
  go(): void
}

const LIMIT = 40

/**
 * One search across everything the site holds. Finding out which plugin key
 * ships a symbol used to mean switching page and searching again by hand.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose(): void }) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const symbolIndexQuery = useQuery({
    queryKey: ['gamesymbols', 'index'],
    queryFn: ({ signal }) => getGameSymbolIndex(signal),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  })
  const newest = symbolIndexQuery.data?.versions[0]
  const lightQuery = useQuery({
    queryKey: ['gamesymbols', 'light', newest?.gameVersion, newest?.light?.url],
    queryFn: ({ signal }) => getGameSymbolLightDataset(newest!, signal),
    enabled: open && Boolean(newest),
    staleTime: Infinity,
  })
  const gamedataQuery = useQuery({
    queryKey: ['gamedata', 'index'],
    queryFn: ({ signal }) => getGameDataIndex(signal),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  })
  const historyQuery = useQuery({
    queryKey: ['history'],
    queryFn: ({ signal }) => getSiteHistory(signal),
    enabled: open,
    staleTime: Infinity,
  })

  useEffect(() => {
    if (open) {
      setSelected(0)
      inputRef.current?.focus()
    }
  }, [open])

  const hits = useMemo<Hit[]>(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return []
    const found: Hit[] = []

    const seen = new Set<string>()
    for (const record of lightQuery.data?.records ?? []) {
      const key = `${record.module}/${record.artifact}`
      if (seen.has(key)) continue
      if (!`${record.symbolName} ${record.module}`.toLowerCase().includes(needle)) continue
      seen.add(key)
      found.push({
        group: 'symbols',
        title: record.symbolName,
        detail: record.module,
        go: () => requestNavigation({ view: 'symbols', params: { symbol: key } }),
      })
      if (found.length > LIMIT * 2) break
    }

    const files = gamedataQuery.data?.versions[0]?.files ?? []
    const history = historyQuery.data
    if (history) {
      for (const [file, keys] of Object.entries(history.files)) {
        for (const name of Object.keys(keys)) {
          if (!name.toLowerCase().includes(needle)) continue
          found.push({
            group: 'keys',
            title: name,
            detail: file,
            go: () => requestNavigation({ view: 'gamedata', params: { file, find: name } }),
          })
          if (found.length > LIMIT * 3) break
        }
      }
    }

    for (const file of files) {
      if (!`${file.plugin} ${file.fileName}`.toLowerCase().includes(needle)) continue
      found.push({
        group: 'files',
        title: `${file.plugin} / ${file.fileName}`,
        detail: file.metadata ? `${file.metadata.summary.covered}/${file.metadata.summary.total}` : '',
        go: () => requestNavigation({ view: 'gamedata', params: { file: file.id } }),
      })
    }

    const order = { symbols: 0, keys: 1, files: 2 }
    return found
      .sort((left, right) => order[left.group] - order[right.group] || left.title.length - right.title.length)
      .slice(0, LIMIT)
  }, [query, lightQuery.data, gamedataQuery.data, historyQuery.data])

  if (!open) return null

  let lastGroup: Hit['group'] | undefined

  return (
    <div
      className="mask"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="qf" role="dialog" aria-modal="true" aria-label={t('palette.label')}>
        <input
          ref={inputRef}
          type="search"
          value={query}
          autoComplete="off"
          placeholder={t('palette.placeholder')}
          aria-label={t('palette.label')}
          onChange={(event) => { setQuery(event.target.value); setSelected(0) }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') onClose()
            if (event.key === 'ArrowDown') {
              event.preventDefault()
              setSelected(Math.min(selected + 1, hits.length - 1))
            }
            if (event.key === 'ArrowUp') {
              event.preventDefault()
              setSelected(Math.max(selected - 1, 0))
            }
            if (event.key === 'Enter' && hits[selected]) {
              event.preventDefault()
              hits[selected].go()
              onClose()
            }
          }}
        />
        <div className="qfres">
          {!query.trim() && <div className="blank">{t('palette.hint')}</div>}
          {query.trim() && hits.length === 0 && (
            <div className="blank">{t('palette.none', { query })}</div>
          )}
          {hits.map((hit, index) => {
            const header = hit.group !== lastGroup ? hit.group : undefined
            lastGroup = hit.group
            return (
              <div key={`${hit.group}-${hit.title}-${index}`}>
                {header && <div className="qfg">{t(`palette.group.${header}`)}</div>}
                <button
                  type="button"
                  className="qfr"
                  aria-selected={index === selected}
                  onMouseEnter={() => setSelected(index)}
                  onClick={() => { hit.go(); onClose() }}
                >
                  <span className="t">{hit.title}</span>
                  <span className="w">{hit.detail}</span>
                </button>
              </div>
            )
          })}
        </div>
        <div className="qff">
          <span><kbd>↑</kbd><kbd>↓</kbd> {t('palette.move')}</span>
          <span><kbd>Enter</kbd> {t('palette.open')}</span>
          <span><kbd>Esc</kbd> {t('palette.close')}</span>
        </div>
      </div>
    </div>
  )
}
