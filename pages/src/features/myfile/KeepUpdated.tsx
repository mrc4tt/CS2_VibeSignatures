import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { copyText } from '../../ui/clipboard'
import { CopyIcon } from '../../ui/icons'
import { Alert, Button, Input } from '../../ui/primitives'
import { manageLink, readLink, rememberLocalFile, storeFile, type CreatedFile } from './userFiles'

/** One link with a copy button: what a server owner pastes somewhere else. */
export function LinkRow({ label, value, secret }: { label: string; value: string; secret?: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[12px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="flex min-w-0 items-center gap-2">
        <code className={`linkrow min-w-0 grow truncate${secret ? ' secret' : ''}`} title={value}>{value}</code>
        <Button
          size="small"
          aria-label={t('myfile.copy', { what: label })}
          onClick={() => void copyText(value, { ok: t('myfile.copied'), failed: t('myfile.copyFailed') })}
        >
          <CopyIcon size={13} />
        </Button>
      </span>
    </div>
  )
}

interface Props {
  /** The text to keep: the fixed copy when the scan offered one, else the file as loaded. */
  text: string
  filename: string
  /** The build the text is right for: the scanned build, so the next update starts from it. */
  build?: string
  /** True when `text` is the fixed copy, not what was loaded. */
  fixed: boolean
}

/**
 * "Keep this file updated": store the file on the scan server and get two links.
 * Sending the file is a choice, so nothing leaves the browser until the button.
 */
export function KeepUpdated({ text, filename, build, fixed }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [webhook, setWebhook] = useState('')
  const store = useMutation({
    mutationFn: () => storeFile(text, filename, build, webhook.trim() || undefined),
    onSuccess: (made: CreatedFile) => rememberLocalFile({ token: made.manage, filename: made.filename, created: Date.now() }),
  })
  const made = store.data

  if (made) {
    const url = readLink(made.url)
    return (
      <section className="keepup flex flex-col gap-3" aria-live="polite">
        <strong className="text-[14px] text-ink">{t('myfile.keep.done')}</strong>
        <LinkRow label={t('myfile.readLink')} value={url} />
        <LinkRow label={t('myfile.curl')} value={`curl -fsSL -o ${made.filename} ${url}`} />
        <LinkRow label={t('myfile.manageLink')} value={manageLink(made.manage)} secret />
        <p className="text-[12.5px] leading-relaxed text-ink-2">{t('myfile.keep.secret')}</p>
      </section>
    )
  }

  return (
    <section className="keepup flex flex-col gap-2.5">
      <strong className="text-[14px] text-ink">{t('myfile.keep.h')}</strong>
      <p className="text-[12.5px] leading-relaxed text-ink-2">{t('myfile.keep.lede')}</p>
      {!open ? (
        <Button onClick={() => setOpen(true)}>{t('myfile.keep.start')}</Button>
      ) : (
        <>
          <p className="text-[12.5px] leading-relaxed text-ink-2">
            {fixed ? t('myfile.keep.whatFixed') : t('myfile.keep.what')} {t('myfile.keep.privacy')}
          </p>
          <label className="flex flex-col gap-1 text-[12px] text-muted-foreground">
            {t('myfile.webhook')}
            <Input
              value={webhook}
              placeholder="https://discord.com/api/webhooks/…"
              onChange={(event) => setWebhook(event.target.value)}
            />
          </label>
          {store.error && <Alert tone="bad" title={(store.error as Error).message} />}
          <Button variant="primary" loading={store.isPending} onClick={() => store.mutate()}>
            {t('myfile.keep.store')}
          </Button>
        </>
      )}
    </section>
  )
}
