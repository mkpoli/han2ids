import { selectElements } from './elements.js';
import { modelInput } from './model-input.js';

export function createReading(deps, els = selectElements(['recognize'])) {
  const READ_DELAY = 280;
  let readTimer = 0;
  let restartTimer = 0;
  let pending = [];
  let modelLoaded = false;
  let loading = false;
  let progress = 0;
  let pumping = false;

  els.recognize.addEventListener('click', () => {
    clearTimeout(readTimer);
    const item = deps.selectedItem();
    if (item) enqueue([item]);
  });

  function scheduleRead(delay = READ_DELAY) {
    clearTimeout(readTimer);
    const item = deps.selectedItem();
    if (!item || deps.isDragging()) return;
    readTimer = setTimeout(() => enqueue([item]), delay);
  }

  function enqueue(items) {
    for (const item of items) {
      item.phase = 'queued';
      item.errorKey = null;
      if (!pending.includes(item.id)) pending.push(item.id);
      deps.touch(item);
    }
    pump();
  }

  let inference = null;

  function loadInference() {
    if (!inference) inference = deps.loadInference();
    return inference;
  }

  async function pump() {
    if (pumping) return;
    pumping = true;
    try {
      while (pending.length) {
        const item = deps.byId(pending.shift());
        if (item) await readItem(item);
      }
    } finally {
      pumping = false;
    }
  }

  async function readItem(item) {
    const seq = ++item.seq;
    item.phase = 'reading';
    item.errorKey = null;
    deps.touch(item);

    const source = deps.getSource(item.sourceId);
    let input;
    try {
      const image = await deps.preparedFor(source);
      if (item.seq !== seq) return;
      input = modelInput(image, item.crop);
      await deps.makeThumb(item, image);
    } catch {
      if (item.seq === seq) fail(item, 'error.cut');
      return;
    }

    const firstLoad = !modelLoaded;
    if (firstLoad) {
      loading = true;
      progress = 0;
      deps.showModelProgress(0);
      if (item.id === deps.selectedItem()?.id) deps.setStatus('status.loading', 'busy');
    }

    try {
      const { recognize } = await loadInference();
      const readings = await recognize(input, {
        onProgress(fraction) {
          if (!firstLoad || !loading) return;
          progress = Math.max(progress, fraction);
          deps.showModelProgress(progress);
        },
      });
      modelLoaded = true;
      loading = false;
      deps.hideModelProgress();
      if (item.seq !== seq) return;
      if (!readings.length) {
        fail(item, 'error.noReading');
        return;
      }
      item.readings = readings;
      item.phase = 'done';
      deps.touch(item);
      if (item.id === deps.selectedItem()?.id) {
        deps.announceReading(readings[0]);
      }
    } catch (error) {
      loading = false;
      deps.hideModelProgress();
      if (item.seq !== seq) return;
      fail(item, error?.name === 'ModelLoadError' || !modelLoaded ? 'error.model' : 'error.read');
    }
  }

  function fail(item, key) {
    item.phase = 'error';
    item.errorKey = key;
    deps.touch(item);
  }


  function discard(item) {
    item.seq += 1;
    item.readings = [];
    item.phase = 'queued';
    item.errorKey = null;
    deps.invalidated(item);
  }

  /** Discards the readings of the given items and, unless `read` is false, reads them again. */
  function restart(items, { delay = READ_DELAY, read = true } = {}) {
    const ids = new Set(items.map(item => item.id));
    pending = pending.filter(id => !ids.has(id));
    for (const item of items) discard(item);
    const selected = deps.selectedItem();
    if (selected && ids.has(selected.id)) clearTimeout(readTimer);
    clearTimeout(restartTimer);
    if (!read) return;
    const first = items.find(item => item.id === selected?.id);
    const order = first ? [first, ...items.filter(item => item !== first)] : items;
    restartTimer = setTimeout(() => enqueue(order.filter(item => deps.byId(item.id))), delay);
  }
  function showError(error) {
    clearTimeout(readTimer);
    loading = false;
    deps.hideModelProgress();
    deps.showError(error);
  }
  return { scheduleRead, enqueue, cropChanged: discard, restart, showError,
    cancelScheduled: () => clearTimeout(readTimer), isLoading: () => loading };

}
