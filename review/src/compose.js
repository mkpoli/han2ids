// A sequence drawn in Mincho by han-compose, through ids-input's composer and its published serif export.
import { composerPreview } from 'ids-input/composer'

export const SERIF_EXPORT = 'https://ids-input-composer.mkpoli.workers.dev/8156f838798c-serif-compose-layout-v4-serif-f6/'
/** The editor's live preview; a newer sequence replaces the one in flight. */
export const preview = composerPreview({ base: SERIF_EXPORT, fontStyle: 'serif' })

// The options' drawings go through a second composer, one at a time, and are kept.
const drawer = composerPreview({ base: SERIF_EXPORT, fontStyle: 'serif' })
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
