<script>
  // One glyph at a time: the image stays on the left while a reading is picked or written on the right.
  import Composed from './Composed.svelte'

  let decks = $state(null)
  let copied = $state('')
  let failure = $state('')
  let answers = $state({})
  let deck = $state('irg')
  let index = $state({ irg: 0, clean: 0 })
  let pending = $state(0)
  let failed = $state(false)
  let editing = $state(false)
  let draft = $state('')
  let Editor = $state(null)
  let workshop = $state(false)
  let frame = $state(null)
  let start = $state('')
  // Settled before any editor opens, so an editing session keeps the editor it started with.
  const discovery = fetch('/api/workshop').then(response => response.json()).then(body => { workshop = Boolean(body.available) }).catch(() => {})

  const NAMES = { irg: 'Proposal glyphs', clean: 'Model vs label' }
  const items = $derived(decks?.[deck] ?? [])
  const item = $derived(items[index[deck]])
  const given = $derived(item ? answers[item.id] : null)
  const done = $derived(items.filter(entry => answers[entry.id]).length)
  const options = $derived(!item ? [] : deck === 'irg'
    ? [...item.known ? [{ c: 'known', key: 'Z', shift: 'KeyZ', who: item.char ? `BabelStone ${item.char}` : 'zi.tools', ids: item.known }] : [],
       ...item.cands.map((cand, n) => ({ c: `c${n}`, key: String(n + 1), shift: `Digit${n + 1}`, ids: cand[0], note: cand[1].toFixed(2) }))]
    : [{ c: 'label', key: 'L', who: 'Label', ids: item.label }, { c: 'model', key: 'M', who: 'Model', ids: item.model, note: item.score.toFixed(2) },
       { c: 'both', key: 'B', who: 'Both describe it', ids: '' }])
  const tally = $derived.by(() => {
    const out = {}
    for (const entry of items) {
      const a = answers[entry.id]
      if (a) { const kind = /^c\d$/.test(a.c) ? 'suggested' : a.c; out[kind] = (out[kind] ?? 0) + 1 }
    }
    return out
  })

  try { const saved = JSON.parse(localStorage.getItem('ids-desk') ?? 'null'); if (saved) { deck = saved.deck; Object.assign(index, saved.index) } } catch {}
  $effect(() => { try { localStorage.setItem('ids-desk', JSON.stringify({ deck, index })) } catch {} })

  Promise.all([fetch('/api/decks'), fetch('/api/answers')]).then(async ([a, b]) => {
    if (!a.ok) throw new Error((await a.json()).error)
    decks = await a.json()
    answers = await b.json()
    if (!decks[deck]) deck = Object.keys(decks)[0]
    if (answers[decks[deck][index[deck]]?.id]) { const n = nextOpen(index[deck]); if (n >= 0) index[deck] = n }
  }).catch(error => { failure = String(error.message ?? error) })

  async function save(id, value) {
    pending += 1
    try {
      const response = await fetch(`/api/answers/${id}`, { method: 'PUT', body: JSON.stringify(value) })
      if (!response.ok) throw new Error(String(response.status))
      failed = false
    } catch { failed = true } finally { pending -= 1 }
  }
  function answer(c, ids) {
    const value = { c, ids, at: new Date().toISOString() }
    answers[item.id] = value
    save(item.id, value)
    editing = false
    const n = nextOpen(index[deck] + 1)
    if (n >= 0) index[deck] = n
    else if (index[deck] < items.length - 1) index[deck] += 1
  }
  function nextOpen(from) {
    for (let k = 0; k < items.length; k += 1) { const at = (from + k) % items.length; if (!answers[items[at].id]) return at }
    return -1
  }
  function go(at) { editing = false; index[deck] = Math.max(0, Math.min(items.length - 1, at)) }
  function choose(option) { answer(option.c, option.c === 'both' ? item.label : option.ids) }
  async function write(from) {
    await discovery
    draft = typeof from === 'string' ? from : given?.c === 'custom' ? given.ids : deck === 'irg' ? item.cands[0]?.[0] ?? '' : item.model
    start = draft
    editing = true
    if (!workshop) Editor ??= (await import('./Editor.svelte')).default
  }
  function use(sequence = draft) { const text = String(sequence ?? '').trim(); if (text) answer('custom', text) }

  // The Workshop's editor page posts each change to the page that frames it.
  function heard(event) {
    if (!editing || !frame || event.source !== frame.contentWindow || event.data?.type !== 'ids-input:sequence') return
    draft = String(event.data.sequence ?? '')
  }

  async function copy(text) {
    try { await navigator.clipboard.writeText(text); copied = text; setTimeout(() => { if (copied === text) copied = '' }, 1200) } catch { copied = '' }
  }

  function keys(event) {
    if (!item || event.metaKey || event.ctrlKey || event.altKey) return
    if (editing) { if (event.key === 'Escape') editing = false; return }
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return
    const key = event.key.toUpperCase()
    if (event.key === 'ArrowLeft') go(index[deck] - 1)
    else if (event.key === 'ArrowRight') go(index[deck] + 1)
    else if (key === 'E') write()
    else if (key === 'X') answer('skip', '')
    else {
      const option = options.find(o => o.key === key || (event.shiftKey && o.shift === event.code))
      if (!option) return
      // Shift with an option's key opens the editor on that option.
      if (event.shiftKey && option.ids) write(option.ids)
      else choose(option)
    }
    event.preventDefault()
  }
</script>

<svelte:window onkeydown={keys} onmessage={heard} />

<div class="desk">
  <header class="top">
    <h1>IDS Review Desk</h1>
    {#if decks}
      <div class="ui-switch-bar tabs" role="tablist">
        {#each Object.keys(decks) as name}
          <button class="ui-button" role="tab" data-size="sm" aria-selected={name === deck} class:is-on={name === deck} onclick={() => { editing = false; deck = name }}>
            {NAMES[name] ?? name} <span class="count">{decks[name].filter(entry => answers[entry.id]).length}/{decks[name].length}</span>
          </button>
        {/each}
      </div>
    {/if}
    <span class="save" data-state={failed ? 'error' : pending ? 'saving' : 'saved'}>{failed ? 'Not saved' : pending ? 'Saving…' : 'Saved'}</span>
  </header>

  {#if failure}
    <p class="ui-error">{failure}</p>
  {:else if item}
    <progress class="bar" max={items.length} value={done}></progress>
    <p class="meta">
      <span><b>{index[deck] + 1}</b> of {items.length}</span>
      <span><b>{done}</b> answered</span>
      {#each [['known', 'known IDS'], ['suggested', 'suggestion kept'], ['label', 'label'], ['model', 'model'], ['both', 'both'], ['custom', 'written'], ['skip', "can't tell"]] as [kind, label]}
        {#if tally[kind]}<span><b>{tally[kind]}</b> {label}</span>{/if}
      {/each}
    </p>

    <div class="work">
      <aside class="reference">
        <img class="glyph" src={`/glyph/${deck}/${item.id}`} alt="Glyph under review">
        <div class="chips">
          {#if deck === 'irg'}
            {#each [item.set, item.source, item.doc && `IRG${item.doc.toUpperCase()}`].filter(Boolean) as text}<span class="ui-chip">{text}</span>{/each}
          {/if}
          {#if item.char}
            <a class="ui-chip zi" href={`https://zi.tools/zi/${encodeURIComponent(item.char)}`} target="_blank" rel="noreferrer" title="Open on zi.tools">
              <span class="char" lang="zh-Hani">{item.char}</span> U+{item.char.codePointAt(0).toString(16).toUpperCase()} ↗
            </a>
          {/if}
          {#if item.zi}
            <a class="ui-chip zi" href={`https://zi.tools/zi/${encodeURIComponent(item.zi)}`} target="_blank" rel="noreferrer" title="Open on zi.tools">zi.tools ↗</a>
          {/if}
          {#if deck === 'clean'}<span class="ui-chip">{item.font}</span>{/if}
        </div>
        <div class="nav">
          <button class="ui-button" data-size="sm" onclick={() => go(index[deck] - 1)}>← Back</button>
          <button class="ui-button" data-size="sm" onclick={() => go(index[deck] + 1)}>Next →</button>
          <button class="ui-button" data-size="sm" data-variant="quiet" onclick={() => { const n = nextOpen(index[deck] + 1); if (n >= 0) go(n) }}>Next unanswered</button>
          <input class="jump" type="number" min="1" max={items.length} value={index[deck] + 1} aria-label="Go to" onchange={event => go(Number(event.currentTarget.value) - 1)}>
        </div>
      </aside>

      <section class="side">
        <div class="choices">
          {#each options as option (option.c)}
            <div class="option">
              <button class="choice" aria-pressed={given?.c === option.c} onclick={() => choose(option)}>
                <kbd>{option.key}</kbd>
                {#if option.ids}<Composed ids={option.ids} />{/if}
                <span>
                  {#if option.who}<span class="who">{option.who}</span>{/if}
                  {#if option.ids}<span class="ids" lang="zh-Hani">{option.ids}</span>{/if}
                </span>
                <span class="note">{option.note ?? ''}</span>
              </button>
              {#if option.ids}
                <button class="ui-button" data-size="sm" title="Open this one in the editor (Shift+{option.key})" onclick={() => write(option.ids)}>Edit</button>
                <button class="ui-button" data-size="sm" onclick={() => copy(option.ids)}>{copied === option.ids ? 'Copied' : 'Copy'}</button>
              {/if}
            </div>
          {/each}
          <div class="row">
            <button class="choice write" aria-pressed={given?.c === 'custom' || editing} onclick={write}>
              <kbd>E</kbd>
              {#if given?.c === 'custom'}<Composed ids={given.ids} />{/if}
              <span>{#if given?.c === 'custom'}<span class="who">Written</span><span class="ids" lang="zh-Hani">{given.ids}</span>{:else}Write IDS{/if}</span>
              <span class="note"></span>
            </button>
            <button class="choice skip" aria-pressed={given?.c === 'skip'} onclick={() => answer('skip', '')}><kbd>X</kbd><span>Can't tell</span><span class="note"></span></button>
          </div>
        </div>

        {#if editing}
          <div class="editor">
            <div class="editor-foot">
              {#if workshop}<Composed ids={draft} size={56} /><span class="ids draft" lang="zh-Hani">{draft}</span>{/if}
              <button class="ui-button" onclick={() => { editing = false }}>Cancel</button>
              {#if workshop}<button class="ui-button" data-variant="primary" disabled={!draft} onclick={() => use()}>Use this IDS</button>{/if}
            </div>
            {#if workshop}
              {#key item.id + start}<iframe class="workshop" bind:this={frame} src={`/editor.html?lang=en&ids=${encodeURIComponent(start)}`} title="IDS Workshop"></iframe>{/key}
            {:else if Editor}<Editor bind:value={draft} onuse={use} />{:else}<p class="meta">Loading the editor…</p>{/if}
          </div>
        {/if}
      </section>
    </div>
  {:else}
    <p class="meta">Loading…</p>
  {/if}
</div>
