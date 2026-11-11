import { selectElements } from './elements.js';
import { uid } from './identity.js';
import { padBox } from './geometry.js';
import { frameSize } from './prepare.js';
import { renderIds } from './render-ids.js';

export function createQueue(deps, els = selectElements(['queueCard', 'queueTotal', 'itemList', 'queuePosition', 'itemPrev', 'itemNext'])) {
  let items = [];
  let selectedId = null;
  const rows = new Map();
  const THUMB = 96;

  // Queue owns item membership and thumbnails; stage owns geometry, reading owns read state.
  function buildItems(source, boxes) {
    const list = boxes.length ? boxes : [source.inkBox ?? { x: 0, y: 0, w: 1, h: 1 }];
    return list.map((box, at) => ({
      id: uid(),
      sourceId: source.id,
      index: at + 1,
      box,
      crop: padBox(box, deps.getMargin(), frameSize(source)),
      margin: deps.getMargin(),
      readings: [],
      phase: 'queued',
      errorKey: null,
      thumb: null,
      thumbUrl: '',
      seq: 0,
    }));
  }

  function itemsOf(sourceId) {
    return items.filter(item => item.sourceId === sourceId);
  }

  function byId(id) {
    return items.find(item => item.id === id) ?? null;
  }

  function selectedItem() {
    return byId(selectedId);
  }

  function selectItem(id, { scroll = true } = {}) {
    const item = byId(id);
    if (!item) return;
    selectedId = id;
    deps.onSelect({ scroll });
  }

  function stepSelection(step) {
    if (!items.length) return;
    const at = items.findIndex(item => item.id === selectedId);
    const next = items[Math.min(items.length - 1, Math.max(0, at + step))];
    if (next) selectItem(next.id);
  }
  /* ---------- The item list ---------- */

  function renderQueue({ scroll = false } = {}) {
    els.queueCard.hidden = items.length === 0;
    els.queueTotal.textContent = String(items.length);

    const seen = new Set();
    const list = items.map(item => {
      seen.add(item.id);
      return rows.get(item.id) ?? makeRow(item);
    });
    for (const id of [...rows.keys()]) if (!seen.has(id)) rows.delete(id);
    els.itemList.replaceChildren(...list);
    for (const item of items) updateRow(item);

    const at = items.findIndex(item => item.id === selectedId);
    els.queuePosition.textContent = at < 0 ? '' : `${at + 1} / ${items.length}`;
    els.itemPrev.disabled = at <= 0;
    els.itemNext.disabled = at < 0 || at >= items.length - 1;
    if (scroll && at >= 0) rows.get(selectedId)?.scrollIntoView({ block: 'nearest' });
  }

  function makeRow(item) {
    const row = document.createElement('li');
    row.className = 'ui-list-row item-row';
    row.dataset.id = item.id;
    row.dataset.interactive = '';
    row.setAttribute('role', 'option');
    row.tabIndex = -1;

    const thumb = document.createElement('img');
    thumb.className = 'item-thumb';
    thumb.alt = '';

    const main = document.createElement('span');
    main.className = 'item-main';
    const ids = document.createElement('span');
    ids.className = 'item-ids';
    ids.lang = 'zh-Hani';
    const source = document.createElement('span');
    source.className = 'item-source';
    main.append(ids, source);

    const mark = document.createElement('span');
    mark.className = 'item-state';

    row.append(thumb, main, mark);
    rows.set(item.id, row);
    return row;
  }

  function updateRow(item) {
    const row = rows.get(item.id);
    if (!row) return;
    const selected = item.id === selectedId;
    row.setAttribute('aria-selected', String(selected));
    row.tabIndex = selected ? 0 : -1;

    const thumb = row.querySelector('.item-thumb');
    if (item.thumbUrl && thumb.getAttribute('src') !== item.thumbUrl) thumb.src = item.thumbUrl;
    if (!item.thumbUrl) thumb.removeAttribute('src');

    const reading = item.readings[0];
    const ids = row.querySelector('.item-ids');
    if (reading) renderIds(ids, reading.ids);
    else ids.textContent = '';
    ids.classList.toggle('is-waiting', !reading);

    const source = deps.getSource(item.sourceId);
    const label = itemsOf(item.sourceId).length > 1 ? `${source.name} · ${item.index}` : source.name;
    row.querySelector('.item-source').textContent = label;

    const mark = row.querySelector('.item-state');
    mark.dataset.state = item.phase;
    mark.title = deps.t(`state.${item.phase}`);
    mark.setAttribute('aria-label', deps.t(`state.${item.phase}`));
  }

  els.itemList.addEventListener('click', event => {
    const row = event.target.closest('[data-id]');
    if (row) selectItem(row.dataset.id, { scroll: false });
  });

  els.itemList.addEventListener('keydown', event => {
    const keys = { ArrowDown: 1, ArrowUp: -1, Home: 'first', End: 'last' };
    if (!(event.key in keys) || !items.length) return;
    event.preventDefault();
    const step = keys[event.key];
    if (step === 'first') selectItem(items[0].id);
    else if (step === 'last') selectItem(items[items.length - 1].id);
    else stepSelection(step);
    rows.get(selectedId)?.focus({ preventScroll: true });
  });

  els.itemPrev.addEventListener('click', () => stepSelection(-1));
  els.itemNext.addEventListener('click', () => stepSelection(1));
  async function makeThumb(item, image) {
    const sx = Math.max(0, Math.floor(item.crop.x * image.width));
    const sy = Math.max(0, Math.floor(item.crop.y * image.height));
    const sw = Math.max(1, Math.round(item.crop.w * image.width));
    const sh = Math.max(1, Math.round(item.crop.h * image.height));
    const scale = Math.min(1, THUMB / Math.max(sw, sh));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(sw * scale));
    canvas.height = Math.max(1, Math.round(sh * scale));
    const context = canvas.getContext('2d');
    context.drawImage(image, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    if (!blob) return;
    if (item.thumbUrl) URL.revokeObjectURL(item.thumbUrl);
    item.thumb = blob;
    item.thumbUrl = URL.createObjectURL(blob);
  }

  function add(source) {
    const added = buildItems(source, source.boxes);
    items.push(...added);
    return added;
  }
  function replaceSource(source, boxes) {
    const at = items.findIndex(item => item.sourceId === source.id);
    const keep = items.filter(item => item.sourceId !== source.id);
    for (const item of itemsOf(source.id)) {
      if (item.thumbUrl) URL.revokeObjectURL(item.thumbUrl);
      rows.delete(item.id);
    }
    const added = buildItems(source, boxes);
    keep.splice(at < 0 ? keep.length : at, 0, ...added);
    items = keep;
    return added;
  }
  return { add, replaceSource, selectedItem, byId, itemsOf, selectItem, renderQueue, updateRow, makeThumb };
}
