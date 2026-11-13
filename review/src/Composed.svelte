<script>
  // The sequence as han-compose draws it, so it can be held against the glyph.
  import { draw } from './compose.js'
  let { ids, size = 64 } = $props()
  let drawn = $state(null)
  let state = $state('idle')

  $effect(() => {
    const text = ids
    drawn = null
    if (!text) { state = 'idle'; return }
    state = 'loading'
    let live = true
    draw(text)
      .then(result => { if (live) { drawn = result; state = 'drawn' } })
      .catch(() => { if (live) state = 'failed' })
    return () => { live = false }
  })
</script>

<span class="composed" data-state={state} style:inline-size={`${size}px`} style:block-size={`${size}px`} title={state === 'failed' ? 'Could not compose' : ids}>
  {#if drawn}
    <svg viewBox="0 0 1000 1000" aria-hidden="true">
      <path d={drawn.d} />
      {#each drawn.slots ?? [] as slot}<rect x={slot.box[0]} y={slot.box[1]} width={slot.box[2]} height={slot.box[3]} class="slot" />{/each}
    </svg>
  {/if}
</span>

<style>
  .composed { flex: none; display: inline-grid; place-items: center; background: #fff; color: #000; border: 1px solid var(--ui-color-border); border-radius: 8px; }
  .composed[data-state="failed"] { background: repeating-linear-gradient(135deg, #fff 0 6px, #f1f1f4 6px 12px); }
  .composed[data-state="loading"] { opacity: .6; }
  svg { inline-size: 88%; block-size: 88%; }
  path { fill: currentColor; }
  .slot { fill: none; stroke: #9a9aa6; stroke-width: 12; stroke-dasharray: 40 30; }
</style>
