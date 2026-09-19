import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const read = (relative: string) => readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8')

/**
 * shadcn components style dark mode with `dark:` classes. Tailwind v4 resolves
 * those against prefers-color-scheme unless told otherwise, which is the OS
 * setting and not this site's toggle - a visitor on a dark OS who picked the
 * light theme gets dark fills on light surfaces. Nothing else would notice: the
 * pages still render, and the tests query by role, not by colour.
 */
describe('dark variant', () => {
  it('follows html[data-theme], not the OS', () => {
    expect(read('../index.css')).toMatch(
      /@custom-variant dark \(&:where\(\[data-theme="dark"\], \[data-theme="dark"\] \*\)\);/,
    )
  })

  it('has data-theme set before first paint, to one of the two values it matches', () => {
    const html = read('../../index.html')
    expect(html).toContain('<html lang="en" data-theme="dark">')
    expect(html).toMatch(/setAttribute\('data-theme', theme === 'light' \? 'light' : 'dark'\)/)
  })
})
