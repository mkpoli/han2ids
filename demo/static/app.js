import { DEFAULT_LOCALE, LOCALES, matchLocale } from './i18n.js';

const MIN_CUT = 0.02;
const READ_DELAY = 280;

const els = {
  fileInput: document.querySelector('#file-input'),
  stage: document.querySelector('#stage'),
  dropEmpty: document.querySelector('#drop-empty'),
  chooseFile: document.querySelector('#choose-file'),
  trySample: document.querySelector('#try-sample'),
  imageEditor: document.querySelector('#image-editor'),
  imageWrap: document.querySelector('#image-wrap'),
  glyphImage: document.querySelector('#glyph-image'),
  cropBox: document.querySelector('#crop-box'),
  imageSize: document.querySelector('#image-size'),
  cutControls: document.querySelector('#cut-controls'),
  margin: document.querySelector('#margin'),
  marginValue: document.querySelector('#margin-value'),
  autoCut: document.querySelector('#auto-cut'),
  fullImage: document.querySelector('#full-image'),
  recognize: document.querySelector('#recognize'),
  replaceImage: document.querySelector('#replace-image'),
  resultCard: document.querySelector('#result-card'),
  readingStatus: document.querySelector('#reading-status'),
  readingStatusText: document.querySelector('#reading-status-text'),
  resultEmpty: document.querySelector('#result-empty'),
  resultBody: document.querySelector('#result-body'),
  idsText: document.querySelector('#ids-text'),
  scoreChip: document.querySelector('#score-chip'),
  validityChip: document.querySelector('#validity-chip'),
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

const IDC = /[\u2FF0-\u2FFF\u303E\u31EF]/;

const state = {
  imageUrl: '',
  natural: { width: 0, height: 0 },
  crop: { x: 0, y: 0, w: 1, h: 1 },
  inkBox: null,
  transparent: false,
  inkLight: false,
  margin: Number(els.margin.value),
  readings: [],
  requestSeq: 0,
  readTimer: 0,
  drag: null,
  busy: false,
  loading: false,
  modelLoaded: false,
  progress: 0,
  running: false,
  queued: false,
  copied: false,
  error: null,
};

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
  refreshStatus();
  if (state.readings.length) updateReadingMeta();
  if (state.error) {
    els.errorTitle.textContent = t(state.error.titleKey);
    els.errorDetail.textContent = t(state.error.detailKey);
  }
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

/* ---------- Image input ---------- */

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

els.trySample.addEventListener('click', async () => {
  try {
    const response = await fetch('./samples/sample-yi.png', { cache: 'no-cache' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    await loadFile(new File([blob], '疑.png', { type: blob.type || 'image/png' }));
  } catch {
    showError({ titleKey: 'error.sample.title', detailKey: 'error.sample.detail' });
  }
});

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
    showError({ titleKey: 'error.imageType.title', detailKey: 'error.imageType.detail' });
    return;
  }

  state.requestSeq += 1;
  clearTimeout(state.readTimer);
  setBusy(false);

  const url = URL.createObjectURL(file);
  const probe = new Image();
  probe.src = url;
  try {
    await probe.decode();
  } catch {
    URL.revokeObjectURL(url);
    showError({ titleKey: 'error.open.title', detailKey: 'error.open.detail' });
    return;
  }

  els.glyphImage.src = url;
  try {
    await els.glyphImage.decode();
  } catch {
    URL.revokeObjectURL(url);
    showError({ titleKey: 'error.open.title', detailKey: 'error.open.detail' });
    return;
  }
  if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
  state.imageUrl = url;
  state.natural = { width: els.glyphImage.naturalWidth, height: els.glyphImage.naturalHeight };

  els.imageEditor.hidden = false;
  els.dropEmpty.hidden = true;
  els.cutControls.hidden = false;
  els.imageSize.hidden = false;
  els.imageSize.textContent = `${state.natural.width} × ${state.natural.height}`;
  els.margin.value = String(state.margin);
  els.marginValue.textContent = `${state.margin}%`;

  resetResult();
  state.transparent = false;
  state.inkLight = false;
  updateImageBackground();

  state.inkBox = analyseInk(els.glyphImage);
  applyAutoCut(0);
  scheduleRead(80);
}

/* ---------- Ink detection and the cut ---------- */

function analyseInk(image) {
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  state.transparent = false;
  state.inkLight = false;
  if (!width || !height) return null;

  const scale = Math.min(1, 700 / Math.max(width, height));
  const w = Math.max(1, Math.round(width * scale));
  const h = Math.max(1, Math.round(height * scale));
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.drawImage(image, 0, 0, w, h);
  const pixels = context.getImageData(0, 0, w, h).data;

  const border = Math.max(1, Math.round(Math.min(w, h) * 0.02));
  let borderCount = 0;
  let borderOpaque = 0;
  let borderLuma = 0;
  const histogram = new Uint32Array(256);
  let histogramCount = 0;

  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const offset = (y * w + x) * 4;
      const alpha = pixels[offset + 3];
      const luma = Math.round(0.2126 * pixels[offset] + 0.7152 * pixels[offset + 1] + 0.0722 * pixels[offset + 2]);
      const onBorder = x < border || y < border || x >= w - border || y >= h - border;
      if (onBorder) {
        borderCount += 1;
        if (alpha > 32) {
          borderOpaque += 1;
          borderLuma += luma;
        }
      }
      if (alpha > 16) {
        histogram[luma] += 1;
        histogramCount += 1;
      }
    }
  }

  const transparentBackground = borderCount > 0 && borderOpaque / borderCount < 0.6;
  const threshold = otsu(histogram, histogramCount);
  const backgroundLuma = borderOpaque ? borderLuma / borderOpaque : 255;
  const brightBackground = backgroundLuma >= threshold;

  let left = w;
  let top = h;
  let right = -1;
  let bottom = -1;
  let inkLuma = 0;
  let inkCount = 0;

  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const offset = (y * w + x) * 4;
      const alpha = pixels[offset + 3];
      if (alpha <= 32) continue;
      const luma = 0.2126 * pixels[offset] + 0.7152 * pixels[offset + 1] + 0.0722 * pixels[offset + 2];
      const ink = transparentBackground ? true : brightBackground ? luma <= threshold : luma >= threshold;
      if (!ink) continue;
      if (x < left) left = x;
      if (x > right) right = x;
      if (y < top) top = y;
      if (y > bottom) bottom = y;
      inkLuma += luma;
      inkCount += 1;
    }
  }

  if (right < left || bottom < top) {
    updateImageBackground();
    return null;
  }

  state.transparent = transparentBackground;
  state.inkLight = inkCount > 0 && inkLuma / inkCount > 127;
  updateImageBackground();

  return {
    x: left / w,
    y: top / h,
    w: (right - left + 1) / w,
    h: (bottom - top + 1) / h,
  };
}

function updateImageBackground() {
  els.imageWrap.style.setProperty('--image-bg', state.transparent && state.inkLight ? '#000' : '#fff');
}

function otsu(histogram, total) {
  if (!total) return 127;
  let sum = 0;
  for (let value = 0; value < 256; value += 1) sum += value * histogram[value];

  let weightBackground = 0;
  let sumBackground = 0;
  let best = -1;
  let threshold = 127;

  for (let value = 0; value < 256; value += 1) {
    weightBackground += histogram[value];
    if (!weightBackground) continue;
    const weightForeground = total - weightBackground;
    if (!weightForeground) break;
    sumBackground += value * histogram[value];
    const meanBackground = sumBackground / weightBackground;
    const meanForeground = (sum - sumBackground) / weightForeground;
    const between = weightBackground * weightForeground * (meanBackground - meanForeground) ** 2;
    if (between > best) {
      best = between;
      threshold = value;
    }
  }
  return threshold;
}

function applyAutoCut(delay = READ_DELAY) {
  if (!state.inkBox) {
    setCrop({ x: 0, y: 0, w: 1, h: 1 }, delay);
    return;
  }

  const box = state.inkBox;
  const padding = (state.margin / 100) * Math.max(box.w * state.natural.width, box.h * state.natural.height);
  const padX = padding / state.natural.width;
  const padY = padding / state.natural.height;

  setCrop({
    x: box.x - padX,
    y: box.y - padY,
    w: box.w + 2 * padX,
    h: box.h + 2 * padY,
  }, delay);
}

function setCrop(crop, delay = READ_DELAY) {
  state.crop = {
    x: clamp(crop.x, 0, 1),
    y: clamp(crop.y, 0, 1),
    w: clamp(crop.w, MIN_CUT, 1),
    h: clamp(crop.h, MIN_CUT, 1),
  };
  state.crop.w = Math.min(state.crop.w, 1 - state.crop.x);
  state.crop.h = Math.min(state.crop.h, 1 - state.crop.y);
  if (state.crop.w < MIN_CUT) {
    state.crop.w = MIN_CUT;
    state.crop.x = Math.max(0, 1 - MIN_CUT);
  }
  if (state.crop.h < MIN_CUT) {
    state.crop.h = MIN_CUT;
    state.crop.y = Math.max(0, 1 - MIN_CUT);
  }
  renderCrop();
  scheduleRead(delay);
}

function renderCrop() {
  const { x, y, w, h } = state.crop;
  els.imageWrap.style.setProperty('--cut-x', `${x * 100}%`);
  els.imageWrap.style.setProperty('--cut-y', `${y * 100}%`);
  els.imageWrap.style.setProperty('--cut-w', `${w * 100}%`);
  els.imageWrap.style.setProperty('--cut-h', `${h * 100}%`);
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

/* ---------- Pointer and keyboard crop controls ---------- */

els.cropBox.addEventListener('pointerdown', event => {
  if (event.button !== 0 || !state.natural.width) return;
  const handle = event.target.closest('[data-handle]');
  const rect = els.imageWrap.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  state.drag = {
    mode: handle ? handle.dataset.handle : 'move',
    startX: (event.clientX - rect.left) / rect.width,
    startY: (event.clientY - rect.top) / rect.height,
    crop: { ...state.crop },
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
  if (!drag) return;
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

  state.crop = next;
  state.drag.moved = true;
  renderCrop();
  event.preventDefault();
});

function endDrag() {
  if (!state.drag) return;
  const { target, pointerId, moved } = state.drag;
  target.releasePointerCapture?.(pointerId);
  state.drag = null;
  els.imageWrap.classList.remove('is-cropping');
  if (moved) scheduleRead();
}

window.addEventListener('pointerup', endDrag);
window.addEventListener('pointercancel', endDrag);

els.cropBox.addEventListener('keydown', event => {
  const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'];
  if (!keys.includes(event.key)) return;

  const step = event.shiftKey ? 0.02 : 0.005;
  const crop = { ...state.crop };

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
  if (state.natural.width) applyAutoCut();
});

els.autoCut.addEventListener('click', () => {
  if (!state.natural.width) return;
  state.inkBox = analyseInk(els.glyphImage);
  applyAutoCut(0);
});

els.fullImage.addEventListener('click', () => {
  if (!state.natural.width) return;
  setCrop({ x: 0, y: 0, w: 1, h: 1 }, 0);
});

els.recognize.addEventListener('click', () => {
  clearTimeout(state.readTimer);
  readNow();
});

/* ---------- Reading ---------- */

function scheduleRead(delay = READ_DELAY) {
  clearTimeout(state.readTimer);
  if (!state.natural.width) return;
  state.readTimer = setTimeout(readNow, delay);
}

let inference = null;

function loadInference() {
  if (!inference) inference = import('./inference.js');
  return inference;
}

async function readNow() {
  if (!state.natural.width) return;
  if (state.running) {
    state.queued = true;
    return;
  }

  state.running = true;
  const request = ++state.requestSeq;
  setBusy(true);
  clearError();

  let input;
  try {
    input = makeModelInput();
  } catch {
    state.running = false;
    showError({ titleKey: 'error.cut.title', detailKey: 'error.cut.detail' });
    return;
  }

  const firstLoad = !state.modelLoaded;
  if (firstLoad) {
    state.loading = true;
    state.progress = 0;
    showModelProgress(0);
    setStatus('status.loading', 'busy');
  }

  try {
    const { recognize } = await loadInference();
    const readings = await recognize(input, {
      onProgress(fraction) {
        if (request !== state.requestSeq || !firstLoad || !state.loading) return;
        state.progress = Math.max(state.progress, fraction);
        showModelProgress(state.progress);
      },
    });
    if (request !== state.requestSeq) return;
    state.modelLoaded = true;
    state.loading = false;
    hideModelProgress();
    showReadings(readings);
  } catch (error) {
    if (request !== state.requestSeq) return;
    state.loading = false;
    hideModelProgress();
    const modelError = error?.name === 'ModelLoadError' || !state.modelLoaded;
    showError({
      titleKey: modelError ? 'error.model.title' : 'error.read.title',
      detailKey: modelError ? 'error.model.detail' : 'error.read.detail',
    });
  } finally {
    state.running = false;
    if (state.queued) {
      state.queued = false;
      readNow();
    }
  }
}

function makeModelInput() {
  const image = els.glyphImage;
  const naturalWidth = image.naturalWidth;
  const naturalHeight = image.naturalHeight;
  const { x, y, w, h } = state.crop;

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
  context.fillStyle = state.transparent && state.inkLight ? '#000' : '#fff';
  context.fillRect(0, 0, width, height);
  context.drawImage(image, sx, sy, sourceWidth, sourceHeight, 0, 0, width, height);
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

function showModelProgress(fraction) {
  els.modelLoad.hidden = false;
  const percent = Math.round(clamp(fraction, 0, 1) * 100);
  els.modelProgress.style.setProperty('--ui-progress', `${percent}%`);
  els.modelProgressText.textContent = `${percent}%`;
}

function hideModelProgress() {
  els.modelLoad.hidden = true;
}

function showReadings(readings) {
  state.loading = false;
  hideModelProgress();
  setBusy(false);
  if (!readings.length) {
    showError({ titleKey: 'error.noReading.title', detailKey: 'error.noReading.detail' });
    return;
  }

  state.readings = readings;
  state.error = null;
  state.copied = false;
  const best = readings[0];
  const score = Math.round(best.score * 1000) / 10;

  renderIds(els.idsText, best.ids);
  updateReadingMeta();
  els.openWorkshop.href = `https://ids.mkpo.li/?ids=${encodeURIComponent(best.ids)}`;

  const alternatives = readings.slice(1);
  els.candidateList.replaceChildren(...alternatives.map(candidateRow));
  els.candidates.hidden = alternatives.length === 0;

  els.resultEmpty.hidden = true;
  els.resultBody.hidden = false;
  els.resultError.hidden = true;
  setStatus('status.ready', 'idle');
  els.liveStatus.textContent = t('live.read', { ids: best.ids, score: score.toFixed(1) });
}

function updateReadingMeta() {
  if (!state.readings.length) return;
  const best = state.readings[0];
  const score = Math.round(best.score * 1000) / 10;
  els.scoreChip.textContent = t('reading.score', { value: score.toFixed(1) });
  els.scoreChip.title = t('reading.scoreHint');
  els.validityChip.textContent = best.valid ? t('reading.valid') : t('reading.invalid');
  els.validityChip.dataset.variant = best.valid ? 'accent' : 'danger';
  els.copyIds.textContent = state.copied ? t('reading.copied') : t('reading.copy');
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


/* ---------- Result state ---------- */

function resetResult() {
  state.readings = [];
  state.error = null;
  state.copied = false;
  state.loading = false;
  state.progress = 0;
  state.requestSeq += 1;
  hideModelProgress();
  els.resultBody.hidden = true;
  els.resultEmpty.hidden = false;
  els.resultError.hidden = true;
  els.candidates.hidden = true;
  els.idsText.replaceChildren();
  els.liveStatus.textContent = '';
  setBusy(false);
}

function setBusy(busy) {
  state.busy = busy;
  els.resultCard.setAttribute('aria-busy', String(busy));
  if (busy) {
    els.recognize.setAttribute('aria-busy', 'true');
    setStatus(state.loading ? 'status.loading' : 'status.reading', 'busy');
  } else {
    els.recognize.removeAttribute('aria-busy');
    if (!els.resultError.hidden) setStatus('status.error', 'error');
    else if (state.readings.length) setStatus('status.ready', 'idle');
    else els.readingStatus.hidden = true;
  }
}

function setStatus(key, kind) {
  els.readingStatus.hidden = false;
  els.readingStatus.dataset.state = kind;
  els.readingStatusText.textContent = t(key);
}

function refreshStatus() {
  if (els.readingStatus.hidden) return;
  const kind = els.readingStatus.dataset.state;
  const key = kind === 'busy'
    ? (state.loading ? 'status.loading' : 'status.reading')
    : kind === 'error' ? 'status.error' : 'status.ready';
  els.readingStatusText.textContent = t(key);
}

function clearError() {
  state.error = null;
  els.resultError.hidden = true;
}

function showError({ titleKey, detailKey }) {
  clearTimeout(state.readTimer);
  state.error = { titleKey, detailKey };
  state.loading = false;
  hideModelProgress();
  setBusy(false);
  els.resultError.hidden = false;
  els.errorTitle.textContent = t(titleKey);
  els.errorDetail.textContent = t(detailKey);
  if (!state.readings.length) {
    els.resultEmpty.hidden = true;
    els.resultBody.hidden = true;
  }
  setStatus('status.error', 'error');
  els.liveStatus.textContent = t(titleKey);
}

/* ---------- Copy ---------- */

els.copyIds.addEventListener('click', async () => {
  const reading = state.readings[0];
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
  updateReadingMeta();
  els.liveStatus.textContent = t('live.copied');
  setTimeout(() => {
    state.copied = false;
    updateReadingMeta();
  }, 1600);
});
