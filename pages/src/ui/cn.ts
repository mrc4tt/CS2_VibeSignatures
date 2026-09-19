/**
 * Join class names, letting a later Tailwind utility win over an earlier one.
 *
 * Re-exported from shadcn's `cn` package rather than built here from clsx and
 * tailwind-merge. Since September 2026 every generated shadcn component imports
 * `cn` from that package directly, so keeping a second implementation would mean
 * our primitives and the shadcn ones could merge the same classes differently.
 * Parity was checked before the switch on the conflicts this app actually
 * produces - custom tokens like bg-accent-fill and text-[color:var(--accent-text)]
 * included - and all of them merged identically.
 */
export { cn } from 'cn'
