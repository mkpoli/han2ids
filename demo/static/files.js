import { selectElements } from './elements.js';
import { analyseImage } from './detect.js';
import { uid } from './identity.js';

export function createFiles(deps, els = selectElements(['chooseFile', 'fileInput', 'replaceImage', 'stage', 'imageEditor', 'trySample', 'trySheet'])) {
  const sources = new Map();
  const bitmaps = new Map();
  let clock = 0;
  const BITMAPS = 4;

  els.chooseFile.addEventListener('click', () => els.fileInput.click());
  els.replaceImage.addEventListener('click', () => els.fileInput.click());

  els.fileInput.addEventListener('change', () => {
    const [file] = els.fileInput.files;
    els.fileInput.value = '';
    if (file) loadFile(file);
  });

  els.stage.addEventListener('click', event => {
    if (!els.imageEditor.hidden) return;
    if (event.target.closest('button, a, input, label')) return;
    els.fileInput.click();
  });

  async function loadSample(name, label) {
    try {
      const response = await fetch(`./samples/${name}`, { cache: 'no-cache' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      await loadFile(new File([blob], label, { type: blob.type || 'image/png' }));
    } catch {
      deps.onError({ titleKey: 'error.sample.title', detailKey: 'error.sample.detail' });
    }
  }

  els.trySample.addEventListener('click', () => loadSample('sample-yi.png', '疑.png'));
  els.trySheet.addEventListener('click', () => loadSample('sheet-grid.png', 'sheet-grid.png'));

  function hasFiles(event) {
    return [...(event.dataTransfer?.types ?? [])].includes('Files');
  }

  for (const type of ['dragenter', 'dragover']) {
    window.addEventListener(type, event => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      els.stage.classList.add('is-dragover');
    });
  }

  window.addEventListener('dragleave', event => {
    if (!event.relatedTarget) els.stage.classList.remove('is-dragover');
  });

  window.addEventListener('drop', event => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    els.stage.classList.remove('is-dragover');
    const file = [...(event.dataTransfer?.files ?? [])].find(isImageFile);
    if (file) loadFile(file);
  });

  window.addEventListener('paste', event => {
    const data = event.clipboardData;
    if (!data) return;
    const item = [...data.items].find(item => item.type.startsWith('image/'));
    const file = item ? item.getAsFile() : [...data.files].find(isImageFile);
    if (!file) return;
    event.preventDefault();
    loadFile(file);
  });

  function isImageFile(file) {
    return Boolean(file) && (file.type.startsWith('image/') || /\.(png|jpe?g|webp|gif|avif)$/i.test(file.name));
  }

  async function loadFile(file) {
    if (!isImageFile(file)) {
      deps.onError({ titleKey: 'error.imageType.title', detailKey: 'error.imageType.detail' });
      return;
    }

    let source;
    try {
      source = await addSource(file);
    } catch {
      deps.onError({ titleKey: 'error.open.title', detailKey: 'error.open.detail' });
      return;
    }

    deps.onSourceLoaded(source);
  }

  async function addSource(file) {
    const bitmap = await createImageBitmap(file);
    const id = uid();
    const found = analyseImage(bitmap);
    const source = {
      id,
      name: file.name || deps.t('source.pasted'),
      type: file.type || 'image/png',
      blob: file,
      width: bitmap.width,
      height: bitmap.height,
      paper: paperOf(bitmap, found),
      // Black and white, specks and enlarging carry over from the image on the stage; the turn
      // and a hand-set ink level belong to each image.
      prep: { ...deps.currentPrep(), turn: 0, ink: null },
      cut: 0,
      inkBox: found.inkBox,
      boxes: found.boxes,
    };
    keepBitmap(id, bitmap);
    sources.set(id, source);
    return source;
  }

  /** Colour behind a transparent image and in the corners a turn opens up. */
  function paperOf(bitmap, found) {
    if (found.transparent) return found.inkLight ? '#000' : '#fff';
    const scale = Math.min(1, 128 / Math.max(bitmap.width, bitmap.height));
    const w = Math.max(1, Math.round(bitmap.width * scale));
    const h = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    context.drawImage(bitmap, 0, 0, w, h);
    const pixels = context.getImageData(0, 0, w, h).data;
    const border = Math.max(1, Math.round(Math.min(w, h) * 0.02));
    const sum = [0, 0, 0];
    let count = 0;
    for (let y = 0; y < h; y += 1) {
      for (let x = 0; x < w; x += 1) {
        if (x >= border && y >= border && x < w - border && y < h - border) continue;
        const offset = (y * w + x) * 4;
        sum[0] += pixels[offset];
        sum[1] += pixels[offset + 1];
        sum[2] += pixels[offset + 2];
        count += 1;
      }
    }
    const [r, g, b] = sum.map(value => Math.round(value / Math.max(1, count)));
    return `rgb(${r} ${g} ${b})`;
  }

  function keepBitmap(id, bitmap) {
    bitmaps.set(id, { bitmap, used: ++clock });
    while (bitmaps.size > BITMAPS) {
      let oldest = null;
      for (const [key, entry] of bitmaps) {
        if (key === id) continue;
        if (!oldest || entry.used < oldest[1].used) oldest = [key, entry];
      }
      if (!oldest) break;
      oldest[1].bitmap.close?.();
      bitmaps.delete(oldest[0]);
    }
  }

  async function bitmapFor(source) {
    const cached = bitmaps.get(source.id);
    if (cached) {
      cached.used = ++clock;
      return cached.bitmap;
    }
    const bitmap = await createImageBitmap(source.blob);
    keepBitmap(source.id, bitmap);
    return bitmap;
  }

  function updateAnalysis(source, found) {
    source.inkBox = found.inkBox;
    source.boxes = found.boxes;
  }

  return { getSource: id => sources.get(id), bitmapFor, updateAnalysis };
}
