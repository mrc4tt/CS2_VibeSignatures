import { useQuery } from '@tanstack/react-query'
import { useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { getSiteHistory } from '../api/siteData'
import { requestNavigation } from '../app/navigate'
import { getGameDataIndex } from '../features/gamedata/data'
import { getGameSymbolIndex, getGameSymbolLightDataset } from '../features/symbols/data'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '../ui/shadcn/command'
import { Dialog, DialogContent, DialogTitle } from '../ui/shadcn/dialog'

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

  const groups = (['symbols', 'keys', 'files'] as const)
    .map((group) => ({ group, hits: hits.filter((hit) => hit.group === group) }))
    .filter(({ hits: groupHits }) => groupHits.length > 0)
  const needle = query.trim()

  // cmdk owns the keyboard (arrows, Enter, the selected row) and Radix Dialog
  // owns the modal part (focus trap, Esc, focus back to the opener, scroll lock).
  // shouldFilter is off because the hits above are already filtered, ranked
  // and capped - cmdk's own fuzzy filter would re-rank them.
  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onClose() }}>
      <DialogContent
        showCloseButton={false}
        aria-describedby={undefined}
        className="top-[8vh] w-[min(680px,calc(100%-2rem))] max-w-none translate-y-0 gap-0 overflow-hidden rounded-[10px] border-rule bg-card p-0 shadow-[0_34px_90px_-34px_rgba(0,0,0,0.6)] sm:max-w-none"
      >
        <DialogTitle className="sr-only">{t('palette.label')}</DialogTitle>
        <Command shouldFilter={false} loop className="rounded-none bg-card text-ink **:data-[slot=command-input-wrapper]:h-auto **:data-[slot=command-input-wrapper]:border-rule **:data-[slot=command-input-wrapper]:px-[18px]">
          <CommandInput
            value={query}
            onValueChange={setQuery}
            placeholder={t('palette.placeholder')}
            aria-label={t('palette.label')}
            // outline-none!: index.css draws a :focus-visible ring on every focused
            // element, unlayered, so it beats a plain utility. The caret is focus enough.
            className="h-auto py-4 font-mono text-[16px] text-ink outline-none! placeholder:text-faint"
          />
          <CommandList className="max-h-[min(54vh,440px)]">
            {!needle && <div className="px-5 py-10 text-center text-[14px] text-muted-foreground">{t('palette.hint')}</div>}
            {needle && (
              <CommandEmpty className="px-5 py-10 text-center text-[14px] text-muted-foreground">
                {t('palette.none', { query })}
              </CommandEmpty>
            )}
            {groups.map(({ group, hits: groupHits }) => (
              <CommandGroup key={group} heading={t(`palette.group.${group}`)} className={GROUP_CLASS}>
                {groupHits.map((hit, index) => (
                  <CommandItem
                    key={`${hit.title}-${index}`}
                    value={`${group}:${index}`}
                    onSelect={() => { hit.go(); onClose() }}
                    className="cursor-pointer items-baseline gap-[11px] rounded-none border-b border-rule-soft px-[18px] py-[9px] data-[selected=true]:bg-accent-2"
                  >
                    <span className="flex-auto font-mono text-[13.5px] [overflow-wrap:anywhere] text-ink">{hit.title}</span>
                    <span className="font-mono text-[11px] text-muted-foreground">{hit.detail}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
          <div className="flex flex-wrap gap-3.5 border-t border-rule bg-card-2 px-[18px] py-[9px] text-[11.5px] text-faint">
            <span><Key>↑</Key><Key>↓</Key> {t('palette.move')}</span>
            <span><Key>Enter</Key> {t('palette.open')}</span>
            <span><Key>Esc</Key> {t('palette.close')}</span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  )
}

/** Sticky group headings, in the small-caps style the palette had before cmdk. */
const GROUP_CLASS = [
  'p-0',
  '[&_[cmdk-group-heading]]:sticky [&_[cmdk-group-heading]]:top-0 [&_[cmdk-group-heading]]:z-10',
  '[&_[cmdk-group-heading]]:border-b [&_[cmdk-group-heading]]:border-rule-soft [&_[cmdk-group-heading]]:bg-card-2',
  '[&_[cmdk-group-heading]]:px-[18px] [&_[cmdk-group-heading]]:pt-[7px] [&_[cmdk-group-heading]]:pb-[6px]',
  '[&_[cmdk-group-heading]]:text-[10.5px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase',
  '[&_[cmdk-group-heading]]:tracking-[0.08em] [&_[cmdk-group-heading]]:text-faint',
].join(' ')

function Key({ children }: { children: ReactNode }) {
  return <kbd className="mr-0.5 rounded-[3px] border border-rule px-1 font-mono">{children}</kbd>
}
