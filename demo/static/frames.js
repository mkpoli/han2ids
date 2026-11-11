import { frameScale, frameSize, greyLevels, inkAmountFor, inkMask, inkSide, removeSpecks } from './prepare.js';

/* A source's frame is the image enlarged and turned, with its grey levels measured. Black and
   white paints a second canvas over it. Item cuts are fractions of the frame, and the model reads
   the top canvas. */

export function createFrames(deps) {
  const frames = new Map();
  const FRAMES = 2;
  let clock = 0;

  const keyOf = source => `${source.prep.turn}|${source.prep.enlarge}`;

  async function frameFor(source) {
    let frame = frames.get(source.id);
    if (!frame || frame.key !== keyOf(source)) {
      const bitmap = await deps.bitmapFor(source);
      frame = frames.get(source.id);
      if (!frame || frame.key !== keyOf(source)) {
        frame = drawFrame(source, bitmap);
        keep(source.id, frame);
      }
    }
    frame.used = ++clock;
    applyTone(source, frame);
    return frame;
  }

  function keep(id, frame) {
    const old = frames.get(id);
    if (old) release(old);
    frames.set(id, frame);
    while (frames.size > FRAMES) {
      let oldest = null;
      for (const [key, entry] of frames) {
        if (key === id) continue;
        if (!oldest || entry.used < oldest[1].used) oldest = [key, entry];
      }
      if (!oldest) break;
      release(oldest[1]);
      frames.delete(oldest[0]);
    }
  }

  function release(frame) {
    for (const canvas of [frame.original, frame.prepared]) {
      if (canvas && !canvas.isConnected) canvas.width = 0;
    }
  }

  function drawFrame(source, bitmap) {
    const { turn, enlarge } = source.prep;
    const scale = frameScale(source.width, source.height, enlarge);
    const drawWidth = source.width * scale;
    const drawHeight = source.height * scale;
    const { width, height } = frameSize(source);

    const canvas = document.createElement('canvas');
    canvas.className = 'frame-original';
    canvas.width = width;
    canvas.height = height;
    canvas.setAttribute('role', 'img');
    canvas.dataset.i18nAria = 'image.alt';
    canvas.setAttribute('aria-label', deps.t('image.alt'));
    const context = canvas.getContext('2d', { willReadFrequently: true });
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = 'high';
    context.fillStyle = source.paper;
    context.fillRect(0, 0, width, height);
    context.save();
    context.translate(width / 2, height / 2);
    context.rotate((turn * Math.PI) / 180);
    context.drawImage(bitmap, -drawWidth / 2, -drawHeight / 2, drawWidth, drawHeight);
    context.restore();

    const grey = greyLevels(context.getImageData(0, 0, width, height).data);
    const side = inkSide(grey, width, height);
    return {
      key: keyOf(source),
      width,
      height,
      original: canvas,
      prepared: null,
      grey,
      side,
      autoInk: inkAmountFor(side.threshold, side.brightPaper),
      tone: '',
      mask: null,
      autoMask: null,
      paint: null,
      used: ++clock,
    };
  }

  /** Paints black and white over the frame, or takes it away. */
  function applyTone(source, frame) {
    const { bw, ink, specks } = source.prep;
    const tone = bw ? `${ink ?? 'auto'}|${specks}` : '';
    if (frame.tone === tone) return;
    frame.tone = tone;
    if (!bw) {
      frame.mask = null;
      if (frame.prepared) frame.prepared.hidden = true;
      return;
    }
    frame.mask = inkMask(frame.grey, ink ?? frame.autoInk, frame.side.brightPaper, frame.mask ?? undefined);
    if (specks) removeSpecks(frame.mask, frame.width, frame.height);

    if (!frame.prepared) {
      frame.prepared = document.createElement('canvas');
      frame.prepared.className = 'frame-prepared';
      frame.prepared.width = frame.width;
      frame.prepared.height = frame.height;
      frame.prepared.setAttribute('aria-hidden', 'true');
    }
    const context = frame.prepared.getContext('2d');
    frame.paint ??= context.createImageData(frame.width, frame.height);
    const pixels = new Uint32Array(frame.paint.data.buffer);
    const mask = frame.mask;
    for (let index = 0; index < mask.length; index += 1) pixels[index] = mask[index] ? 0xff000000 : 0xffffffff;
    context.putImageData(frame.paint, 0, 0);
    frame.prepared.hidden = false;
  }

  return { frameFor, peek: id => frames.get(id) ?? null };
}

/** The canvas the model reads: what the stage shows. */
export function preparedCanvas(frame) {
  return frame.mask ? frame.prepared : frame.original;
}

/** The ink Straighten measures: black and white when it is on, else the automatic split. */
export function frameInk(frame) {
  if (frame.mask) return frame.mask;
  frame.autoMask ??= inkMask(frame.grey, frame.autoInk, frame.side.brightPaper);
  return frame.autoMask;
}
