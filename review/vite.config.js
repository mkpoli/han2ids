// The review desk: a local page whose answers are written straight into data/review/answers.json.
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { createReadStream, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const root = fileURLToPath(new URL('..', import.meta.url))
const DECKS = `${root}build/review/decks.json`
const ANSWERS = `${root}data/review/answers.json`
const TYPES = { '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp' }

function desk() {
  let decks = null
  const read = () => (decks ??= JSON.parse(readFileSync(DECKS, 'utf8')))
  const answers = () => (existsSync(ANSWERS) ? JSON.parse(readFileSync(ANSWERS, 'utf8')) : {})
  const json = (res, status, body) => { res.statusCode = status; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(body)) }
  return {
    name: 'review-desk',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url, 'http://localhost')
        if (url.pathname === '/api/decks') {
          if (!existsSync(DECKS)) return json(res, 404, { error: 'Run review/prepare.py first.' })
          const all = read()
          // The page gets everything but the image paths, which stay on this machine.
          return json(res, 200, Object.fromEntries(Object.entries(all).map(([name, items]) => [name, items.map(({ image, ...rest }) => rest)])))
        }
        const glyph = /^\/glyph\/([a-z]+)\/(\d+)$/.exec(url.pathname)
        if (glyph) {
          const item = read()[glyph[1]]?.[Number(glyph[2])]
          if (!item || !existsSync(item.image)) return json(res, 404, { error: 'No such glyph.' })
          res.setHeader('Content-Type', TYPES[extname(item.image)] ?? 'application/octet-stream')
          res.setHeader('Cache-Control', 'max-age=3600')
          return createReadStream(item.image).pipe(res)
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
  server: { port: 8430, strictPort: true, fs: { allow: ['..'] } },
})
