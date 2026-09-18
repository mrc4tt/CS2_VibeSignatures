/**
 * The seven icons the app used from @ant-design/icons, as inline stroke SVG.
 *
 * Inline rather than a library: these are the only ones in use, they inherit
 * currentColor so a Tag or Button carries them without a second colour token,
 * and it takes ~2 kB against the icon package's several hundred.
 */
import type { SVGProps } from 'react'

export type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function Glyph({ children, size = 16, ...rest }: SVGProps<SVGSVGElement> & { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  )
}

export const ArrowLeftIcon = (props: IconProps) => (
  <Glyph {...props}><path d="M19 12H5" /><path d="M11 18l-6-6 6-6" /></Glyph>
)

export const ReloadIcon = (props: IconProps) => (
  <Glyph {...props}><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 4v7h-7" /></Glyph>
)

export const WarningIcon = (props: IconProps) => (
  <Glyph {...props}><path d="M12 9v4" /><path d="M12 17h.01" /><path d="M10.3 4.3 2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z" /></Glyph>
)

export const ApiIcon = (props: IconProps) => (
  <Glyph {...props}><path d="M10 14 4.5 19.5a3.5 3.5 0 0 1-5-5L5 9" /><path d="m14 10 5.5-5.5a3.5 3.5 0 0 1 5 5L19 15" /><path d="m9 15 6-6" /></Glyph>
)

export const SettingsIcon = (props: IconProps) => (
  <Glyph {...props}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z" /></Glyph>
)

export const MoonIcon = (props: IconProps) => (
  <Glyph {...props}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></Glyph>
)

export const SunIcon = (props: IconProps) => (
  <Glyph {...props}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Glyph>
)

/* Navigation glyphs, one per view in the sidebar rail. */

export const OverviewIcon = (props: IconProps) => (
  <Glyph {...props}><rect x="3" y="3" width="7" height="9" /><rect x="14" y="3" width="7" height="5" /><rect x="14" y="12" width="7" height="9" /><rect x="3" y="16" width="7" height="5" /></Glyph>
)

export const SearchIcon = (props: IconProps) => (
  <Glyph {...props}><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.5" y2="16.5" /></Glyph>
)

export const TableIcon = (props: IconProps) => (
  <Glyph {...props}><path d="M4 5h16v14H4z" /><path d="M4 10h16" /><path d="M10 10v9" /></Glyph>
)

export const FileCheckIcon = (props: IconProps) => (
  <Glyph {...props}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /><path d="M9 15l2 2 4-4" /></Glyph>
)

export const ChartIcon = (props: IconProps) => (
  <Glyph {...props}><path d="M4 19V5" /><path d="M4 19h16" /><path d="M8 15l4-6 3 4 4-7" /></Glyph>
)

export const BookIcon = (props: IconProps) => (
  <Glyph {...props}><path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z" /><path d="M5 17h14" /></Glyph>
)

export const CopyIcon = (props: IconProps) => (
  <Glyph {...props}><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></Glyph>
)

export const DownloadIcon = (props: IconProps) => (
  <Glyph {...props}><path d="M12 3v12" /><path d="M7 11l5 5 5-5" /><path d="M4 20h16" /></Glyph>
)

export const InfoIcon = (props: IconProps) => (
  <Glyph {...props}><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><path d="M12 8h.01" /></Glyph>
)

export const CheckIcon = (props: IconProps) => (
  <Glyph strokeWidth={2.6} {...props}><path d="M20 6L9 17l-5-5" /></Glyph>
)
