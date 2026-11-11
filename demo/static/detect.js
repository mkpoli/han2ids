/* Where the glyphs are in an image.

   One pass of Otsu binarisation gives an ink mask; connected components drop specks; the widest
   run of ink along each axis estimates the em box. A sheet is then cut at its widest gaps, first
   into rows and then into glyphs, never past a piece that already fits one em box, so the halves
   of ⿰ and the tiers of ⿱ stay with their glyph. Two glyphs must leave one blank pixel row or
   column between them in at least one direction. */

const MAX_SIDE = 1200;
const SPECK_PIXELS = 3;
const DUST_EM = 0.06;
const MIN_BOX_EM = 0.22;
const SPAN_EM = 1.15;
const MAX_BOXES = 400;

/** Ink geometry of a raster: the whole ink box, one box per glyph, and the background it found. */
export function analysePixels({ data, width, height }) {
  if (!width || !height) return { inkBox: null, boxes: [], cell: 0, transparent: false, inkLight: false };

  const { mask, transparent, inkLight } = binarise(data, width, height);
  const labels = new Int32Array(width * height);
  const parts = label(mask, labels, width, height);
  const ground = { transparent, inkLight };

  let kept = parts.filter(part => part.pixels > SPECK_PIXELS);
  if (!kept.length) return { inkBox: null, boxes: [], cell: 0, ...ground };
  prune(mask, labels, parts, kept);

  let content = cover(kept);
  let cell = emBox(mask, width, content);

  const solid = kept.filter(part => Math.max(part.right - part.left + 1, part.bottom - part.top + 1) >= DUST_EM * cell);
  if (solid.length && solid.length !== kept.length) {
    prune(mask, labels, parts, solid);
    kept = solid;
    content = cover(kept);
    cell = emBox(mask, width, content);
  }

  const span = Math.max(1, SPAN_EM * cell);
  const boxes = [];
  const rows = cut(runs(profile(mask, width, content, 'row'), content.top, content.bottom + 1), span);
  for (const band of rows) {
    const strip = { ...content, top: band.start, bottom: band.end - 1 };
    const columns = cut(runs(profile(mask, width, strip, 'column'), content.left, content.right + 1), span);
    for (const column of columns) {
      const box = tighten(mask, width, { ...strip, left: column.start, right: column.end - 1 });
      if (!box) continue;
      if (Math.max(box.right - box.left + 1, box.bottom - box.top + 1) < MIN_BOX_EM * cell) continue;
      boxes.push(box);
    }
  }

  return {
    inkBox: normalise(content, width, height),
    boxes: boxes.slice(0, MAX_BOXES).map(box => normalise(box, width, height)),
    cell,
    ...ground,
  };
}

/** The same geometry for an image element, measured on a downscale of it. */
export function analyseImage(image, { maxSide = MAX_SIDE } = {}) {
  const width = image.naturalWidth || image.width;
  const height = image.naturalHeight || image.height;
  if (!width || !height) return { inkBox: null, boxes: [], cell: 0, transparent: false, inkLight: false };

  const scale = Math.min(1, maxSide / Math.max(width, height));
  const w = Math.max(1, Math.round(width * scale));
  const h = Math.max(1, Math.round(height * scale));
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.drawImage(image, 0, 0, w, h);
  return analysePixels({ data: context.getImageData(0, 0, w, h).data, width: w, height: h });
}

/* ---------- Binarisation ---------- */

function binarise(data, width, height) {
  const edge = Math.max(1, Math.round(Math.min(width, height) * 0.02));
  const histogram = new Uint32Array(256);
  let borderCount = 0;
  let borderOpaque = 0;
  let borderLuma = 0;
  let histogramCount = 0;

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const offset = (y * width + x) * 4;
      const alpha = data[offset + 3];
      const luma = Math.round(0.2126 * data[offset] + 0.7152 * data[offset + 1] + 0.0722 * data[offset + 2]);
      if (x < edge || y < edge || x >= width - edge || y >= height - edge) {
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

  const transparent = borderCount > 0 && borderOpaque / borderCount < 0.6;
  const threshold = otsu(histogram, histogramCount);
  const bright = (borderOpaque ? borderLuma / borderOpaque : 255) >= threshold;

  const mask = new Uint8Array(width * height);
  let inkLuma = 0;
  let inkCount = 0;
  for (let index = 0; index < mask.length; index += 1) {
    const offset = index * 4;
    if (data[offset + 3] <= 32) continue;
    const luma = 0.2126 * data[offset] + 0.7152 * data[offset + 1] + 0.0722 * data[offset + 2];
    if (!transparent && !(bright ? luma <= threshold : luma >= threshold)) continue;
    mask[index] = 1;
    inkLuma += luma;
    inkCount += 1;
  }

  return { mask, transparent, inkLight: inkCount > 0 && inkLuma / inkCount > 127 };
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

/* ---------- Components ---------- */

function label(mask, labels, width, height) {
  const parts = [];
  const stack = new Int32Array(mask.length);
  for (let seed = 0; seed < mask.length; seed += 1) {
    if (!mask[seed] || labels[seed]) continue;
    const id = parts.length + 1;
    labels[seed] = id;
    stack[0] = seed;
    let depth = 1;
    let left = width;
    let right = -1;
    let top = height;
    let bottom = -1;
    let pixels = 0;

    while (depth) {
      const index = stack[--depth];
      const x = index % width;
      const y = (index - x) / width;
      pixels += 1;
      if (x < left) left = x;
      if (x > right) right = x;
      if (y < top) top = y;
      if (y > bottom) bottom = y;
      for (let ny = Math.max(0, y - 1); ny <= Math.min(height - 1, y + 1); ny += 1) {
        for (let nx = Math.max(0, x - 1); nx <= Math.min(width - 1, x + 1); nx += 1) {
          const next = ny * width + nx;
          if (!mask[next] || labels[next]) continue;
          labels[next] = id;
          stack[depth++] = next;
        }
      }
    }
    parts.push({ id, left, top, right, bottom, pixels });
  }
  return parts;
}

function prune(mask, labels, parts, kept) {
  const keep = new Uint8Array(parts.length + 1);
  for (const part of kept) keep[part.id] = 1;
  for (let index = 0; index < mask.length; index += 1) {
    if (mask[index] && !keep[labels[index]]) mask[index] = 0;
  }
}

function cover(parts) {
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const part of parts) {
    if (part.left < left) left = part.left;
    if (part.top < top) top = part.top;
    if (part.right > right) right = part.right;
    if (part.bottom > bottom) bottom = part.bottom;
  }
  return { left, top, right, bottom };
}

/* ---------- Projections and cuts ---------- */

function profile(mask, width, box, axis) {
  const counts = axis === 'row' ? new Uint32Array(box.bottom + 1) : new Uint32Array(box.right + 1);
  for (let y = box.top; y <= box.bottom; y += 1) {
    const row = y * width;
    for (let x = box.left; x <= box.right; x += 1) {
      if (mask[row + x]) counts[axis === 'row' ? y : x] += 1;
    }
  }
  return counts;
}

function runs(counts, from, to) {
  const out = [];
  let start = -1;
  for (let at = from; at < to; at += 1) {
    if (counts[at]) {
      if (start < 0) start = at;
    } else if (start >= 0) {
      out.push({ start, end: at });
      start = -1;
    }
  }
  if (start >= 0) out.push({ start, end: to });
  return out;
}

/** Group runs into pieces no wider than one em box, cutting at the widest gap first. */
function cut(list, span) {
  if (!list.length) return [];
  const out = [];
  const pending = [[0, list.length]];

  while (pending.length) {
    const [from, to] = pending.pop();
    const start = list[from].start;
    const end = list[to - 1].end;
    if (to - from === 1 || end - start <= span) {
      out.push({ start, end });
      continue;
    }

    const middle = (start + end) / 2;
    let widest = -1;
    let offset = Infinity;
    let at = from;
    for (let index = from; index < to - 1; index += 1) {
      const gap = list[index + 1].start - list[index].end;
      const distance = Math.abs((list[index].end + list[index + 1].start) / 2 - middle);
      if (gap > widest || (gap === widest && distance < offset)) {
        widest = gap;
        offset = distance;
        at = index;
      }
    }
    pending.push([from, at + 1], [at + 1, to]);
  }

  return out.sort((first, second) => first.start - second.start);
}

function emBox(mask, width, content) {
  let cell = 0;
  for (const run of runs(profile(mask, width, content, 'row'), content.top, content.bottom + 1)) {
    cell = Math.max(cell, run.end - run.start);
  }
  for (const run of runs(profile(mask, width, content, 'column'), content.left, content.right + 1)) {
    cell = Math.max(cell, run.end - run.start);
  }
  return cell;
}

function tighten(mask, width, box) {
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (let y = box.top; y <= box.bottom; y += 1) {
    const row = y * width;
    for (let x = box.left; x <= box.right; x += 1) {
      if (!mask[row + x]) continue;
      if (x < left) left = x;
      if (x > right) right = x;
      if (y < top) top = y;
      if (y > bottom) bottom = y;
    }
  }
  return right < left ? null : { left, top, right, bottom };
}

function normalise(box, width, height) {
  return {
    x: box.left / width,
    y: box.top / height,
    w: (box.right - box.left + 1) / width,
    h: (box.bottom - box.top + 1) / height,
  };
}

/** Canvas colour behind the glyph: light ink on transparency needs a dark ground. */
export function background(source) {
  return source.transparent && source.inkLight ? '#000' : '#fff';
}
