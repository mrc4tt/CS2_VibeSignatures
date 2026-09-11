import { useQuery } from '@tanstack/react-query'
import { Alert, Select, Skeleton } from 'antd'
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Explain } from '../../components/Explain'
import { getGameSymbolDataset, getGameSymbolIndex, getGameSymbolLightDataset } from './data'
import { filterEntries, pivotRecords, verdictOf, type SymbolFilters } from './pivot'
import { SymbolCard } from './SymbolCard'

const PAGE = 12

export function FindSymbolPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const [limit, setLimit] = useState(PAGE)
  const listRef = useRef<HTMLDivElement>(null)

  const query = params.get('q') ?? ''
  const module = params.get('module') ?? undefined
  const state = (params.get('state') as SymbolFilters['state']) ?? 'all'
  // Memoised so the filter object is stable between renders; an inline literal
  // makes every useMemo below recompute on every keystroke.
  const filters = useMemo<SymbolFilters>(() => ({ query, module, state }), [query, module, state])
  const openKey = params.get('symbol') ?? undefined
  const deferredQuery = useDeferredValue(query)

  const setParam = useCallback((key: string, value?: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }, [params, setParams])

  const indexQuery = useQuery({
    queryKey: ['gamesymbols', 'index'],
    queryFn: ({ signal }) => getGameSymbolIndex(signal),
    staleTime: 5 * 60 * 1000,
  })
  const version = params.get('build') ?? indexQuery.data?.versions[0]?.gameVersion
  const entry = indexQuery.data?.versions.find((candidate) => candidate.gameVersion === version)

  // The companion arrives first and carries names, modules, kinds and aliases:
  // enough for the whole list. The full snapshot follows and is what a card
  // needs once it is opened.
  const lightQuery = useQuery({
    queryKey: ['gamesymbols', 'light', version, entry?.light?.url],
    queryFn: ({ signal }) => getGameSymbolLightDataset(entry!, signal),
    enabled: Boolean(entry),
    staleTime: Infinity,
  })
  const fullQuery = useQuery({
    queryKey: ['gamesymbols', version, entry?.url],
    queryFn: ({ signal }) => getGameSymbolDataset(entry!, signal),
    enabled: Boolean(entry),
    staleTime: Infinity,
  })
  const dataset = fullQuery.data ?? lightQuery.data

  const entries = useMemo(() => (dataset ? pivotRecords(dataset.records) : []), [dataset])
  const detailed = useMemo(() => (fullQuery.data ? pivotRecords(fullQuery.data.records) : []), [fullQuery.data])
  const detailedByKey = useMemo(() => new Map(detailed.map((item) => [item.key, item])), [detailed])

  const pool = useMemo(
    () => filterEntries(entries, { query: deferredQuery, module }),
    [entries, deferredQuery, module],
  )
  const visible = useMemo(
    () => filterEntries(entries, { ...filters, query: deferredQuery }),
    [entries, filters, deferredQuery],
  )

  useEffect(() => setLimit(PAGE), [deferredQuery, module, state])

  const counts = useMemo(() => ({
    all: pool.length,
    onePlatform: pool.filter((item) => verdictOf(item) === 'onePlatform').length,
    caveat: pool.filter((item) => verdictOf(item) === 'caveat').length,
  }), [pool])

  const modules = useMemo(
    () => [...new Set(entries.map((item) => item.module))].sort(),
    [entries],
  )

  function moveFocus(direction: 1 | -1): boolean {
    const cards = [...(listRef.current?.querySelectorAll<HTMLElement>('.rescard') ?? [])]
    if (cards.length === 0) return false
    const active = document.activeElement as HTMLElement | null
    const at = cards.findIndex((card) => card === active || card.contains(active))
    const index = at < 0 ? (direction > 0 ? 0 : cards.length - 1) : Math.min(cards.length - 1, Math.max(0, at + direction))
    cards[index]?.focus()
    cards[index]?.scrollIntoView({ block: 'nearest' })
    return true
  }

  return (
    <div className="handbook" onKeyDown={(event) => {
      if (event.key === 'ArrowDown' && moveFocus(1)) event.preventDefault()
      if (event.key === 'ArrowUp' && moveFocus(-1)) event.preventDefault()
    }}>
      <div className="hero">
        <h1>{t('symbols2.h1')}</h1>
        <p className="lede">{t('symbols2.lede')}</p>
      </div>
      <Explain html={t('symbols2.explain')} />

      <div className="finder">
        <label className="bigsearch">
          <span className="mag" aria-hidden="true">⌕</span>
          <input
            type="search"
            value={filters.query}
            placeholder={t('symbols2.placeholder')}
            aria-label={t('symbols2.h1')}
            onChange={(event) => setParam('q', event.target.value)}
          />
        </label>

        <div className="filters">
          {(['all', 'caveat', 'onePlatform'] as const).map((state) => (
            <button
              key={state}
              type="button"
              className="chip"
              aria-pressed={filters.state === state}
              onClick={() => setParam('state', state === 'all' ? undefined : state)}
            >
              {t(`symbols2.filter.${state}`)}
              <span className="n">{counts[state]}</span>
            </button>
          ))}
          <span className="fsep" />
          <Select
            allowClear
            showSearch
            size="small"
            style={{ minWidth: 150 }}
            placeholder={t('symbols.allModules')}
            value={filters.module}
            onChange={(value?: string) => setParam('module', value)}
            options={modules.map((module) => ({ value: module, label: module }))}
          />
          {version && indexQuery.data && (
            <Select
              size="small"
              style={{ minWidth: 110 }}
              value={version}
              onChange={(value: string) => setParam('build', value)}
              options={indexQuery.data.versions.map((item) => ({ value: item.gameVersion, label: item.gameVersion }))}
            />
          )}
        </div>

        <div className="resultline" role="status" aria-live="polite">
          {dataset && <span>{t('symbols2.shown', { count: visible.length, total: entries.length })}</span>}
          {dataset && <span>{t('symbols2.hint')}</span>}
        </div>
      </div>

      {indexQuery.error && <Alert type="error" showIcon message={t('symbols.indexError')} description={indexQuery.error.message} />}
      {lightQuery.error && fullQuery.error && (
        <Alert type="error" showIcon message={t('symbols.datasetError')} description={fullQuery.error.message} />
      )}

      {!dataset && (
        <div className="results" aria-busy="true">
          {[0, 1, 2].map((row) => (
            <div className="rescard" key={row}><Skeleton active paragraph={{ rows: 3 }} title={false} /></div>
          ))}
        </div>
      )}

      {dataset && (
        <div className="results" ref={listRef}>
          {visible.slice(0, limit).map((item) => (
            <SymbolCard
              key={item.key}
              entry={detailedByKey.get(item.key) ?? item}
              gameVersion={version ?? ''}
              open={openKey === item.key}
              detailReady={detailedByKey.has(item.key)}
              onToggle={(key) => setParam('symbol', openKey === key ? undefined : key)}
            />
          ))}
          {visible.length === 0 && (
            <div className="blank">
              <div className="big">◆</div>
              <p>{t('symbols2.none', { query: filters.query })}<br />{t('symbols2.noneHint')}</p>
            </div>
          )}
          {visible.length > limit && (
            <button type="button" className="btn morebtn" onClick={() => setLimit(limit + PAGE)}>
              {t('symbols2.showMore', { count: Math.min(PAGE, visible.length - limit), total: visible.length })}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
