import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { buttonClass } from '../../ui/buttonStyle'
import { DownloadIcon } from '../../ui/icons'
import { Alert, Button, Input, Spin, Tag } from '../../ui/primitives'
import { LinkRow } from './KeepUpdated'
import {
  deleteStoredFile, forgetLocalFile, getStoredFile, manageLink, readLink, readLocalFiles, tokenFromHash,
  updateStoredFile, type StoredFile, type StoredHistory,
} from './userFiles'

function when(seconds: number | null | undefined, locale: string): string {
  return seconds ? new Date(seconds * 1000).toLocaleString(locale) : '—'
}

function short(value: string | number): string {
  const text = String(value)
  return text.length > 48 ? `${text.slice(0, 45)}…` : text
}

function HistoryEntry({ entry }: { entry: StoredHistory }) {
  const { t, i18n } = useTranslation()
  return (
    <li className="myhist">
      <div className="flex flex-wrap items-center gap-2">
        <strong className="font-mono text-[13.5px] text-ink">{t('myfile.build', { build: entry.build })}</strong>
        <span className="text-[12px] text-muted-foreground">{when(entry.at, i18n.language)}</span>
        {entry.event === 'replaced' ? (
          <Tag tone="neutral">{t('myfile.replaced')}</Tag>
        ) : (
          <>
            <Tag tone="ok">{t('myfile.changed', { count: entry.changes.length })}</Tag>
            {entry.unresolved.length > 0 && <Tag tone="warn">{t('myfile.unresolved', { count: entry.unresolved.length })}</Tag>}
          </>
        )}
      </div>
      {entry.changes.length > 0 && (
        <ul className="mylist">
          {entry.changes.map((change) => (
            <li key={`${change.key}.${change.platform}`}>
              <span className="font-mono text-ink">{change.key}</span> <Tag tone="neutral">{change.platform}</Tag>{' '}
              <span className="font-mono text-[12px] text-ink-2">{short(change.from)} → {short(change.to)}</span>
              <div className="text-[12px] text-muted-foreground">{change.how}</div>
            </li>
          ))}
        </ul>
      )}
      {entry.unresolved.length > 0 && (
        <ul className="mylist">
          {entry.unresolved.map((row) => (
            <li key={`${row.key}.${row.platform}`}>
              <span className="font-mono text-ink">{row.key}</span> <Tag tone="warn">{row.platform}</Tag>
              <div className="text-[12px] text-muted-foreground">{row.why}</div>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

function Managed({ token, onGone }: { token: string; onGone(): void }) {
  const { t, i18n } = useTranslation()
  const client = useQueryClient()
  const key = ['stored-file', token]
  const { data, error, isPending } = useQuery({ queryKey: key, queryFn: () => getStoredFile(token), retry: false })
  const [webhook, setWebhook] = useState('')
  const [confirm, setConfirm] = useState(false)
  const update = useMutation({
    mutationFn: (change: Parameters<typeof updateStoredFile>[1]) => updateStoredFile(token, change),
    onSuccess: (next: StoredFile) => client.setQueryData(key, next),
  })
  const remove = useMutation({
    mutationFn: () => deleteStoredFile(token),
    onSuccess: () => {
      forgetLocalFile(token)
      onGone()
    },
  })

  if (isPending) return <Spin label={t('myfile.loading')} />
  if (error || !data) {
    return <Alert tone="bad" title={t('myfile.notFound')} description={(error as Error | null)?.message} />
  }
  const url = readLink(data.url)
  const history = [...data.history].reverse()

  return (
    <div className="flex flex-col gap-5">
      <section className="panel myfacts">
        <header><h2>{data.filename}</h2></header>
        <div className="flex flex-col gap-3 p-4">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-[13px] text-ink-2">
            <span>{t('myfile.upToDate', { build: data.baseline_build ?? '—' })}</span>
            <span>{t('myfile.created', { at: when(data.created, i18n.language) })}</span>
            <span>{t('myfile.lastFetch', { at: when(data.last_fetch, i18n.language) })}</span>
          </div>
          <LinkRow label={t('myfile.readLink')} value={url} />
          <LinkRow label={t('myfile.curl')} value={`curl -fsSL -o ${data.filename} ${url}`} />
          <LinkRow label={t('myfile.manageLink')} value={manageLink(token)} secret />
          <p className="text-[12.5px] text-ink-2">{t('myfile.expiry')}</p>
        </div>
      </section>

      <section className="panel">
        <header><h2>{t('myfile.historyH')}</h2></header>
        <div className="p-4">
          {history.length ? <ul className="flex flex-col gap-4">{history.map((entry) => <HistoryEntry key={`${entry.build}.${entry.at}`} entry={entry} />)}</ul>
            : <p className="text-[13px] text-ink-2">{t('myfile.noHistory')}</p>}
        </div>
      </section>

      <section className="panel">
        <header><h2>{t('myfile.changeH')}</h2></header>
        <div className="flex flex-col gap-4 p-4">
          <div className="flex flex-wrap gap-2">
            <Button
              icon={<DownloadIcon size={13} />}
              onClick={() => {
                const blob = new Blob([data.current], { type: 'text/plain' })
                const link = document.createElement('a')
                link.href = URL.createObjectURL(blob)
                link.download = data.filename
                link.click()
                URL.revokeObjectURL(link.href)
              }}
            >
              {t('myfile.download')}
            </Button>
            <label className={buttonClass('default')}>
              {t('myfile.replace')}
              <input
                type="file"
                hidden
                onChange={(event) => {
                  const picked = event.target.files?.[0]
                  event.target.value = ''
                  if (picked) void picked.text().then((text) => update.mutate({ gamedata: text, filename: picked.name }))
                }}
              />
            </label>
          </div>
          <p className="text-[12.5px] text-ink-2">{t('myfile.replaceNote')}</p>
          <label className="flex flex-col gap-1 text-[12px] text-muted-foreground">
            {data.webhook ? t('myfile.webhookSet') : t('myfile.webhook')}
            <span className="flex gap-2">
              <Input value={webhook} placeholder="https://discord.com/api/webhooks/…" onChange={(event) => setWebhook(event.target.value)} />
              <Button loading={update.isPending} disabled={!webhook.trim()} onClick={() => update.mutate({ webhook: webhook.trim() })}>
                {t('myfile.save')}
              </Button>
              {data.webhook && (
                <Button variant="text" onClick={() => update.mutate({ webhook: null })}>{t('myfile.webhookOff')}</Button>
              )}
            </span>
          </label>
          {update.error && <Alert tone="bad" title={(update.error as Error).message} />}
        </div>
      </section>

      <section className="panel">
        <header><h2>{t('myfile.deleteH')}</h2></header>
        <div className="flex flex-col gap-3 p-4">
          <p className="text-[12.5px] text-ink-2">{t('myfile.deleteNote')}</p>
          {!confirm ? (
            <Button className="self-start" onClick={() => setConfirm(true)}>{t('myfile.delete')}</Button>
          ) : (
            <span className="flex flex-wrap gap-2">
              <Button variant="primary" className="bg-bad text-white hover:bg-bad/90" loading={remove.isPending} onClick={() => remove.mutate()}>
                {t('myfile.deleteConfirm')}
              </Button>
              <Button variant="text" onClick={() => setConfirm(false)}>{t('myfile.cancel')}</Button>
            </span>
          )}
          {remove.error && <Alert tone="bad" title={(remove.error as Error).message} />}
        </div>
      </section>
    </div>
  )
}

/**
 * /my-file#<manage token>: one stored file's history, links, replace, webhook and delete.
 * Without a token in the fragment it lists the files this browser stored.
 */
export function MyFilePage() {
  const { t } = useTranslation()
  const [token, setToken] = useState<string | null>(() => tokenFromHash(window.location.hash))
  const [gone, setGone] = useState(false)
  const [local, setLocal] = useState(readLocalFiles)

  useEffect(() => {
    const onHash = () => setToken(tokenFromHash(window.location.hash))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  return (
    <div className="myfile flex flex-col gap-5">
      <div>
        <h1 className="font-display text-[26px] font-bold text-ink">{t('myfile.h1')}</h1>
        <p className="text-[14px] text-ink-2">{t('myfile.lede')}</p>
      </div>
      {gone && <Alert tone="ok" title={t('myfile.deleted')} />}
      {token && !gone ? (
        <Managed
          key={token}
          token={token}
          onGone={() => {
            setGone(true)
            setLocal(readLocalFiles())
            history.replaceState(null, '', window.location.pathname)
            setToken(null)
          }}
        />
      ) : (
        <section className="panel">
          <header><h2>{t('myfile.localH')}</h2></header>
          <div className="flex flex-col gap-2 p-4">
            {local.length ? local.map((row) => (
              <a key={row.token} className="font-mono text-[13.5px]" href={`#${row.token}`}>
                {row.filename} <span className="text-[12px] text-muted-foreground">{new Date(row.created).toLocaleDateString()}</span>
              </a>
            )) : <p className="text-[13px] text-ink-2">{t('myfile.noLocal')}</p>}
          </div>
        </section>
      )}
    </div>
  )
}

export default MyFilePage
