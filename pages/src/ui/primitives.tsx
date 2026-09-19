/**
 * The primitives that replace Ant Design.
 *
 * Only what the app actually used is here - the 22 components the 18 antd
 * importers between them referenced, and nothing speculative.
 *
 * Where shadcn/ui has the same component, the primitive is a thin wrapper over
 * the generated one in ./shadcn: the antd-shaped API stays (so no call site
 * changes), and the wrapper translates it - variant and size names, `tone` -
 * and restates only what is this site's own look (the tone colours, the
 * underlined tabs, the drawer width). The rest is plain markup, because shadcn
 * has no counterpart for it or its counterpart would only change the spacing.
 */
import { cva } from 'class-variance-authority'
import { XIcon } from 'lucide-react'
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { cn } from './cn'
import { Alert as AlertRoot, AlertDescription, AlertTitle } from './shadcn/alert'
import { Badge } from './shadcn/badge'
import { Button as ShadcnButton } from './shadcn/button'
import { NativeSelect } from './shadcn/native-select'
import { Sheet, SheetClose, SheetContent, SheetTitle } from './shadcn/sheet'
import { Spinner } from './shadcn/spinner'
import { Switch as ShadcnSwitch } from './shadcn/switch'
import { Tabs as TabsRoot, TabsContent, TabsList, TabsTrigger } from './shadcn/tabs'
import { Toggle } from './shadcn/toggle'
import { ToggleGroup, ToggleGroupItem } from './shadcn/toggle-group'
import { Tooltip as TooltipRoot, TooltipContent, TooltipProvider, TooltipTrigger } from './shadcn/tooltip'

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
        type === 'secondary' && 'text-muted-foreground',
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
type ButtonSize = 'small' | 'middle' | 'large'

const BUTTON_VARIANT = { primary: 'default', default: 'outline', text: 'ghost', link: 'link' } as const
const BUTTON_SIZE = { small: 'sm', middle: 'default', large: 'lg' } as const
/** shadcn sizes by height and text-sm; this site's three sizes each have their own type size. */
const BUTTON_TEXT: Record<ButtonSize, string> = {
  small: 'h-7 px-2.5 text-[12.5px]',
  middle: 'px-3.5 text-[13.5px]',
  large: 'px-5 text-[15px]',
}

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
  size?: ButtonSize
  block?: boolean
  loading?: boolean
  icon?: ReactNode
}) {
  return (
    <ShadcnButton
      type="button"
      variant={BUTTON_VARIANT[variant]}
      size={BUTTON_SIZE[size]}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        BUTTON_TEXT[size],
        variant === 'primary' && 'font-semibold',
        variant === 'link' && 'h-auto p-0',
        block && 'w-full',
        className,
      )}
      {...rest}
    >
      {loading ? <Spinner /> : icon}
      {children}
    </ShadcnButton>
  )
}

/* ------------------------------------------------------------------- input */

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'w-full rounded-[8px] border border-rule-strong bg-card-2 px-3 py-2 text-[13.5px] text-ink',
        'placeholder:text-faint focus:border-accent-fill focus:outline-none',
        className,
      )}
      {...rest}
    />
  )
}

/**
 * A native <select>, deliberately: shadcn's `select` is a Radix listbox with its
 * own API. `wrapperClassName` reaches the positioned box around the control -
 * a layout that wants the select to grow has to size that, not the select.
 */
export function Select({
  className,
  wrapperClassName,
  children,
  ...rest
}: Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> & { wrapperClassName?: string }) {
  return (
    <NativeSelect
      wrapperClassName={wrapperClassName}
      // h-auto: the height comes from the padding, so a caller's py-1 still
      // makes a compact select. pr-8 is re-applied last because a caller's px-2
      // would otherwise take away the room the chevron sits in.
      className={cn('h-auto bg-card-2 text-[13.5px] text-ink dark:bg-card-2', className, 'pr-8')}
      {...rest}
    >
      {children}
    </NativeSelect>
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
      <label htmlFor={htmlFor} className="text-[12.5px] font-medium text-muted-foreground">
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
  return <ShadcnSwitch checked={checked} onCheckedChange={onCheckedChange} aria-label={label} />
}

/* ------------------------------------------------------------------ status */

type Tone = 'neutral' | 'ok' | 'qualify' | 'warn' | 'bad' | 'accent'

/**
 * The six status tones, shared by Tag and Alert. shadcn's badge and alert only
 * know default/destructive; these ride on top of them as classes rather than as
 * edits to the generated files, so `shadcn add --overwrite` cannot lose them.
 */
const toneVariants = cva('border', {
  variants: {
    tone: {
      neutral: 'text-ink-2 bg-card-2 border-rule-strong',
      ok: 'text-ok bg-ok-bg border-ok-line',
      qualify: 'text-qualify bg-qualify-bg border-qualify-line',
      warn: 'text-warn bg-warn-bg border-warn-line',
      bad: 'text-bad bg-bad-bg border-bad-line',
      accent: 'text-[color:var(--accent-text)] bg-accent-2 border-[color:var(--accent-line)]',
    } satisfies Record<Tone, string>,
  },
  defaultVariants: { tone: 'neutral' },
})

export function Tag({ tone = 'neutral', className, children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return (
    <Badge
      variant="outline"
      className={cn(toneVariants({ tone }), 'gap-1.5 rounded-[5px] px-2 py-0.5 text-[11.5px] font-semibold', className)}
    >
      {children}
    </Badge>
  )
}

export function Dot({ tone = 'neutral', className }: { tone?: Tone; className?: string }) {
  const fill =
    tone === 'ok' ? 'bg-ok' : tone === 'qualify' ? 'bg-qualify' : tone === 'warn' ? 'bg-warn'
      : tone === 'bad' ? 'bg-bad' : tone === 'accent' ? 'bg-accent-fill' : 'bg-faint'
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
  // shadcn lays the alert out as an icon/text grid; this one has an action slot
  // on the right instead, hence flex. w-auto: shadcn's w-full stretches it past
  // its text in a flex column. line-clamp-none: titles here are often error
  // messages, which shadcn's one-line clamp would cut off.
  return (
    <AlertRoot className={cn(toneVariants({ tone }), 'flex w-auto gap-3 rounded-[10px]', className)}>
      <div className="flex min-w-0 grow flex-col gap-1">
        <AlertTitle className="line-clamp-none text-[13.5px] font-semibold tracking-normal">{title}</AlertTitle>
        {description ? (
          <AlertDescription className="block text-[12.5px] leading-relaxed text-ink-2">{description}</AlertDescription>
        ) : null}
      </div>
      {action}
    </AlertRoot>
  )
}

export function Progress({ percent, tone = 'accent', label }: { percent: number; tone?: Tone; label?: string }) {
  const clamped = Math.max(0, Math.min(100, Math.round(percent)))
  const fill =
    tone === 'ok' ? 'bg-ok' : tone === 'bad' ? 'bg-bad' : tone === 'qualify' ? 'bg-qualify' : 'bg-accent-fill'
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
  return <Spinner aria-label={label ?? 'Loading'} className={cn('text-accent-fill', px, className)} />
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
      <span className="text-[13.5px] text-muted-foreground">{description}</span>
      {children}
    </div>
  )
}

/* ------------------------------------------------------------------- chips */

/** The pill look the old `.chip` rule in App.css had, restated over shadcn's toggle. */
const CHIP_CLASS = [
  'h-auto min-w-0 gap-1.5 rounded-[18px] border border-rule bg-card px-3 py-1.5 text-[13px] font-normal text-muted-foreground',
  'hover:border-muted-foreground hover:bg-card hover:text-ink',
  'data-[state=on]:border-ink data-[state=on]:bg-ink data-[state=on]:font-medium data-[state=on]:text-card',
].join(' ')

export interface ChipItem {
  value: string
  label: ReactNode
  /** Shown after the label in small mono figures. */
  count?: ReactNode
}

/**
 * A row of filter chips of which one is chosen. It is Radix's ToggleGroup, so
 * the row is a radiogroup: one tab stop, arrow keys between chips, and a screen
 * reader hears one question with its options instead of N unrelated buttons.
 *
 * Clicking the chosen chip is ignored, as in any radio group, unless
 * `allowEmpty` - then it clears the choice and `onValueChange` gets undefined.
 */
export function ChipGroup({
  value,
  onValueChange,
  items,
  label,
  allowEmpty = false,
  className,
}: {
  value: string | undefined
  onValueChange(next: string | undefined): void
  items: ChipItem[]
  label: string
  allowEmpty?: boolean
  className?: string
}) {
  return (
    <ToggleGroup
      type="single"
      value={value ?? ''}
      onValueChange={(next) => {
        if (next) onValueChange(next)
        else if (allowEmpty) onValueChange(undefined)
      }}
      aria-label={label}
      spacing={1.5}
      className={cn('flex-wrap', className)}
    >
      {items.map((item) => (
        <ToggleGroupItem key={item.value} value={item.value} className={CHIP_CLASS}>
          {item.label}
          {item.count !== undefined && <span className="font-mono text-[11px] tabular-nums opacity-70">{item.count}</span>}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}

/** A single on/off chip. */
export function ChipToggle({
  pressed,
  onPressedChange,
  children,
}: {
  pressed: boolean
  onPressedChange(next: boolean): void
  children: ReactNode
}) {
  return (
    <Toggle pressed={pressed} onPressedChange={onPressedChange} className={CHIP_CLASS}>
      {children}
    </Toggle>
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
        'border-b border-rule px-3 py-2.5 text-left text-[11.5px] font-semibold uppercase tracking-wide text-muted-foreground',
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
          <dt className="text-[12.5px] text-muted-foreground">{item.label}</dt>
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

/** A right-hand sheet. Not shadcn's `drawer`: that one is vaul, and slides up from the bottom. */
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
    <Sheet open={open} onOpenChange={(next) => { if (!next) onClose() }}>
      <SheetContent
        side="right"
        showCloseButton={false}
        aria-describedby={undefined}
        style={{ width: `min(${width}px, 100vw)` }}
        // sm:max-w-none: shadcn caps a sheet at 24rem, which the 440/620px drawers exceed.
        className="gap-4 overflow-y-auto border-rule bg-card p-6 shadow-[var(--shadow)] sm:max-w-none"
      >
        <div className="flex items-start justify-between gap-4">
          <SheetTitle className="m-0 font-display text-[19px] font-bold text-ink">{title}</SheetTitle>
          <SheetClose asChild>
            <Button variant="text" size="small" aria-label="Close">
              <XIcon className="size-[15px]" strokeWidth={2.2} aria-hidden="true" />
            </Button>
          </SheetClose>
        </div>
        {children}
      </SheetContent>
    </Sheet>
  )
}

/** shadcn's tooltip as it comes: inverted ink on paper, with its arrow. */
export function Tooltip({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <TooltipProvider delayDuration={200}>
      <TooltipRoot>
        <TooltipTrigger asChild>{children}</TooltipTrigger>
        <TooltipContent sideOffset={4}>{title}</TooltipContent>
      </TooltipRoot>
    </TooltipProvider>
  )
}

/**
 * shadcn's `line` tabs, recoloured: the underline is the accent and sits on the
 * list's rule, where shadcn floats it 5px below the trigger.
 */
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
    <TabsRoot value={value} onValueChange={onValueChange} className="min-h-0 gap-4">
      <TabsList
        variant="line"
        className="w-full justify-start gap-5 rounded-none border-b border-rule p-0 group-data-[orientation=horizontal]/tabs:h-auto"
      >
        {items.map((item) => (
          <TabsTrigger
            key={item.key}
            value={item.key}
            className={cn(
              'h-auto flex-none rounded-none px-0 pt-0 pb-2.5 text-[13.5px] text-muted-foreground',
              'data-[state=active]:font-semibold data-[state=active]:text-ink',
              'after:bg-accent-fill group-data-[orientation=horizontal]/tabs:after:bottom-[-2px]',
            )}
          >
            {item.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {items.map((item) => (
        <TabsContent key={item.key} value={item.key} className="min-h-0">
          {item.children}
        </TabsContent>
      ))}
    </TabsRoot>
  )
}
