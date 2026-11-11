import { selectElements } from './elements.js';
import { frameInk } from './frames.js';
import { DEFAULT_PREP, carryPoint, estimateSkew, normaliseTurn, snapTurn, turnedSize } from './prepare.js';

const TURN_COMMIT_DELAY = 420;

/* The Prepare panel, the Cut/Turn switch and Original. Preparation belongs to a source and applies
   to every item cut from it. */
export function createPreparation(deps, els = selectElements(['imageWrap', 'frame', 'turnSurface', 'compare', 'prepReset', 'turnLeft', 'turnRight', 'straighten', 'prepBw', 'inkField', 'ink', 'inkAuto', 'specksRow', 'prepSpecks'])) {
  const enlargeRadios = [...document.querySelectorAll('input[name="enlarge"]')];
  const toolRadios = [...document.querySelectorAll('input[name="tool"]')];
  let shownId = null;
  let comparing = false;
  let turnDrag = null;
  let turnPending = 0;
  let turnTimer = 0;
  let inkFrame = 0;

  function selectedSource() {
    const item = deps.selectedItem();
    return item ? deps.getSource(item.sourceId) : null;
  }

  /**
   * Changes how a source is prepared. Its items read the new frame; a turn finds the glyphs again,
   * keeping the one under the selected cut.
   */
  function change(source, update) {
    const before = source.prep.turn;
    source.prep = { ...source.prep, ...update };
    const items = deps.itemsOf(source.id);
    if (source.prep.turn === before) {
      deps.restart(items);
      deps.renderStage();
      return;
    }
    const item = deps.selectedItem();
    const unit = turn => ({ ...turnedSize(source.width, source.height, turn), turn });
    const focus = item?.sourceId === source.id
      ? carryPoint({ x: item.crop.x + item.crop.w / 2, y: item.crop.y + item.crop.h / 2 }, unit(before), unit(source.prep.turn))
      : null;
    deps.restart(items, { read: false });
    deps.renderStage();
    deps.recut(source, { focus, afterTurn: true });
  }

  function render(source) {
    if (source?.id !== shownId) {
      shownId = source?.id ?? null;
      cancelTurn();
    }
    const prep = source?.prep ?? DEFAULT_PREP;
    els.prepBw.checked = prep.bw;
    els.prepSpecks.checked = prep.specks;
    els.inkField.hidden = !prep.bw;
    els.specksRow.hidden = !prep.bw;
    els.compare.hidden = !prep.bw;
    if (!prep.bw && comparing) setCompare(false);
    els.ink.value = String(prep.ink ?? (source && deps.peekFrame(source.id)?.autoInk) ?? 128);
    els.inkAuto.setAttribute('aria-pressed', String(prep.ink === null));
    els.prepReset.hidden = Object.keys(DEFAULT_PREP).every(key => prep[key] === DEFAULT_PREP[key]);
    for (const radio of enlargeRadios) radio.checked = Number(radio.value) === prep.enlarge;
    els.turnSurface.setAttribute('aria-valuenow', String(Math.round(prep.turn)));
  }

  for (const radio of enlargeRadios) {
    radio.addEventListener('change', () => {
      const source = selectedSource();
      if (radio.checked && source) change(source, { enlarge: Number(radio.value) });
    });
  }

  els.prepBw.addEventListener('change', () => {
    const source = selectedSource();
    if (source) change(source, { bw: els.prepBw.checked });
  });

  els.prepSpecks.addEventListener('change', () => {
    const source = selectedSource();
    if (source) change(source, { specks: els.prepSpecks.checked });
  });

  els.ink.addEventListener('input', () => {
    const source = selectedSource();
    if (!source) return;
    const ink = Number(els.ink.value);
    els.inkAuto.setAttribute('aria-pressed', 'false');
    deps.restart(deps.itemsOf(source.id), { read: false });
    cancelAnimationFrame(inkFrame);
    inkFrame = requestAnimationFrame(() => change(source, { ink }));
  });

  els.inkAuto.addEventListener('click', () => {
    const source = selectedSource();
    if (source && source.prep.ink !== null) change(source, { ink: null });
  });

  els.prepReset.addEventListener('click', () => {
    const source = selectedSource();
    if (!source) return;
    cancelTurn();
    change(source, DEFAULT_PREP);
  });

  /* Original: hold the button, by pointer or by Space or Enter, to see the frame without the
     black and white layer. */

  function setCompare(on) {
    comparing = on;
    els.compare.setAttribute('aria-pressed', String(on));
    els.frame.classList.toggle('is-comparing', on);
  }

  els.compare.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    els.compare.setPointerCapture?.(event.pointerId);
    setCompare(true);
    event.preventDefault();
  });
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
    els.compare.addEventListener(type, () => setCompare(false));
  }
  els.compare.addEventListener('keydown', event => {
    if (event.key !== ' ' && event.key !== 'Enter') return;
    event.preventDefault();
    if (!event.repeat) setCompare(true);
  });
  els.compare.addEventListener('keyup', event => {
    if (event.key === ' ' || event.key === 'Enter') setCompare(false);
  });
  els.compare.addEventListener('blur', () => setCompare(false));
  els.compare.addEventListener('contextmenu', event => event.preventDefault());

  /* ---------- Turning ---------- */

  function setTool(tool) {
    const next = tool === 'turn' ? 'turn' : 'cut';
    els.imageWrap.dataset.tool = next;
    els.turnSurface.hidden = next !== 'turn';
    for (const radio of toolRadios) radio.checked = radio.value === next;
    if (next === 'cut') commitTurn();
  }

  for (const radio of toolRadios) {
    radio.addEventListener('change', () => {
      if (radio.checked) setTool(radio.value);
    });
  }

  /** Shows a turn that is still being made, without redrawing the frame. */
  function showTurn(delta) {
    const source = selectedSource();
    if (!source) return;
    const target = snapTurn(source.prep.turn + delta);
    const shown = normaliseTurn(target - source.prep.turn);
    els.frame.style.setProperty('--live-turn', `${shown}deg`);
    els.imageWrap.classList.toggle('is-turning', shown !== 0);
    els.turnSurface.setAttribute('aria-valuenow', String(Math.round(target)));
  }

  function turnBy(delta) {
    cancelTurn();
    const source = selectedSource();
    if (!source) return;
    const next = snapTurn(source.prep.turn + delta);
    if (next !== source.prep.turn) change(source, { turn: next });
  }

  function commitTurn() {
    clearTimeout(turnTimer);
    const delta = turnPending;
    turnPending = 0;
    if (delta) turnBy(delta);
    else cancelTurn();
  }

  function cancelTurn() {
    clearTimeout(turnTimer);
    turnPending = 0;
    els.frame.style.setProperty('--live-turn', '0deg');
    els.imageWrap.classList.remove('is-turning');
  }

  function pointerAngle(event, drag) {
    return Math.atan2(event.clientY - drag.centreY, event.clientX - drag.centreX);
  }

  els.turnSurface.addEventListener('pointerdown', event => {
    if (event.button !== 0 || !selectedSource() || turnDrag) return;
    commitTurn();
    const rect = els.imageWrap.getBoundingClientRect();
    const drag = {
      pointerId: event.pointerId,
      centreX: rect.left + rect.width / 2,
      centreY: rect.top + rect.height / 2,
      reach: Math.min(rect.width, rect.height) * 0.08,
      delta: 0,
    };
    drag.last = pointerAngle(event, drag);
    turnDrag = drag;
    els.turnSurface.setPointerCapture?.(event.pointerId);
    els.turnSurface.focus({ preventScroll: true });
    els.imageWrap.classList.add('is-dragging');
    event.preventDefault();
  });

  els.turnSurface.addEventListener('pointermove', event => {
    const drag = turnDrag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    // Near the centre the angle swings wildly, so the pointer has to be a little way out.
    if (Math.hypot(event.clientX - drag.centreX, event.clientY - drag.centreY) < drag.reach) return;
    const angle = pointerAngle(event, drag);
    let step = angle - drag.last;
    if (step > Math.PI) step -= 2 * Math.PI;
    if (step < -Math.PI) step += 2 * Math.PI;
    drag.last = angle;
    drag.delta += (step * 180) / Math.PI;
    showTurn(drag.delta);
    event.preventDefault();
  });

  function endTurnDrag(event) {
    const drag = turnDrag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    turnDrag = null;
    els.imageWrap.classList.remove('is-dragging');
    if (els.turnSurface.hasPointerCapture?.(drag.pointerId)) els.turnSurface.releasePointerCapture(drag.pointerId);
    turnBy(drag.delta);
  }

  els.turnSurface.addEventListener('pointerup', endTurnDrag);
  els.turnSurface.addEventListener('pointercancel', endTurnDrag);
  els.turnSurface.addEventListener('lostpointercapture', endTurnDrag);

  els.turnSurface.addEventListener('keydown', event => {
    const source = selectedSource();
    if (!source) return;
    const fine = event.shiftKey ? 5 : 0.5;
    const steps = { ArrowRight: fine, ArrowUp: fine, ArrowLeft: -fine, ArrowDown: -fine };
    if (event.key in steps) {
      event.preventDefault();
      turnPending += steps[event.key];
      showTurn(turnPending);
      clearTimeout(turnTimer);
      turnTimer = setTimeout(commitTurn, TURN_COMMIT_DELAY);
    } else if (event.key === 'PageUp' || event.key === 'PageDown') {
      event.preventDefault();
      turnBy(turnPending + (event.key === 'PageUp' ? 90 : -90));
    } else if (event.key === 'Home') {
      event.preventDefault();
      turnBy(-source.prep.turn);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      commitTurn();
    }
  });

  els.turnSurface.addEventListener('blur', commitTurn);

  els.turnLeft.addEventListener('click', () => turnBy(-90));
  els.turnRight.addEventListener('click', () => turnBy(90));

  els.straighten.addEventListener('click', async () => {
    const source = selectedSource();
    if (!source) return;
    commitTurn();
    let frame;
    try {
      frame = await deps.frameFor(source);
    } catch {
      return;
    }
    if (selectedSource() !== source) return;
    const fix = estimateSkew(frameInk(frame), frame.width, frame.height);
    if (Math.abs(fix) < 0.2) {
      deps.announce(deps.t('live.straight'));
      return;
    }
    turnBy(fix);
  });

  return { render, currentPrep: () => selectedSource()?.prep ?? DEFAULT_PREP };
}
