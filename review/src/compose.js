// A sequence drawn in Mincho by han-compose's composer, from the serif export the IDS Workshop draws with.
import { composerPreview } from '@han-compose/composer'
import { askDrawable, createCustomComponents } from 'ids-input'
import customUrl from 'ids-input/data/custom-components.json.gz?url'

export const SERIF_EXPORT = 'https://ids-input-composer.mkpoli.workers.dev/8156f838798c-serif-compose-layout-v4-serif-f6+variants/'
// A component no code point names (#(-𠃍㇉), {53}) is drawn as the character or sequence ids-input gives it.
let custom = null
/** @param {string} text */
const drawable = text => (custom ??= fetch(customUrl).then(gunzipped).then(body => createCustomComponents(JSON.parse(body)))
  .catch(error => { custom = null; throw error })).then(table => table.drawableLeaves(text))

/** A response's text; the dev server may send the .gz as it is or already decoded. @param {Response} response */
async function gunzipped(response) {
  if (!response.ok) throw new Error(`${response.url}: ${response.status}`)
  const bytes = new Uint8Array(await response.arrayBuffer())
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return new TextDecoder().decode(bytes)
  return new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text()
}

/** The editor's live preview; a newer sequence replaces the one in flight. */
export const preview = askDrawable(composerPreview({ base: SERIF_EXPORT, fontStyle: 'serif' }), drawable)

// The options' drawings go through a second composer, one at a time, and are kept.
const drawer = askDrawable(composerPreview({ base: SERIF_EXPORT, fontStyle: 'serif' }), drawable)
const drawings = new Map()
let last = Promise.resolve()

/** @param {string} ids */
export function draw(ids) {
  if (!drawings.has(ids)) {
    const drawn = last.then(() => drawer(ids, {}))
    last = drawn.catch(() => {})
    drawings.set(ids, drawn)
  }
  return drawings.get(ids)
}
