import { selectElements } from './elements.js';
import { clamp } from './geometry.js';
import { renderIds } from './render-ids.js';

export function createDisplay(deps, els = selectElements(['modelLoad', 'modelProgress', 'modelProgressText', 'resultEmpty', 'resultBody', 'resultError', 'readingStatus', 'candidates', 'idsText', 'resultCard', 'errorTitle', 'errorDetail', 'openWorkshop', 'scoreChip', 'validityChip', 'copyIds', 'sourceChip', 'candidateList', 'readingStatusText', 'liveStatus'])) {
  let copied = false;

  function showModelProgress(fraction) {
    els.modelLoad.hidden = false;
    els.modelProgress.hidden = fraction === null;
    if (fraction === null) {
      els.modelProgressText.textContent = '—';
      return;
    }
    const percent = Math.floor(clamp(fraction, 0, 1) * 100);
    els.modelProgress.style.setProperty('--ui-progress', `${percent}%`);
    els.modelProgressText.textContent = `${percent}%`;
  }

  function hideModelProgress() {
    els.modelLoad.hidden = true;
  }
  function renderResult() {
    const item = deps.selectedItem();
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
      els.errorTitle.textContent = deps.t(`${item.errorKey}.title`);
      els.errorDetail.textContent = deps.t(`${item.errorKey}.detail`);
    }

    if (reading) {
      renderIds(els.idsText, reading.ids);
      els.openWorkshop.href = `https://ids.mkpo.li/?ids=${encodeURIComponent(reading.ids)}`;
      const score = Math.round(reading.score * 1000) / 10;
      els.scoreChip.textContent = deps.t('reading.score', { value: score.toFixed(1) });
      els.scoreChip.title = deps.t('reading.scoreHint');
      els.validityChip.textContent = reading.valid ? deps.t('reading.valid') : deps.t('reading.invalid');
      els.validityChip.dataset.variant = reading.valid ? 'accent' : 'danger';
      els.copyIds.textContent = copied ? deps.t('reading.copied') : deps.t('reading.copy');

      const source = deps.getSource(item.sourceId);
      els.sourceChip.hidden = false;
      els.sourceChip.textContent = deps.itemsOf(item.sourceId).length > 1
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

    if (item.phase === 'reading') setStatus(deps.isLoading() ? 'status.loading' : 'status.reading', 'busy');
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
  function setStatus(key, kind) {
    els.readingStatus.hidden = false;
    els.readingStatus.dataset.state = kind;
    els.readingStatusText.textContent = deps.t(key);
  }

  function clearError() {
    els.resultError.hidden = true;
  }

  function showError({ titleKey, detailKey }) {
    els.resultError.hidden = false;
    els.errorTitle.textContent = deps.t(titleKey);
    els.errorDetail.textContent = deps.t(detailKey);
    setStatus('status.error', 'error');
    els.liveStatus.textContent = deps.t(titleKey);
  }

  /* ---------- Copy ---------- */

  els.copyIds.addEventListener('click', async () => {
    const reading = deps.selectedItem()?.readings[0];
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
    copied = true;
    renderResult();
    els.liveStatus.textContent = deps.t('live.copied');
    setTimeout(() => {
      copied = false;
      renderResult();
    }, 1600);
  });

  return { renderResult, showModelProgress, hideModelProgress, setStatus, clearError, showError, clearCopied: () => { copied = false; }, clearLive: () => { els.liveStatus.textContent = ''; }, announceReading: reading => { els.liveStatus.textContent = deps.t('live.read', { ids: reading.ids, score: (Math.round(reading.score * 1000) / 10).toFixed(1) }); } };
}
