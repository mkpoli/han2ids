export const MIN_CUT = 0.02;

export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
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

/** A box grown by `margin` percent of its longer side, in a frame of the given size. */
export function padBox(box, margin, { width, height }) {
  if (!box) return { x: 0, y: 0, w: 1, h: 1 };
  const padding = (margin / 100) * Math.max(box.w * width, box.h * height);
  return clampCrop({
    x: box.x - padding / width,
    y: box.y - padding / height,
    w: box.w + (2 * padding) / width,
    h: box.h + (2 * padding) / height,
  });
}

/** The item whose box holds the point, else the one whose box centre is nearest. */
export function nearestItem(items, point) {
  if (!point) return null;
  let best = null;
  let distance = Infinity;
  for (const item of items) {
    const { x, y, w, h } = item.box;
    const inside = point.x >= x && point.x <= x + w && point.y >= y && point.y <= y + h;
    const away = inside ? -1 : Math.hypot(point.x - (x + w / 2), point.y - (y + h / 2));
    if (away < distance) {
      distance = away;
      best = item;
    }
  }
  return best;
}
