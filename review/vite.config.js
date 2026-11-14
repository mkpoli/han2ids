// The review desk: a local page whose answers are written straight into data/review/answers.json.
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { createReadStream, existsSync, mkdirSync, readFileSync, realpathSync, renameSync, statSync, writeFileSync } from 'node:fs'
import { dirname, extname, normalize } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const root = fileURLToPath(new URL('..', import.meta.url))
const DECKS = `${root}build/review/decks.json`
const ANSWERS = `${root}data/review/answers.json`
// Jigmo covers every character the labels use; scripts/fetch_fonts.py puts it here.
const FONTS = `${root}cache/fonts/jigmo/`
// A build of the IDS Workshop (ids-input's `vite build demo`), served beside the desk so the editor is the site's own.
const WORKSHOP = (process.env.IDS_WORKSHOP ?? `${root}build/review/workshop`).replace(/\/?$/, '/')
// han-compose's composer, linked in from a checkout outside this repository; its drawing worker is served from there.
const HAN_COMPOSE = `${root}build/review/han-compose`
const WEB = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.wasm': 'application/wasm',
  '.woff2': 'font/woff2', '.gz': 'application/gzip', '.svg': 'image/svg+xml', '.webp': 'image/webp', '.png': 'image/png', '.txt': 'text/plain', '.tsv': 'text/tab-separated-values' }
const TYPES = { '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp' }

function desk() {
  // Re-read whenever prepare.py rewrites the decks, so a running desk sees them.
  let decks = null
  let stamp = 0
  const read = () => {
    const now = statSync(DECKS).mtimeMs
    if (now !== stamp) { decks = JSON.parse(readFileSync(DECKS, 'utf8')); stamp = now }
    return decks
  }
  const answers = () => (existsSync(ANSWERS) ? JSON.parse(readFileSync(ANSWERS, 'utf8')) : {})
  const json = (res, status, body) => { res.statusCode = status; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(body)) }
  return {
    name: 'review-desk',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url, 'http://localhost')
        if (url.pathname === '/api/workshop') return json(res, 200, { available: existsSync(`${WORKSHOP}editor.html`) })
        if (existsSync(`${WORKSHOP}editor.html`)) {
          // The Workshop's editor page and its assets; the desk keeps its own index.
          const path = normalize(decodeURIComponent(url.pathname)).replace(/^\/+/, '')
          const file = `${WORKSHOP}${path}`
          if (path && path !== 'index.html') {
            if (!path.startsWith('..') && existsSync(file) && statSync(file).isFile()) {
              res.setHeader('Content-Type', WEB[extname(file)] ?? 'application/octet-stream')
              return createReadStream(file).pipe(res)
            }
          }
        }
        if (url.pathname === '/api/decks') {
          if (!existsSync(DECKS)) return json(res, 404, { error: 'Run review/prepare.py first.' })
          const all = read()
          // The page gets everything but the image paths, which stay on this machine.
          return json(res, 200, Object.fromEntries(Object.entries(all).map(([name, items]) => [name, items.map(({ image, ...rest }) => rest)])))
        }
        // By item id, so an image always belongs to the item a page shows, whatever order the decks are rebuilt in.
        const glyph = /^\/glyph\/([a-z]+)\/([A-Za-z0-9_.-]+)$/.exec(url.pathname)
        if (glyph) {
          const item = read()[glyph[1]]?.find(entry => entry.id === glyph[2])
          if (!item || !existsSync(item.image)) return json(res, 404, { error: 'No such glyph.' })
          res.setHeader('Content-Type', TYPES[extname(item.image)] ?? 'application/octet-stream')
          res.setHeader('Cache-Control', 'max-age=3600')
          return createReadStream(item.image).pipe(res)
        }
        const font = /^\/fonts\/(Jigmo[23]?\.ttf)$/.exec(url.pathname)
        if (font) {
          if (!existsSync(FONTS + font[1])) return json(res, 404, { error: 'Run scripts/fetch_fonts.py first.' })
          res.setHeader('Content-Type', 'font/ttf')
          res.setHeader('Cache-Control', 'max-age=86400')
          return createReadStream(FONTS + font[1]).pipe(res)
        }
        if (url.pathname === '/api/answers' && req.method === 'GET') return json(res, 200, answers())
        const one = /^\/api\/answers\/([A-Za-z0-9_.-]+)$/.exec(url.pathname)
        if (one && req.method === 'PUT') {
          let body = ''
          req.on('data', chunk => { body += chunk })
          req.on('end', () => {
            try {
              const value = JSON.parse(body)
              const all = answers()
              if (value === null) delete all[one[1]]
              else all[one[1]] = { c: String(value.c), ids: String(value.ids ?? ''), at: String(value.at) }
              const sorted = Object.fromEntries(Object.keys(all).sort().map(key => [key, all[key]]))
              mkdirSync(dirname(ANSWERS), { recursive: true })
              writeFileSync(`${ANSWERS}.tmp`, `${JSON.stringify(sorted, null, 1)}\n`)
              renameSync(`${ANSWERS}.tmp`, ANSWERS)
              json(res, 200, { saved: Object.keys(sorted).length })
            } catch (error) { json(res, 400, { error: String(error) }) }
          })
          return
        }
        next()
      })
    },
  }
}

export default defineConfig({
  plugins: [svelte(), desk()],
  // The IDS editor's data is fetched as gzip files, and each stays a file of its own.
  build: { assetsInlineLimit: 0 },
  server: { port: 8430, strictPort: true, fs: { allow: ['..', ...existsSync(HAN_COMPOSE) ? [realpathSync(HAN_COMPOSE)] : []] } },
})
