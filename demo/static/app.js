import { DEFAULT_LOCALE, LOCALES, matchLocale } from './i18n.js';
import { analyseImage } from './detect.js';
import { IDC } from './ids.js';

const MIN_CUT = 0.02;
const READ_DELAY = 280;
const THUMB = 96;
const BITMAPS = 4;

const els = {
  fileInput: document.querySelector('#file-input'),
  folderInput: document.querySelector('#folder-input'),
  stage: document.querySelector('#stage'),
  dropEmpty: document.querySelector('#drop-empty'),
  chooseFile: document.querySelector('#choose-file'),
  trySample: document.querySelector('#try-sample'),
  trySheet: document.querySelector('#try-sheet'),
  imageEditor: document.querySelector('#image-editor'),
  imageWrap: document.querySelector('#image-wrap'),
  glyphImage: document.querySelector('#glyph-image'),
  boxLayer: document.querySelector('#box-layer'),
  cropBox: document.querySelector('#crop-box'),
  imageSize: document.querySelector('#image-size'),
  boxCount: document.querySelector('#box-count'),
  cutControls: document.querySelector('#cut-controls'),
  margin: document.querySelector('#margin'),
  marginValue: document.querySelector('#margin-value'),
  quickCut: document.querySelector('#quick-cut'),
  autoCut: document.querySelector('#auto-cut'),
  fullImage: document.querySelector('#full-image'),
  recognize: document.querySelector('#recognize'),
  replaceImage: document.querySelector('#replace-image'),
  queueCard: document.querySelector('#queue-card'),
  queueTotal: document.querySelector('#queue-total'),
  addImages: document.querySelector('#add-images'),
  addFolder: document.querySelector('#add-folder'),
  queueClear: document.querySelector('#queue-clear'),
  queueRun: document.querySelector('#queue-run'),
  queueProgress: document.querySelector('#queue-progress'),
  queueCount: document.querySelector('#queue-count'),
  queueToggle: document.querySelector('#queue-toggle'),
  itemList: document.querySelector('#item-list'),
  itemPrev: document.querySelector('#item-prev'),
  itemNext: document.querySelector('#item-next'),
  queuePosition: document.querySelector('#queue-position'),
  resultCard: document.querySelector('#result-card'),
  readingStatus: document.querySelector('#reading-status'),
  readingStatusText: document.querySelector('#reading-status-text'),
  resultEmpty: document.querySelector('#result-empty'),
  resultBody: document.querySelector('#result-body'),
  idsText: document.querySelector('#ids-text'),
  scoreChip: document.querySelector('#score-chip'),
  validityChip: document.querySelector('#validity-chip'),
  sourceChip: document.querySelector('#source-chip'),
  copyIds: document.querySelector('#copy-ids'),
  openWorkshop: document.querySelector('#open-workshop'),
  candidates: document.querySelector('#candidates'),
  candidateList: document.querySelector('#candidate-list'),
  resultError: document.querySelector('#result-error'),
  errorTitle: document.querySelector('#error-title'),
  errorDetail: document.querySelector('#error-detail'),
  liveStatus: document.querySelector('#live-status'),
  languageMenu: document.querySelector('#language-menu'),
  languageButton: document.querySelector('#language-button'),
  languageList: document.querySelector('#language-list'),
  languageLabel: document.querySelector('#language-label'),
  languageCode: document.querySelector('#language-code'),
  modelLoad: document.querySelector('#model-load'),
  modelProgress: document.querySelector('#model-progress'),
  modelProgressText: document.querySelector('#model-progress-text'),
};

const state = {
  sources: new Map(),
  items: [],
  selectedId: null,
  pending: [],
  run: { total: 0, done: 0 },
  importing: false,
  cancelled: false,
  margin: Number(els.margin.value),
  readTimer: 0,
  drag: null,
  modelLoaded: false,
  loading: false,
  progress: 0,
  copied: false,
};

const rows = new Map();
const bitmaps = new Map();
let clock = 0;
let pumping = false;

function uid() {
  return crypto.randomUUID ? crypto.randomUUID() : `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/* ---------- Theme ---------- */

const themeRadios = [...document.querySelectorAll('input[name="theme"]')];

function storedTheme() {
  try {
    const value = localStorage.getItem('han2ids:theme');
    return value === 'light' || value === 'dark' ? value : 'system';
  } catch {
    return 'system';
  }
}

function applyTheme(theme) {
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  for (const radio of themeRadios) radio.checked = radio.value === theme;
}

for (const radio of themeRadios) {
  radio.addEventListener('change', () => {
    if (!radio.checked) return;
    applyTheme(radio.value);
    try {
      if (radio.value === 'system') localStorage.removeItem('han2ids:theme');
      else localStorage.setItem('han2ids:theme', radio.value);
    } catch {}
  });
}

applyTheme(storedTheme());

/* ---------- Language ---------- */

let locale = DEFAULT_LOCALE;
let messages = LOCALES[locale].messages;

function t(key, params = {}) {
  let text = messages[key] ?? LOCALES[DEFAULT_LOCALE].messages[key] ?? key;
  for (const [name, value] of Object.entries(params)) text = text.split(`{${name}}`).join(String(value));
  return text;
}

function storedLanguage() {
  try {
    return localStorage.getItem('han2ids:lang');
  } catch {
    return null;
  }
}

function initialLocale() {
  const query = new URLSearchParams(location.search).get('lang');
  const candidates = [query, storedLanguage(), ...(navigator.languages ?? []), navigator.language];
  for (const candidate of candidates) {
    const match = matchLocale(candidate);
    if (match) return match;
  }
  return DEFAULT_LOCALE;
}

function setLocale(value, { persist = true } = {}) {
  locale = LOCALES[value] ? value : DEFAULT_LOCALE;
  messages = LOCALES[locale].messages;
  if (persist) {
    try {
      localStorage.setItem('han2ids:lang', locale);
      const url = new URL(location.href);
      url.searchParams.set('lang', locale);
      history.replaceState(null, '', url);
    } catch {}
  }
  applyTranslations();
}

function applyTranslations() {
  document.documentElement.lang = LOCALES[locale].htmlLang;
  document.title = t('meta.title');
  document.querySelector('meta[name="description"]')?.setAttribute('content', t('meta.description'));
  for (const node of document.querySelectorAll('[data-i18n]')) node.textContent = t(node.dataset.i18n);
  for (const node of document.querySelectorAll('[data-i18n-aria]')) node.setAttribute('aria-label', t(node.dataset.i18nAria));
  for (const node of document.querySelectorAll('[data-i18n-title]')) node.title = t(node.dataset.i18nTitle);
  for (const node of document.querySelectorAll('[data-i18n-alt]')) node.alt = t(node.dataset.i18nAlt);
  renderLanguage();
  renderQueue();
  renderStage();
  renderResult();
  renderRun();
  els.liveStatus.textContent = '';
}

function languageOptions() {
  return [...els.languageList.querySelectorAll('[role="option"]')];
}

function selectedLanguageOption() {
  return languageOptions().find(option => option.getAttribute('aria-selected') === 'true');
}

function renderLanguage() {
  const language = LOCALES[locale];
  const label = `${t('language.label')}: ${language.label}`;
  els.languageButton.setAttribute('aria-label', label);
  els.languageButton.title = label;
  els.languageLabel.textContent = language.label;
  els.languageCode.textContent = language.code;
  els.languageList.setAttribute('aria-label', t('language.label'));
  for (const option of languageOptions()) {
    option.setAttribute('aria-selected', String(option.dataset.value === locale));
  }
}

function openLanguage() {
  if (els.languageButton.disabled) return;
  els.languageList.hidden = false;
  els.languageButton.setAttribute('aria-expanded', 'true');
  requestAnimationFrame(() => (selectedLanguageOption() ?? languageOptions()[0])?.focus());
}

function closeLanguage(refocus = false) {
  els.languageList.hidden = true;
  els.languageButton.setAttribute('aria-expanded', 'false');
  if (refocus) els.languageButton.focus();
}

function chooseLanguage(option) {
  if (!option) return;
  setLocale(option.dataset.value);
  closeLanguage(true);
}

els.languageButton.addEventListener('click', () => {
  if (els.languageList.hidden) openLanguage();
  else closeLanguage();
});

els.languageButton.addEventListener('keydown', event => {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    openLanguage();
  } else if (event.key === 'Escape' && !els.languageList.hidden) {
    event.preventDefault();
    closeLanguage(true);
  }
});

els.languageList.addEventListener('keydown', event => {
  const options = languageOptions();
  const at = options.indexOf(document.activeElement);
  if (event.key === 'Escape') {
    event.preventDefault();
    closeLanguage(true);
  } else if (event.key === 'Tab') {
    closeLanguage(true);
  } else if (event.key === 'Home' || event.key === 'End') {
    event.preventDefault();
    options[event.key === 'Home' ? 0 : options.length - 1]?.focus();
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    const step = event.key === 'ArrowDown' ? 1 : -1;
    options[(at + step + options.length) % options.length]?.focus();
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    chooseLanguage(document.activeElement);
  }
});

for (const option of languageOptions()) {
  option.addEventListener('click', () => chooseLanguage(option));
}

document.addEventListener('pointerdown', event => {
  if (!els.languageList.hidden && !els.languageMenu.contains(event.target)) closeLanguage();
});

setLocale(initialLocale(), { persist: false });

/* ---------- Files ---------- */

for (const button of [els.chooseFile, els.replaceImage, els.addImages]) {
  button.addEventListener('click', () => els.fileInput.click());
}
els.addFolder.addEventListener('click', () => els.folderInput.click());

for (const input of [els.fileInput, els.folderInput]) {
  input.addEventListener('change', () => {
    const files = [...input.files];
    input.value = '';
    loadFiles(files);
  });
}

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
    await loadFiles([new File([blob], label, { type: blob.type || 'image/png' })]);
  } catch {
    showError({ titleKey: 'error.sample.title', detailKey: 'error.sample.detail' });
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
  droppedFiles(event.dataTransfer).then(loadFiles);
});

/** Dropped files, walking into folders where the browser exposes them. */
async function droppedFiles(dataTransfer) {
  const entries = [...(dataTransfer?.items ?? [])].map(item => item.webkitGetAsEntry?.()).filter(Boolean);
  if (!entries.length) return [...(dataTransfer?.files ?? [])].filter(isImageFile);
  const out = [];
  for (const entry of entries) await walkEntry(entry, out);
  return out;
}

async function walkEntry(entry, out, depth = 0) {
  if (entry.isFile) {
    const file = await new Promise(resolve => entry.file(resolve, () => resolve(null)));
    if (file && isImageFile(file)) {
      if (entry.fullPath) Object.defineProperty(file, 'relativePath', { value: entry.fullPath.replace(/^\//, '') });
      out.push(file);
    }
    return;
  }
  if (!entry.isDirectory || depth > 8) return;
  const reader = entry.createReader();
  for (;;) {
    const batch = await new Promise(resolve => reader.readEntries(resolve, () => resolve([])));
    if (!batch.length) break;
    for (const child of batch) await walkEntry(child, out, depth + 1);
  }
}

window.addEventListener('paste', event => {
  const data = event.clipboardData;
  if (!data) return;
  const item = [...data.items].find(item => item.type.startsWith('image/'));
  const file = item ? item.getAsFile() : [...data.files].find(isImageFile);
  if (!file) return;
  event.preventDefault();
  loadFiles([file]);
});

function isImageFile(file) {
  return Boolean(file) && (file.type.startsWith('image/') || /\.(png|jpe?g|webp|gif|avif)$/i.test(file.name));
}

async function loadFiles(files) {
  const images = files.filter(isImageFile).sort((first, second) =>
    fileName(first).localeCompare(fileName(second), undefined, { numeric: true, sensitivity: 'base' }));
  if (!images.length) {
    if (files.length) showError({ titleKey: 'error.imageType.title', detailKey: 'error.imageType.detail' });
    return;
  }

  clearError();
  state.cancelled = false;
  state.importing = true;
  renderRun();

  let first = null;
  let failed = 0;
  for (const file of images) {
    if (state.cancelled) break;
    let source;
    try {
      source = await addSource(file);
    } catch {
      failed += 1;
      continue;
    }
    const items = buildItems(source, source.boxes);
    state.items.push(...items);
    if (!first) {
      first = items[0];
      selectItem(first.id);
    }
    renderQueue();
    await thumbnails(source, items);
    enqueue(items);
  }

  state.importing = false;
  renderRun();
  if (!first && failed) showError({ titleKey: 'error.open.title', detailKey: 'error.open.detail' });
}

function fileName(file) {
  return file.relativePath || file.webkitRelativePath || file.name || '';
}

async function addSource(file) {
  const bitmap = await createImageBitmap(file);
  const id = uid();
  const found = analyseImage(bitmap);
  const source = {
    id,
    name: fileName(file) || t('source.pasted'),
    type: file.type || 'image/png',
    blob: file,
    width: bitmap.width,
    height: bitmap.height,
    url: '',
    transparent: found.transparent,
    inkLight: found.inkLight,
    inkBox: found.inkBox,
    boxes: found.boxes,
  };
  keepBitmap(id, bitmap);
  state.sources.set(id, source);
  return source;
}

function sourceUrl(source) {
  if (!source.url) source.url = URL.createObjectURL(source.blob);
  return source.url;
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

/* ---------- Items ---------- */

function buildItems(source, boxes) {
  const list = boxes.length ? boxes : [source.inkBox ?? { x: 0, y: 0, w: 1, h: 1 }];
  return list.map((box, at) => ({
    id: uid(),
    sourceId: source.id,
    index: at + 1,
    box,
    crop: padBox(box, state.margin, source),
    margin: state.margin,
    readings: [],
    phase: 'queued',
    errorKey: null,
    thumb: null,
    thumbUrl: '',
    seq: 0,
  }));
}

function itemsOf(sourceId) {
  return state.items.filter(item => item.sourceId === sourceId);
}

function byId(id) {
  return state.items.find(item => item.id === id) ?? null;
}

function selectedItem() {
  return byId(state.selectedId);
}

function selectItem(id, { scroll = true } = {}) {
  const item = byId(id);
  if (!item) return;
  state.selectedId = id;
  state.copied = false;
  clearTimeout(state.readTimer);
  renderStage();
  renderQueue({ scroll });
  renderResult();
}

function stepSelection(step) {
  if (!state.items.length) return;
  const at = state.items.findIndex(item => item.id === state.selectedId);
  const next = state.items[Math.min(state.items.length - 1, Math.max(0, at + step))];
  if (next) selectItem(next.id);
}

function padBox(box, margin, source) {
  if (!box) return { x: 0, y: 0, w: 1, h: 1 };
  const padding = (margin / 100) * Math.max(box.w * source.width, box.h * source.height);
  return clampCrop({
    x: box.x - padding / source.width,
    y: box.y - padding / source.height,
    w: box.w + (2 * padding) / source.width,
    h: box.h + (2 * padding) / source.height,
  });
}

function clampCrop(crop) {
  const out = {
    x: clamp(crop.x, 0, 1),
    y: clamp(crop.y, 0, 1),
    w: clamp(crop.w, MIN_CUT, 1),
    h: clamp(crop.h, MIN_CUT, 1),
  };
  out.w = Math.min(out.w, 1 - out.x);
  out.h = Math.min(out.h, 1 - out.y);
  if (out.w < MIN_CUT) {
    out.w = MIN_CUT;
    out.x = Math.max(0, 1 - MIN_CUT);
  }
  if (out.h < MIN_CUT) {
    out.h = MIN_CUT;
    out.y = Math.max(0, 1 - MIN_CUT);
  }
  return out;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

/* ---------- The stage ---------- */

function renderStage() {
  const item = selectedItem();
  if (!item) {
    els.imageEditor.hidden = true;
    els.dropEmpty.hidden = false;
    els.cutControls.hidden = true;
    els.imageSize.hidden = true;
    els.boxCount.hidden = true;
    els.boxLayer.replaceChildren();
    return;
  }

  const source = state.sources.get(item.sourceId);
  if (els.glyphImage.dataset.source !== source.id) {
    els.glyphImage.src = sourceUrl(source);
    els.glyphImage.dataset.source = source.id;
  }
  els.imageEditor.hidden = false;
  els.dropEmpty.hidden = true;
  els.cutControls.hidden = false;
  els.imageSize.hidden = false;
  els.imageSize.textContent = `${source.width} × ${source.height}`;
  const count = itemsOf(source.id).length;
  els.boxCount.hidden = count < 2;
  els.boxCount.textContent = t('quick.boxes', { count });
  els.imageWrap.toggleAttribute('data-many', count > 1);
  els.imageWrap.style.setProperty('--image-bg', source.transparent && source.inkLight ? '#000' : '#fff');
  els.margin.value = String(item.margin);
  els.marginValue.textContent = `${item.margin}%`;
  renderBoxes();
  renderCrop();
}

function renderBoxes() {
  const item = selectedItem();
  const list = item ? itemsOf(item.sourceId) : [];
  if (list.length < 2) {
    els.boxLayer.replaceChildren();
    return;
  }
  els.boxLayer.replaceChildren(...list.map(entry => {
    const box = document.createElement('button');
    box.type = 'button';
    box.className = 'glyph-box';
    box.tabIndex = -1;
    box.dataset.id = entry.id;
    box.dataset.state = entry.phase;
    if (entry.id === item.id) box.dataset.selected = 'true';
    box.style.insetInlineStart = `${entry.crop.x * 100}%`;
    box.style.insetBlockStart = `${entry.crop.y * 100}%`;
    box.style.inlineSize = `${entry.crop.w * 100}%`;
    box.style.blockSize = `${entry.crop.h * 100}%`;
    const number = document.createElement('span');
    number.className = 'glyph-box-number';
    number.textContent = String(entry.index);
    box.append(number);
    return box;
  }));
}

els.boxLayer.addEventListener('click', event => {
  const box = event.target.closest('[data-id]');
  if (box) selectItem(box.dataset.id);
});

function renderCrop() {
  const item = selectedItem();
  if (!item) return;
  const { x, y, w, h } = item.crop;
  els.imageWrap.style.setProperty('--cut-x', `${x * 100}%`);
  els.imageWrap.style.setProperty('--cut-y', `${y * 100}%`);
  els.imageWrap.style.setProperty('--cut-w', `${w * 100}%`);
  els.imageWrap.style.setProperty('--cut-h', `${h * 100}%`);
}

function setCrop(crop, delay = READ_DELAY) {
  const item = selectedItem();
  if (!item) return;
  const next = clampCrop(crop);
  const changed = ['x', 'y', 'w', 'h'].some(key => next[key] !== item.crop[key]);
  item.crop = next;
  if (changed) {
    item.seq += 1;
    item.readings = [];
    item.phase = 'queued';
    item.errorKey = null;
    if (item.id === state.selectedId) {
      state.copied = false;
      touch(item);
    }
  }
  renderCrop();
  scheduleRead(delay);
}

/* ---------- Pointer and keyboard crop controls ---------- */

els.cropBox.addEventListener('pointerdown', event => {
  if (event.button !== 0 || !selectedItem() || state.drag) return;
  const handle = event.target.closest('[data-handle]');
  const rect = els.imageWrap.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  state.drag = {
    mode: handle ? handle.dataset.handle : 'move',
    startX: (event.clientX - rect.left) / rect.width,
    startY: (event.clientY - rect.top) / rect.height,
    crop: { ...selectedItem().crop },
    moved: false,
    target: handle ?? els.cropBox,
    pointerId: event.pointerId,
  };
  state.drag.target.setPointerCapture?.(event.pointerId);
  els.imageWrap.classList.add('is-cropping');
  els.cropBox.focus({ preventScroll: true });
  clearTimeout(state.readTimer);
  event.preventDefault();
});

window.addEventListener('pointermove', event => {
  const drag = state.drag;
  const item = selectedItem();
  if (!drag || !item || event.pointerId !== drag.pointerId) return;
  const rect = els.imageWrap.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  const x = clamp((event.clientX - rect.left) / rect.width, 0, 1);
  const y = clamp((event.clientY - rect.top) / rect.height, 0, 1);
  const dx = x - drag.startX;
  const dy = y - drag.startY;
  const start = drag.crop;
  let next = { ...start };

  if (drag.mode === 'move') {
    next.x = clamp(start.x + dx, 0, 1 - start.w);
    next.y = clamp(start.y + dy, 0, 1 - start.h);
  } else {
    let left = start.x;
    let top = start.y;
    let right = start.x + start.w;
    let bottom = start.y + start.h;
    if (drag.mode.includes('w')) left = clamp(x, 0, right - MIN_CUT);
    if (drag.mode.includes('e')) right = clamp(x, left + MIN_CUT, 1);
    if (drag.mode.includes('n')) top = clamp(y, 0, bottom - MIN_CUT);
    if (drag.mode.includes('s')) bottom = clamp(y, top + MIN_CUT, 1);
    next = { x: left, y: top, w: right - left, h: bottom - top };
  }

  item.crop = next;
  state.drag.moved = true;
  renderCrop();
  event.preventDefault();
});

function endDrag(event) {
  if (!state.drag || event.pointerId !== state.drag.pointerId) return;
  const { target, pointerId, moved } = state.drag;
  state.drag = null;
  if (target.hasPointerCapture?.(pointerId)) target.releasePointerCapture(pointerId);
  els.imageWrap.classList.remove('is-cropping');
  if (moved) scheduleRead();
}

window.addEventListener('pointerup', endDrag);
window.addEventListener('pointercancel', endDrag);
els.cropBox.addEventListener('lostpointercapture', endDrag);

els.cropBox.addEventListener('keydown', event => {
  const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'];
  const item = selectedItem();
  if (!item || !keys.includes(event.key)) return;

  const step = event.shiftKey ? 0.02 : 0.005;
  const crop = { ...item.crop };

  if (event.shiftKey) {
    if (event.key === 'ArrowLeft') crop.w = Math.max(MIN_CUT, crop.w - step);
    if (event.key === 'ArrowRight') crop.w = Math.min(1 - crop.x, crop.w + step);
    if (event.key === 'ArrowUp') crop.h = Math.max(MIN_CUT, crop.h - step);
    if (event.key === 'ArrowDown') crop.h = Math.min(1 - crop.y, crop.h + step);
  } else {
    if (event.key === 'ArrowLeft') crop.x = Math.max(0, crop.x - step);
    if (event.key === 'ArrowRight') crop.x = Math.min(1 - crop.w, crop.x + step);
    if (event.key === 'ArrowUp') crop.y = Math.max(0, crop.y - step);
    if (event.key === 'ArrowDown') crop.y = Math.min(1 - crop.h, crop.y + step);
  }

  event.preventDefault();
  setCrop(crop);
});

/* ---------- Cut controls ---------- */

els.margin.addEventListener('input', () => {
  state.margin = Number(els.margin.value);
  els.marginValue.textContent = `${state.margin}%`;
  const item = selectedItem();
  if (!item) return;
  item.margin = state.margin;
  const source = state.sources.get(item.sourceId);
  setCrop(padBox(item.box, item.margin, source));
});

els.quickCut.addEventListener('click', () => quickCut());

els.autoCut.addEventListener('click', () => {
  const item = selectedItem();
  if (!item) return;
  const source = state.sources.get(item.sourceId);
  setCrop(padBox(item.box, item.margin, source), 0);
});

els.fullImage.addEventListener('click', () => {
  if (!selectedItem()) return;
  setCrop({ x: 0, y: 0, w: 1, h: 1 }, 0);
});

els.recognize.addEventListener('click', () => {
  clearTimeout(state.readTimer);
  const item = selectedItem();
  if (item) enqueue([item]);
});

async function quickCut() {
  const current = selectedItem();
  if (!current) return;
  const source = state.sources.get(current.sourceId);
  let found;
  try {
    found = analyseImage(await bitmapFor(source));
  } catch {
    showError({ titleKey: 'error.cut.title', detailKey: 'error.cut.detail' });
    return;
  }
  if (!found.boxes.length) {
    showError({ titleKey: 'error.detect.title', detailKey: 'error.detect.detail' });
    return;
  }

  clearError();
  source.inkBox = found.inkBox;
  source.boxes = found.boxes;
  source.transparent = found.transparent;
  source.inkLight = found.inkLight;

  const at = state.items.findIndex(item => item.sourceId === source.id);
  const keep = state.items.filter(item => item.sourceId !== source.id);
  for (const item of itemsOf(source.id)) dropItem(item);
  const items = buildItems(source, found.boxes);
  keep.splice(at < 0 ? keep.length : at, 0, ...items);
  state.items = keep;
  selectItem(items[0].id);
  renderQueue();
  await thumbnails(source, items);
  enqueue(items);
}

function dropItem(item) {
  if (item.thumbUrl) URL.revokeObjectURL(item.thumbUrl);
  rows.delete(item.id);
}

/* ---------- The item list ---------- */

function renderQueue({ scroll = false } = {}) {
  els.queueCard.hidden = state.items.length === 0;
  els.queueTotal.textContent = String(state.items.length);

  const seen = new Set();
  const list = state.items.map(item => {
    seen.add(item.id);
    return rows.get(item.id) ?? makeRow(item);
  });
  for (const id of [...rows.keys()]) if (!seen.has(id)) rows.delete(id);
  els.itemList.replaceChildren(...list);
  for (const item of state.items) updateRow(item);

  const at = state.items.findIndex(item => item.id === state.selectedId);
  els.queuePosition.textContent = at < 0 ? '' : `${at + 1} / ${state.items.length}`;
  els.itemPrev.disabled = at <= 0;
  els.itemNext.disabled = at < 0 || at >= state.items.length - 1;
  if (scroll && at >= 0) rows.get(state.selectedId)?.scrollIntoView({ block: 'nearest' });
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
  const selected = item.id === state.selectedId;
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

  const source = state.sources.get(item.sourceId);
  const label = itemsOf(item.sourceId).length > 1 ? `${source.name} · ${item.index}` : source.name;
  row.querySelector('.item-source').textContent = label;

  const mark = row.querySelector('.item-state');
  mark.dataset.state = item.phase;
  mark.title = t(`state.${item.phase}`);
  mark.setAttribute('aria-label', t(`state.${item.phase}`));
}

els.itemList.addEventListener('click', event => {
  const row = event.target.closest('[data-id]');
  if (row) selectItem(row.dataset.id, { scroll: false });
});

els.itemList.addEventListener('keydown', event => {
  const keys = { ArrowDown: 1, ArrowUp: -1, Home: 'first', End: 'last' };
  if (!(event.key in keys) || !state.items.length) return;
  event.preventDefault();
  const step = keys[event.key];
  if (step === 'first') selectItem(state.items[0].id);
  else if (step === 'last') selectItem(state.items[state.items.length - 1].id);
  else stepSelection(step);
  rows.get(state.selectedId)?.focus({ preventScroll: true });
});

els.itemPrev.addEventListener('click', () => stepSelection(-1));
els.itemNext.addEventListener('click', () => stepSelection(1));

/* ---------- Reading ---------- */

function scheduleRead(delay = READ_DELAY) {
  clearTimeout(state.readTimer);
  const item = selectedItem();
  if (!item || state.drag) return;
  state.readTimer = setTimeout(() => enqueue([item]), delay);
}

function enqueue(items) {
  state.cancelled = false;
  for (const item of items) {
    item.phase = 'queued';
    item.errorKey = null;
    if (state.pending.includes(item.id)) continue;
    state.pending.push(item.id);
    state.run.total += 1;
    touch(item);
  }
  renderRun();
  pump();
}

function cancelRun() {
  state.cancelled = true;
  state.pending.length = 0;
  renderRun();
}

function readQueued() {
  const waiting = state.items.filter(item => item.phase === 'queued' || item.phase === 'error');
  if (!waiting.length) return;
  state.run = { total: 0, done: 0 };
  enqueue(waiting);
}

function renderRun() {
  const waiting = state.items.some(item => item.phase === 'queued');
  const active = pumping || state.importing;
  els.queueRun.hidden = !active && !waiting;
  if (els.queueRun.hidden) return;
  const { done, total } = state.run;
  els.queueProgress.style.setProperty('--ui-progress', `${total ? Math.round((done / total) * 100) : 0}%`);
  els.queueCount.textContent = total ? `${done} / ${total}` : '';
  els.queueToggle.textContent = active ? t('queue.cancel') : t('queue.read');
}

els.queueToggle.addEventListener('click', () => {
  if (pumping || state.importing) cancelRun();
  else readQueued();
});

els.queueClear.addEventListener('click', () => clearAll());

function clearAll() {
  cancelRun();
  for (const item of state.items) dropItem(item);
  for (const source of state.sources.values()) if (source.url) URL.revokeObjectURL(source.url);
  for (const entry of bitmaps.values()) entry.bitmap.close?.();
  bitmaps.clear();
  state.items = [];
  state.sources.clear();
  state.selectedId = null;
  state.run = { total: 0, done: 0 };
  els.glyphImage.removeAttribute('src');
  delete els.glyphImage.dataset.source;
  clearError();
  renderStage();
  renderQueue();
  renderResult();
  renderRun();
}

let inference = null;

function loadInference() {
  if (!inference) inference = import('./inference.js');
  return inference;
}

async function pump() {
  if (pumping) return;
  pumping = true;
  renderRun();
  try {
    while (state.pending.length && !state.cancelled) {
      const item = byId(state.pending.shift());
      if (!item) continue;
      await readItem(item);
      state.run.done += 1;
      renderRun();
    }
  } finally {
    pumping = false;
    if (!state.pending.length && !state.importing) state.run = { total: 0, done: 0 };
    renderRun();
  }
}

async function readItem(item) {
  const seq = ++item.seq;
  item.phase = 'reading';
  item.errorKey = null;
  touch(item);

  const source = state.sources.get(item.sourceId);
  let input;
  try {
    const bitmap = await bitmapFor(source);
    if (item.seq !== seq) return;
    input = modelInput(bitmap, source, item.crop);
    await makeThumb(item, bitmap, source);
  } catch {
    if (item.seq === seq) fail(item, 'error.cut');
    return;
  }

  const firstLoad = !state.modelLoaded;
  if (firstLoad) {
    state.loading = true;
    state.progress = 0;
    showModelProgress(0);
    if (item.id === state.selectedId) setStatus('status.loading', 'busy');
  }

  try {
    const { recognize } = await loadInference();
    const readings = await recognize(input, {
      onProgress(fraction) {
        if (!firstLoad || !state.loading) return;
        state.progress = Math.max(state.progress, fraction);
        showModelProgress(state.progress);
      },
    });
    state.modelLoaded = true;
    state.loading = false;
    hideModelProgress();
    if (item.seq !== seq) return;
    if (!readings.length) {
      fail(item, 'error.noReading');
      return;
    }
    item.readings = readings;
    item.phase = 'done';
    touch(item);
    if (item.id === state.selectedId) {
      els.liveStatus.textContent = t('live.read', {
        ids: readings[0].ids,
        score: (Math.round(readings[0].score * 1000) / 10).toFixed(1),
      });
    }
  } catch (error) {
    state.loading = false;
    hideModelProgress();
    if (item.seq !== seq) return;
    fail(item, error?.name === 'ModelLoadError' || !state.modelLoaded ? 'error.model' : 'error.read');
  }
}

function fail(item, key) {
  item.phase = 'error';
  item.errorKey = key;
  touch(item);
}

function touch(item) {
  updateRow(item);
  renderBoxes();
  if (item.id === state.selectedId) renderResult();
}

function modelInput(bitmap, source, crop) {
  const naturalWidth = source.width;
  const naturalHeight = source.height;
  const { x, y, w, h } = crop;

  const sx = clamp(Math.floor(x * naturalWidth), 0, naturalWidth - 1);
  const sy = clamp(Math.floor(y * naturalHeight), 0, naturalHeight - 1);
  const ex = clamp(Math.ceil((x + w) * naturalWidth), sx + 1, naturalWidth);
  const ey = clamp(Math.ceil((y + h) * naturalHeight), sy + 1, naturalHeight);
  const sourceWidth = ex - sx;
  const sourceHeight = ey - sy;
  const scale = 224 / Math.max(sourceWidth, sourceHeight);
  const width = Math.max(1, Math.round(sourceWidth * scale));
  const height = Math.max(1, Math.round(sourceHeight * scale));

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = 'high';
  context.fillStyle = background(source);
  context.fillRect(0, 0, width, height);
  context.drawImage(bitmap, sx, sy, sourceWidth, sourceHeight, 0, 0, width, height);
  const pixels = context.getImageData(0, 0, width, height).data;

  const gray = new Float32Array(width * height);
  let mean = 0;
  for (let index = 0; index < gray.length; index += 1) {
    const offset = index * 4;
    const value = 0.299 * pixels[offset] + 0.587 * pixels[offset + 1] + 0.114 * pixels[offset + 2];
    gray[index] = value;
    mean += value;
  }
  const invert = mean / gray.length < 127;
  const data = new Float32Array(3 * 224 * 224);
  data.fill(1);
  const left = Math.floor((224 - width) / 2);
  const top = Math.floor((224 - height) / 2);
  for (let row = 0; row < height; row += 1) {
    for (let column = 0; column < width; column += 1) {
      let value = gray[row * width + column];
      if (invert) value = 255 - value;
      const normalized = (value / 255 - 0.5) / 0.5;
      const target = (top + row) * 224 + left + column;
      data[target] = normalized;
      data[224 * 224 + target] = normalized;
      data[2 * 224 * 224 + target] = normalized;
    }
  }
  return data;
}

function background(source) {
  return source.transparent && source.inkLight ? '#000' : '#fff';
}

async function thumbnails(source, items) {
  let bitmap;
  try {
    bitmap = await bitmapFor(source);
  } catch {
    return;
  }
  for (const item of items) {
    await makeThumb(item, bitmap, source);
    updateRow(item);
  }
}

async function makeThumb(item, bitmap, source) {
  const sx = Math.max(0, Math.floor(item.crop.x * source.width));
  const sy = Math.max(0, Math.floor(item.crop.y * source.height));
  const sw = Math.max(1, Math.round(item.crop.w * source.width));
  const sh = Math.max(1, Math.round(item.crop.h * source.height));
  const scale = Math.min(1, THUMB / Math.max(sw, sh));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(sw * scale));
  canvas.height = Math.max(1, Math.round(sh * scale));
  const context = canvas.getContext('2d');
  context.fillStyle = background(source);
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(bitmap, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
  if (!blob) return;
  if (item.thumbUrl) URL.revokeObjectURL(item.thumbUrl);
  item.thumb = blob;
  item.thumbUrl = URL.createObjectURL(blob);
}

function showModelProgress(fraction) {
  els.modelLoad.hidden = false;
  const percent = Math.round(clamp(fraction, 0, 1) * 100);
  els.modelProgress.style.setProperty('--ui-progress', `${percent}%`);
  els.modelProgressText.textContent = `${percent}%`;
}

function hideModelProgress() {
  els.modelLoad.hidden = true;
}

/* ---------- The reading ---------- */

function renderResult() {
  const item = selectedItem();
  if (!item) {
    els.resultEmpty.hidden = false;
    els.resultBody.hidden = true;
    els.resultError.hidden = true;
    els.readingStatus.hidden = true;
    els.candidates.hidden = true;
    els.idsText.replaceChildren();
    return;
  }

  const reading = item.readings[0];
  els.resultBody.hidden = !reading;
  els.resultEmpty.hidden = Boolean(reading) || item.phase === 'error';
  els.resultError.hidden = item.phase !== 'error';
  els.resultCard.setAttribute('aria-busy', String(item.phase === 'reading'));

  if (item.phase === 'error' && item.errorKey) {
    els.errorTitle.textContent = t(`${item.errorKey}.title`);
    els.errorDetail.textContent = t(`${item.errorKey}.detail`);
  }

  if (reading) {
    renderIds(els.idsText, reading.ids);
    els.openWorkshop.href = `https://ids.mkpo.li/?ids=${encodeURIComponent(reading.ids)}`;
    const score = Math.round(reading.score * 1000) / 10;
    els.scoreChip.textContent = t('reading.score', { value: score.toFixed(1) });
    els.scoreChip.title = t('reading.scoreHint');
    els.validityChip.textContent = reading.valid ? t('reading.valid') : t('reading.invalid');
    els.validityChip.dataset.variant = reading.valid ? 'accent' : 'danger';
    els.copyIds.textContent = state.copied ? t('reading.copied') : t('reading.copy');

    const source = state.sources.get(item.sourceId);
    els.sourceChip.hidden = false;
    els.sourceChip.textContent = itemsOf(item.sourceId).length > 1
      ? `${source.name} · ${item.index}`
      : source.name;
    els.sourceChip.title = source.name;

    const alternatives = item.readings.slice(1);
    els.candidateList.replaceChildren(...alternatives.map(candidateRow));
    els.candidates.hidden = alternatives.length === 0;
  } else {
    els.sourceChip.hidden = true;
    els.candidates.hidden = true;
  }

  if (item.phase === 'reading') setStatus(state.loading ? 'status.loading' : 'status.reading', 'busy');
  else if (item.phase === 'error') setStatus('status.error', 'error');
  else if (item.phase === 'queued') setStatus('status.queued', 'idle');
  else setStatus('status.ready', 'idle');
}

function candidateRow(reading, index) {
  const row = document.createElement('li');
  row.className = 'ui-list-row';

  const rank = document.createElement('span');
  rank.className = 'candidate-rank';
  rank.textContent = String(index + 2);

  const ids = document.createElement('span');
  ids.className = 'candidate-ids';
  ids.title = reading.ids;
  renderIds(ids, reading.ids);

  const score = document.createElement('span');
  score.className = 'ui-list-row-note';
  score.textContent = `${(reading.score * 100).toFixed(1)}%`;

  row.append(rank, ids, score);
  return row;
}

function renderIds(element, text) {
  const fragment = document.createDocumentFragment();
  let buffer = '';
  for (const char of text) {
    if (IDC.test(char)) {
      if (buffer) fragment.append(document.createTextNode(buffer));
      buffer = '';
      const span = document.createElement('span');
      span.className = 'idc';
      span.textContent = char;
      fragment.append(span);
    } else {
      buffer += char;
    }
  }
  if (buffer) fragment.append(document.createTextNode(buffer));
  element.replaceChildren(fragment);
}

function setStatus(key, kind) {
  els.readingStatus.hidden = false;
  els.readingStatus.dataset.state = kind;
  els.readingStatusText.textContent = t(key);
}

function clearError() {
  els.resultError.hidden = true;
}

function showError({ titleKey, detailKey }) {
  clearTimeout(state.readTimer);
  state.loading = false;
  hideModelProgress();
  els.resultError.hidden = false;
  els.errorTitle.textContent = t(titleKey);
  els.errorDetail.textContent = t(detailKey);
  setStatus('status.error', 'error');
  els.liveStatus.textContent = t(titleKey);
}

/* ---------- Copy ---------- */

els.copyIds.addEventListener('click', async () => {
  const reading = selectedItem()?.readings[0];
  if (!reading) return;
  try {
    await navigator.clipboard.writeText(reading.ids);
  } catch {
    const area = document.createElement('textarea');
    area.value = reading.ids;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.append(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  }
  state.copied = true;
  renderResult();
  els.liveStatus.textContent = t('live.copied');
  setTimeout(() => {
    state.copied = false;
    renderResult();
  }, 1600);
});
