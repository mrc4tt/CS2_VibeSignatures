import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gameDataPlugin } from './gameDataPlugin'
import { gameSymbolsPlugin } from './gameSymbolsPlugin'
import { siteMetaPlugin } from './siteMetaPlugin'

const configuredInputRoot = process.env.PAGES_RELEASE_INPUT_ROOT
if (!process.env.VITEST && !configuredInputRoot) {
  throw new Error('PAGES_RELEASE_INPUT_ROOT is required for Pages development and builds')
}
const inputRoot = configuredInputRoot
  ? resolve(configuredInputRoot)
  : fileURLToPath(new URL('..', import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    gameSymbolsPlugin(join(inputRoot, 'gamesymbols')),
    gameDataPlugin(join(inputRoot, 'gamedata')),
    siteMetaPlugin(join(inputRoot, 'gamesymbols'), join(inputRoot, 'gamedata'), inputRoot),
  ],
  // Custom domain (sig.miksen.me) serves at root; the github.io/CS2_VibeSignatures path no longer applies.
  base: '/',
})
