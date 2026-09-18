/**
 * The primitives that replace Ant Design.
 *
 * Only what the app actually used is here - the 22 components the 18 antd
 * importers between them referenced, and nothing speculative. Anything whose
 * keyboard and screen-reader behaviour is hard to get right (dialog, tabs,
 * tooltip, switch) delegates to Radix; the rest is markup, because a Card that
 * pulls in a component library is a Card that cannot be restyled.
 */
import * as DialogPrimitive from '@radix-ui/react-dialog'
import * as SwitchPrimitive from '@radix-ui/react-switch'
import * as TabsPrimitive from '@radix-ui/react-tabs'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { cn } from './cn'

/* ------------------------------------------------------------------ layout */

/** antd's Card carried its padding in `.ant-card-body`; here it is on the card. */
export function Card({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('rounded-[12px] border border-rule bg-card p-4', className)} {...rest}>
      {children}
    </div>
  )
}

/** antd's Space: a flex row (or column) with a gap. */
export function Space({
  direction = 'horizontal',
  size = 'middle',
  wrap = false,
  align,
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & {
  direction?: 'horizontal' | 'vertical'
  size?: 'small' | 'middle' | 'large'
  wrap?: boolean
  align?: 'start' | 'center' | 'end' | 'baseline'
}) {
  const gap = size === 'small' ? 'gap-2' : size === 'large' ? 'gap-6' : 'gap-3'
  return (
    <div
      className={cn(
        'flex',
        direction === 'vertical' ? 'flex-col' : 'flex-row',
        gap,
        wrap && 'flex-wrap',
        align === 'start' && 'items-start',
        align === 'center' && 'items-center',
        align === 'end' && 'items-end',
        align === 'baseline' && 'items-baseline',
        !align && direction === 'horizontal' && 'items-center',
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  )
}

/* -------------------------------------------------------------- typography */

export function Title({
  level = 2,
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLHeadingElement> & { level?: 1 | 2 | 3 | 4 | 5 }) {
  const Tag = (`h${Math.min(level, 3)}` as 'h1' | 'h2' | 'h3')
  const size =
    level === 1 ? 'text-[30px]' : level === 2 ? 'text-[22px]' : level === 3 ? 'text-[17px]' : 'text-[15px]'
  return (
    <Tag className={cn('font-display font-bold text-ink', size, className)} {...rest}>
      {children}
    </Tag>
  )
}

export function Text({
  type,
  strong,
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLSpanElement> & {
  type?: 'secondary' | 'success' | 'warning' | 'danger'
  strong?: boolean
}) {
  return (
    <span
      className={cn(
        type === 'secondary' && 'text-muted',
        type === 'success' && 'text-ok',
        type === 'warning' && 'text-warn',
        type === 'danger' && 'text-bad',
        strong && 'font-semibold',
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  )
}

export function Paragraph({ className, children, ...rest }: HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p className={cn('m-0 leading-relaxed text-ink-2', className)} {...rest}>
      {children}
    </p>
  )
}

/* ----------------------------------------------------------------- actions */

type ButtonVariant = 'primary' | 'default' | 'text' | 'link'

export function Button({
  variant = 'default',
  size = 'middle',
  block,
  loading,
  icon,
  className,
  children,
  disabled,
  ...rest
}: Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type'> & {
  variant?: ButtonVariant
  size?: 'small' | 'middle' | 'large'
  block?: boolean
  loading?: boolean
  icon?: ReactNode
}) {
  const pad = size === 'small' ? 'px-2.5 py-1 text-[12.5px]' : size === 'large' ? 'px-5 py-2.5 text-[15px]' : 'px-3.5 py-2 text-[13.5px]'
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-[8px] font-medium transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-55',
        pad,
        variant === 'primary' && 'bg-accent text-accent-ink font-semibold hover:brightness-110',
        variant === 'default' && 'border border-rule-strong bg-transparent text-ink hover:bg-card-2',
        variant === 'text' && 'bg-transparent text-ink-2 hover:bg-card-2',
        variant === 'link' && 'bg-transparent p-0 text-[color:var(--accent-text)] hover:underline',
        block && 'w-full',
        className,
      )}
      {...rest}
    >
      {loading ? <Spin size="small" /> : icon}
      {children}
    </button>
  )
}

/* ------------------------------------------------------------------- input */

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'w-full rounded-[8px] border border-rule-strong bg-card-2 px-3 py-2 text-[13.5px] text-ink',
        'placeholder:text-faint focus:border-accent focus:outline-none',
        className,
      )}
      {...rest}
    />
  )
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        'rounded-[8px] border border-rule-strong bg-card-2 px-3 py-2 text-[13.5px] text-ink',
        'focus:border-accent focus:outline-none',
        className,
      )}
      {...rest}
    >
      {children}
    </select>
  )
}

export function Field({
  label,
  htmlFor,
  help,
  className,
  children,
}: {
  label: string
  htmlFor: string
  help?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <label htmlFor={htmlFor} className="text-[12.5px] font-medium text-muted">
        {label}
      </label>
      {children}
      {help ? <span className="text-[12px] text-faint">{help}</span> : null}
    </div>
  )
}

export function Switch({
  checked,
  onCheckedChange,
  label,
}: {
  checked: boolean
  onCheckedChange(next: boolean): void
  label: string
}) {
  return (
    <SwitchPrimitive.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      aria-label={label}
      className={cn(
        'relative h-5 w-9 shrink-0 rounded-full border border-rule-strong transition-colors',
        checked ? 'bg-accent' : 'bg-card-2',
      )}
    >
      <SwitchPrimitive.Thumb
        className={cn(
          'block h-3.5 w-3.5 rounded-full bg-ink transition-transform',
          checked ? 'translate-x-[18px] bg-accent-ink' : 'translate-x-[3px]',
        )}
      />
    </SwitchPrimitive.Root>
  )
}

/* ------------------------------------------------------------------ status */

type Tone = 'neutral' | 'ok' | 'qualify' | 'warn' | 'bad' | 'accent'

const TONE_CLASS: Record<Tone, string> = {
  neutral: 'text-ink-2 bg-card-2 border-rule-strong',
  ok: 'text-ok bg-ok-bg border-ok-line',
  qualify: 'text-qualify bg-qualify-bg border-qualify-line',
  warn: 'text-warn bg-warn-bg border-warn-line',
  bad: 'text-bad bg-bad-bg border-bad-line',
  accent: 'text-[color:var(--accent-text)] bg-accent-2 border-[color:var(--accent-line)]',
}

export function Tag({ tone = 'neutral', className, children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-[5px] border px-2 py-0.5 text-[11.5px] font-semibold',
        TONE_CLASS[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function Dot({ tone = 'neutral', className }: { tone?: Tone; className?: string }) {
  const fill =
    tone === 'ok' ? 'bg-ok' : tone === 'qualify' ? 'bg-qualify' : tone === 'warn' ? 'bg-warn'
      : tone === 'bad' ? 'bg-bad' : tone === 'accent' ? 'bg-accent' : 'bg-faint'
  return <span aria-hidden="true" className={cn('inline-block size-[7px] shrink-0 rounded-full', fill, className)} />
}

export function Alert({
  tone = 'warn',
  title,
  description,
  action,
  className,
}: {
  tone?: Tone
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div
      role="alert"
      className={cn('flex items-start gap-3 rounded-[10px] border px-4 py-3', TONE_CLASS[tone], className)}
    >
      <div className="flex min-w-0 grow flex-col gap-1">
        <span className="text-[13.5px] font-semibold">{title}</span>
        {description ? <span className="text-[12.5px] leading-relaxed text-ink-2">{description}</span> : null}
      </div>
      {action}
    </div>
  )
}

export function Progress({ percent, tone = 'accent', label }: { percent: number; tone?: Tone; label?: string }) {
  const clamped = Math.max(0, Math.min(100, Math.round(percent)))
  const fill =
    tone === 'ok' ? 'bg-ok' : tone === 'bad' ? 'bg-bad' : tone === 'qualify' ? 'bg-qualify' : 'bg-accent'
  return (
    <div
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      className="h-1.5 w-full overflow-hidden rounded-full bg-rule"
    >
      <div className={cn('h-full rounded-full transition-[width]', fill)} style={{ width: `${clamped}%` }} />
    </div>
  )
}

export function Spin({ size = 'middle', label, className }: { size?: 'small' | 'middle' | 'large'; label?: string; className?: string }) {
  const px = size === 'small' ? 'size-3.5' : size === 'large' ? 'size-7' : 'size-5'
  return (
    <span
      role="status"
      aria-label={label ?? 'Loading'}
      className={cn('inline-block animate-spin rounded-full border-2 border-rule-strong border-t-accent', px, className)}
    />
  )
}

export function Skeleton({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div aria-hidden="true" className={cn('flex flex-col gap-2.5', className)}>
      {Array.from({ length: rows }, (_, index) => (
        <span
          key={index}
          className="h-3.5 animate-pulse rounded bg-card-2"
          style={{ width: index === rows - 1 ? '62%' : '100%' }}
        />
      ))}
    </div>
  )
}

export function Empty({ description, children, className }: { description: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col items-center gap-3 px-4 py-10 text-center', className)}>
      <span className="text-[13.5px] text-muted">{description}</span>
      {children}
    </div>
  )
}

/* ------------------------------------------------------------------ tables */

export function Table({ className, children, ...rest }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn('w-full border-collapse text-[13px]', className)} {...rest}>
        {children}
      </table>
    </div>
  )
}

export function Th({ className, children, ...rest }: HTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn(
        'border-b border-rule px-3 py-2.5 text-left text-[11.5px] font-semibold uppercase tracking-wide text-muted',
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  )
}

export function Td({ className, children, ...rest }: HTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={cn('border-b border-rule-soft px-3 py-2.5 align-middle text-ink-2', className)} {...rest}>
      {children}
    </td>
  )
}

/** antd's Descriptions: a label/value grid. */
export function Descriptions({ items, className }: { items: { label: ReactNode; value: ReactNode }[]; className?: string }) {
  return (
    <dl className={cn('m-0 grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-5 gap-y-2.5', className)}>
      {items.map((item, index) => (
        <div key={index} className="contents">
          <dt className="text-[12.5px] text-muted">{item.label}</dt>
          <dd className="m-0 min-w-0 text-[13px] text-ink">{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}

export function List({ items, empty }: { items: ReactNode[]; empty?: ReactNode }) {
  if (items.length === 0) return <Empty description={empty ?? 'Nothing here'} />
  return (
    <ul className="m-0 flex list-none flex-col gap-0 p-0">
      {items.map((item, index) => (
        <li key={index} className="border-b border-rule-soft py-2.5 last:border-b-0">
          {item}
        </li>
      ))}
    </ul>
  )
}

/* ---------------------------------------------------------------- overlays */

export function Drawer({
  open,
  onClose,
  title,
  children,
  width = 520,
}: {
  open: boolean
  onClose(): void
  title: ReactNode
  children: ReactNode
  width?: number
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={(next) => { if (!next) onClose() }}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/55" />
        <DialogPrimitive.Content
          style={{ width: `min(${width}px, 100vw)` }}
          className="fixed inset-y-0 right-0 z-50 flex flex-col gap-4 overflow-y-auto border-l border-rule bg-card p-6 shadow-[var(--shadow)]"
        >
          <div className="flex items-start justify-between gap-4">
            <DialogPrimitive.Title className="m-0 font-display text-[19px] font-bold text-ink">
              {title}
            </DialogPrimitive.Title>
            <DialogPrimitive.Close asChild>
              <Button variant="text" size="small" aria-label="Close">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              </Button>
            </DialogPrimitive.Close>
          </div>
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

export function Tooltip({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <TooltipPrimitive.Provider delayDuration={200}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            sideOffset={6}
            className="z-50 rounded-[7px] border border-rule-strong bg-card-2 px-2.5 py-1.5 text-[12.5px] text-ink shadow-[var(--tooltip-shadow)]"
          >
            {title}
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  )
}

export function Tabs({
  value,
  onValueChange,
  items,
}: {
  value: string
  onValueChange(next: string): void
  items: { key: string; label: ReactNode; children: ReactNode }[]
}) {
  return (
    <TabsPrimitive.Root value={value} onValueChange={onValueChange} className="flex min-h-0 flex-col gap-4">
      <TabsPrimitive.List className="flex gap-5 border-b border-rule">
        {items.map((item) => (
          <TabsPrimitive.Trigger
            key={item.key}
            value={item.key}
            className={cn(
              '-mb-px border-b-2 border-transparent pb-2.5 text-[13.5px] font-medium text-muted',
              'data-[state=active]:border-accent data-[state=active]:font-semibold data-[state=active]:text-ink',
            )}
          >
            {item.label}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
      {items.map((item) => (
        <TabsPrimitive.Content key={item.key} value={item.key} className="min-h-0">
          {item.children}
        </TabsPrimitive.Content>
      ))}
    </TabsPrimitive.Root>
  )
}
