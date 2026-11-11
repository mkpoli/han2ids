export const MIN_CUT = 0.02;

export function uid() {
  return crypto.randomUUID ? crypto.randomUUID() : `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function padBox(box, margin, source) {
  if (!box) return { x: 0, y: 0, w: 1, h: 1 };
  const padding = (margin / 100) * Math.max(box.w * source.width, box.h * source.height);
  return clampCrop({
    x: box.x - padding / source.width,
    y: box.y - padding / source.height,
    w: box.w + (2 * padding) / source.width,
    h: box.h + (2 * padding) / source.height,
  });
}

export function clampCrop(crop) {
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

export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export function background(source) {
  return source.transparent && source.inkLight ? '#000' : '#fff';
}
