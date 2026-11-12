import { selectElements } from './elements.js';
import { analyseImage } from './detect.js';
import { MIN_CUT, clamp, clampCrop, padBox } from './geometry.js';

const CROP_ANNOUNCE_DELAY = 250;

export function createStage(deps, els = selectElements(['cleanUp', 'imageEditor', 'dropEmpty', 'cutControls', 'imageSize', 'boxCount', 'boxLayer', 'glyphImage', 'imageWrap', 'cropBox', 'cropState', 'cropLive', 'quickCut', 'autoCut', 'fullImage'])) {
  let drag = null;
  let cropAnnounceTimer = 0;

  function renderStage() {
    const item = deps.selectedItem();
    resetCropAnnouncement();
    if (!item) {
      els.imageEditor.hidden = true;
      els.dropEmpty.hidden = false;
      els.cutControls.hidden = true;
      els.imageSize.hidden = true;
      els.boxCount.hidden = true;
      els.boxLayer.replaceChildren();
      els.cropState.textContent = '';
      return;
    }

    const source = deps.getSource(item.sourceId);
    if (els.glyphImage.dataset.source !== source.id) {
      els.glyphImage.src = deps.sourceUrl(source);
      els.glyphImage.dataset.source = source.id;
    }
    els.imageEditor.hidden = false;
    els.dropEmpty.hidden = true;
    els.cutControls.hidden = false;
    els.imageSize.hidden = false;
    els.imageSize.textContent = `${source.width} × ${source.height}`;
    const count = deps.itemsOf(source.id).length;
    els.boxCount.hidden = count < 2;
    els.boxCount.textContent = deps.t('quick.boxes', { count });
    els.imageWrap.toggleAttribute('data-many', count > 1);
    els.imageWrap.style.setProperty('--image-bg', source.transparent && source.inkLight ? '#000' : '#fff');
    renderBoxes();
    renderCrop();
  }

  function renderBoxes() {
    const item = deps.selectedItem();
    const list = item ? deps.itemsOf(item.sourceId) : [];
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
    if (box) deps.selectItem(box.dataset.id);
  });

  function renderCrop() {
    const item = deps.selectedItem();
    if (!item) return;
    const { x, y, w, h } = item.crop;
    els.imageWrap.style.setProperty('--cut-x', `${x * 100}%`);
    els.imageWrap.style.setProperty('--cut-y', `${y * 100}%`);
    els.imageWrap.style.setProperty('--cut-w', `${w * 100}%`);
    els.imageWrap.style.setProperty('--cut-h', `${h * 100}%`);
    updateCropDescription();
  }

  function updateCropDescription() {
    const item = deps.selectedItem();
    if (!item) {
      els.cropState.textContent = '';
      return;
    }
    const format = new Intl.NumberFormat(document.documentElement.lang || 'en', { maximumFractionDigits: 1 });
    const { x, y, w, h } = item.crop;
    els.cropState.textContent = deps.t('crop.state', {
      x: format.format(x * 100), y: format.format(y * 100),
      w: format.format(w * 100), h: format.format(h * 100),
    });
  }

  function resetCropAnnouncement() {
    clearTimeout(cropAnnounceTimer);
    els.cropLive.textContent = '';
  }

  function announceCrop() {
    if (drag) return;
    clearTimeout(cropAnnounceTimer);
    els.cropLive.textContent = '';
    cropAnnounceTimer = setTimeout(() => {
      els.cropLive.textContent = els.cropState.textContent;
    }, CROP_ANNOUNCE_DELAY);
  }

  function setCrop(crop, delay) {
    const item = deps.selectedItem();
    if (!item) return;
    const next = clampCrop(crop);
    const changed = ['x', 'y', 'w', 'h'].some(key => next[key] !== item.crop[key]);
    item.crop = next;
    if (changed) {
      deps.onCropChanged(item);
      announceCrop();
    }
    renderCrop();
    deps.scheduleRead(delay);
  }

  /* ---------- Pointer and keyboard crop controls ---------- */

  els.cropBox.addEventListener('pointerdown', event => {
    if (event.button !== 0 || !deps.selectedItem() || drag) return;
    const handle = event.target.closest('[data-handle]');
    const rect = els.imageWrap.getBoundingClientRect();
    if (!rect.width || !rect.height) return;

    drag = {
      mode: handle ? handle.dataset.handle : 'move',
      startX: (event.clientX - rect.left) / rect.width,
      startY: (event.clientY - rect.top) / rect.height,
      crop: { ...deps.selectedItem().crop },
      moved: false,
      target: handle ?? els.cropBox,
      pointerId: event.pointerId,
    };
    drag.target.setPointerCapture?.(event.pointerId);
    els.imageWrap.classList.add('is-cropping');
    resetCropAnnouncement();
    els.cropBox.focus({ preventScroll: true });
    deps.cancelScheduled();
    event.preventDefault();
  });

  window.addEventListener('pointermove', event => {
    const item = deps.selectedItem();
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
    drag.moved = true;
    renderCrop();
    event.preventDefault();
  });

  function endDrag(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const { target, pointerId, moved } = drag;
    drag = null;
    if (target.hasPointerCapture?.(pointerId)) target.releasePointerCapture(pointerId);
    els.imageWrap.classList.remove('is-cropping');
    if (moved) {
      deps.scheduleRead();
      announceCrop();
    }
  }

  window.addEventListener('pointerup', endDrag);
  window.addEventListener('pointercancel', endDrag);
  els.cropBox.addEventListener('lostpointercapture', endDrag);

  els.cropBox.addEventListener('focus', () => announceCrop());

  els.cropBox.addEventListener('keydown', event => {
    const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'];
    const item = deps.selectedItem();
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

  els.cleanUp.addEventListener('change', () => deps.onCleanChanged(els.cleanUp.checked));

  els.quickCut.addEventListener('click', () => quickCut());

  els.autoCut.addEventListener('click', () => {
    const item = deps.selectedItem();
    if (!item) return;
    const source = deps.getSource(item.sourceId);
    setCrop(padBox(item.box, source), 0);
  });

  els.fullImage.addEventListener('click', () => {
    if (!deps.selectedItem()) return;
    setCrop({ x: 0, y: 0, w: 1, h: 1 }, 0);
  });

  async function quickCut() {
    const current = deps.selectedItem();
    if (!current) return;
    const source = deps.getSource(current.sourceId);
    let found;
    try {
      found = analyseImage(await deps.bitmapFor(source));
    } catch {
      deps.showError({ titleKey: 'error.cut.title', detailKey: 'error.cut.detail' });
      return;
    }
    if (!found.boxes.length) {
      deps.showError({ titleKey: 'error.detect.title', detailKey: 'error.detect.detail' });
      return;
    }

    deps.clearError();
    deps.onQuickCut(source, found);
  }

  return { renderStage, renderBoxes, setCrop, isClean: () => els.cleanUp.checked, isDragging: () => Boolean(drag) };
}
