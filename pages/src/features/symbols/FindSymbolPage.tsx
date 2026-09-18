import { useQuery } from '@tanstack/react-query'
import { Alert, Select, Skeleton } from '../../ui/primitives'
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getSiteDiagnostics, getSiteHistory } from '../../api/siteData'
import { Explain } from '../../components/Explain'
import { getGameSymbolDataset, getGameSymbolIndex, getGameSymbolLightDataset } from './data'
import { filterEntries, pivotRecords, verdictOf, type SymbolFilters } from './pivot'
import { SymbolCard } from './SymbolCard'
import { SymbolRow } from './SymbolRow'

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

  // `push` for opening or closing a card, so the back button closes it again;
  // `replace` while typing, which would otherwise add one entry per keystroke.
  const setParam = useCallback((key: string, value?: string, push = false) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: !push })
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

  // Optional companions: a build published before they existed simply has none,
  // and the panels they feed disappear rather than erroring.
  const diagnosticsQuery = useQuery({
    queryKey: ['diagnostics', version],
    queryFn: ({ signal }) => getSiteDiagnostics(version!, signal),
    enabled: Boolean(version),
    staleTime: Infinity,
  })
  const historyQuery = useQuery({
    queryKey: ['history'],
    queryFn: ({ signal }) => getSiteHistory(signal),
    staleTime: Infinity,
  })
  const warningsBySymbol = diagnosticsQuery.data?.validator.bySymbol
  const symbolToKeys = historyQuery.data?.symbolToKeys

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
          <label htmlFor="symbol-module" className="sr-only">{t('symbols.allModules')}</label>
          <Select
            id="symbol-module"
            className="min-w-[150px] px-2 py-1 text-[12.5px]"
            value={filters.module ?? ''}
            onChange={(event) => setParam('module', event.target.value || undefined)}
          >
            <option value="">{t('symbols.allModules')}</option>
            {modules.map((module) => <option key={module} value={module}>{module}</option>)}
          </Select>
          {version && indexQuery.data && (
            <>
              <label htmlFor="symbol-build" className="sr-only">{t('symbols.build')}</label>
              <Select
                id="symbol-build"
                className="min-w-[110px] px-2 py-1 font-mono text-[12.5px]"
                value={version}
                onChange={(event) => setParam('build', event.target.value)}
              >
                {indexQuery.data.versions.map((item) => (
                  <option key={item.gameVersion} value={item.gameVersion}>{item.gameVersion}</option>
                ))}
              </Select>
            </>
          )}
        </div>

        <div className="resultline" role="status" aria-live="polite">
          {dataset && <span>{t('symbols2.shown', { count: visible.length, total: entries.length })}</span>}
          {dataset && <span>{t('symbols2.hint')}</span>}
        </div>
      </div>

      {indexQuery.error && <Alert tone="bad" title={t('symbols.indexError')} description={indexQuery.error.message} />}
      {lightQuery.error && fullQuery.error && (
        <Alert tone="bad" title={t('symbols.datasetError')} description={fullQuery.error.message} />
      )}

      {!dataset && (
        <div className="results" aria-busy="true">
          {[0, 1, 2].map((row) => (
            <div className="rescard" key={row}><Skeleton rows={3} /></div>
          ))}
        </div>
      )}

      {dataset && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,400px)_minmax(0,1fr)] lg:items-start">
          {/*
            Master-detail rather than a column of expanders: with 2,008 entries
            the list is for scanning and the detail is for reading, and one
            column made you lose your place in the list every time you opened
            something. Below lg the grid collapses, list first, detail under it.
          */}
          <div className="results flex flex-col gap-1.5 lg:max-h-[calc(100vh-260px)] lg:overflow-y-auto lg:pr-1" ref={listRef}>
            {visible.slice(0, limit).map((item) => (
              <SymbolRow
                key={item.key}
                entry={item}
                selected={openKey === item.key}
                onSelect={(key) => setParam('symbol', key, true)}
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

          {/* Detail pane: the selected symbol, or the first result so the pane
              is never an empty box on arrival. */}
          <div className="lg:sticky lg:top-6">
            {(() => {
              const selected = visible.find((item) => item.key === openKey) ?? visible[0]
              if (!selected) return null
              return (
                <SymbolCard
                  entry={detailedByKey.get(selected.key) ?? selected}
                  gameVersion={version ?? ''}
                  warnings={warningsBySymbol?.[selected.key]}
                  shippedBy={symbolToKeys?.[selected.key]}
                  open
                  detailReady={detailedByKey.has(selected.key)}
                  onToggle={() => undefined}
                />
              )
            })()}
          </div>
        </div>
      )}
    </div>
  )
}
