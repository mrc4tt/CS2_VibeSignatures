import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { copyFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gameDataPlugin } from './gameDataPlugin'
import { gameSymbolsPlugin } from './gameSymbolsPlugin'
import { siteMetaPlugin } from './siteMetaPlugin'
import { symbolPagesPlugin } from './symbolPagesPlugin'

const configuredInputRoot = process.env.PAGES_RELEASE_INPUT_ROOT
if (!process.env.VITEST && !configuredInputRoot) {
  throw new Error('PAGES_RELEASE_INPUT_ROOT is required for Pages development and builds')
}
const inputRoot = configuredInputRoot
  ? resolve(configuredInputRoot)
  : fileURLToPath(new URL('..', import.meta.url))

/**
 * GitHub Pages has no rewrite rule, so it answers an unknown path with its own
 * 404 page. Every route other than "/" is an unknown path to it, which is why a
 * deep link into the app only ever worked in dev. Pages does serve 404.html for
 * those, so shipping the app shell under that name turns the 404 into the router
 * taking over. nginx does the same job with try_files.
 */
function spaFallback(): Plugin {
  let outDir = 'dist'
  return {
    name: 'spa-fallback-404',
    configResolved(config) {
      outDir = config.build.outDir
    },
    // Copied after the write rather than emitted during the bundle: in Vite 7
    // index.html is not in the bundle yet when generateBundle runs, so emitting
    // from there failed outright.
    async closeBundle() {
      const root = fileURLToPath(new URL('.', import.meta.url))
      const index = resolve(root, outDir, 'index.html')
      const fallback = resolve(root, outDir, '404.html')
      await copyFile(index, fallback)
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    spaFallback(),
    gameSymbolsPlugin(join(inputRoot, 'gamesymbols')),
    gameDataPlugin(join(inputRoot, 'gamedata')),
    siteMetaPlugin(join(inputRoot, 'gamesymbols'), join(inputRoot, 'gamedata'), inputRoot),
    symbolPagesPlugin(),
  ],
  // Custom domain (sig.miksen.me) serves at root; the github.io/CS2_VibeSignatures path no longer applies.
  base: '/',
})
