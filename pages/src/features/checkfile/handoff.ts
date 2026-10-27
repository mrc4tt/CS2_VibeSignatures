/**
 * A file carried from Check my file into the scanner.
 *
 * Held in memory only, for one navigation: the text never touches storage, and
 * a reload of /scan simply opens on the example instead. The scanner clears it
 * once mounted, so Back and Forward do not bring an old file back.
 */
let pending: { text: string; name: string } | null = null

export function handOff(text: string, name: string): void {
  pending = { text, name }
}

/** Read without clearing, so a component can read it in a state initializer (which StrictMode runs twice). */
export function peekHandoff(): { text: string; name: string } | null {
  return pending
}

export function clearHandoff(): void {
  pending = null
}
