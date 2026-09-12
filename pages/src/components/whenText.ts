/**
 * Dates in the reader's own clock and language. dateStyle/timeStyle cannot be
 * combined with timeZoneName, so the components are named individually: mixing
 * them throws and the zone is silently lost.
 */
export function formatWhen(iso: string | undefined, language: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  try {
    return new Intl.DateTimeFormat(language, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
    }).format(date)
  } catch {
    return date.toLocaleString()
  }
}

export function formatDay(iso: string | undefined, language: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  try {
    return new Intl.DateTimeFormat(language, { year: 'numeric', month: 'short', day: 'numeric' }).format(date)
  } catch {
    return date.toLocaleDateString()
  }
}

export function formatAgo(iso: string | undefined, language: string): string {
  if (!iso) return ''
  const elapsed = Date.now() - new Date(iso).getTime()
  if (!Number.isFinite(elapsed)) return ''
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['minute', 60], ['hour', 24], ['day', 30], ['month', 12], ['year', Number.POSITIVE_INFINITY],
  ]
  let value = Math.round(elapsed / 60_000)
  let index = 0
  while (index < units.length - 1 && Math.abs(value) >= units[index][1]) {
    value = Math.round(value / units[index][1])
    index += 1
  }
  try {
    return new Intl.RelativeTimeFormat(language, { numeric: 'auto' }).format(-value, units[index][0])
  } catch {
    return ''
  }
}
