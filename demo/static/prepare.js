/* What the model reads: a 224 px frame with black ink on white, upright and centred.

   Scans and photos arrive grey, shaded, speckled, tilted or light-on-dark. Each step below undoes
   one of those, on plain pixel arrays so the same code runs in the page and under Node. */

export const SIZE = 224;
const WORK = 640;
export const DEFAULTS = { flatten: true, levels: true, despeckle: true, deskew: true, margin: 12, contrast: 0.25 };
/** Polarity and framing only, for an image the clean-up misreads. */
export const RAW = { flatten: false, levels: false, despeckle: false, deskew: false };

/** RGBA pixels in, the model tensor and its greyscale view out. */
export function prepare({ data, width, height }, options = {}) {
  const o = { ...DEFAULTS, ...options };
  let image = luminance(data, width, height);
  if (borderMedian(image) < 0.5) image = map(image, value => 1 - value);
  if (o.flatten) image = flatten(image);
  const split = otsu(image);
  if (o.levels) image = levels(image, split, o.contrast);
  const cut = o.levels ? 0.5 : split.threshold;
  if (o.despeckle) despeckle(image, cut);
  let angle = 0;
  if (o.deskew) {
    angle = skew(image, cut);
    if (Math.abs(angle) >= 0.75) image = rotate(image, -angle);
    else angle = 0;
  }
  const view = frame(image, inkBox(image, cut), o.margin);
  const input = new Float32Array(3 * SIZE * SIZE);
  for (let index = 0; index < SIZE * SIZE; index += 1) {
    const value = (view[index] - 0.5) / 0.5;
    input[index] = value;
    input[SIZE * SIZE + index] = value;
    input[2 * SIZE * SIZE + index] = value;
  }
  return { input, view, angle };
}

function map(image, fn) {
  const pixels = new Float32Array(image.pixels.length);
  for (let index = 0; index < pixels.length; index += 1) pixels[index] = fn(image.pixels[index]);
  return { ...image, pixels };
}

/** Luminance in 0..1 at working size; transparent pixels take the ground that contrasts with the ink. */
function luminance(data, width, height) {
  const step = Math.max(1, Math.ceil(Math.max(width, height) / WORK));
  const w = Math.max(1, Math.floor(width / step));
  const h = Math.max(1, Math.floor(height / step));
  let sum = 0;
  let weight = 0;
  for (let offset = 0; offset < data.length; offset += 4) {
    const alpha = data[offset + 3];
    sum += alpha * (0.299 * data[offset] + 0.587 * data[offset + 1] + 0.114 * data[offset + 2]);
    weight += alpha;
  }
  const ground = weight && sum / weight < 127 ? 255 : 0;
  const pixels = new Float32Array(w * h);
  const area = step * step * 255;
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      let total = 0;
      for (let dy = 0; dy < step; dy += 1) {
        for (let dx = 0; dx < step; dx += 1) {
          const offset = ((y * step + dy) * width + x * step + dx) * 4;
          const alpha = data[offset + 3] / 255;
          const value = 0.299 * data[offset] + 0.587 * data[offset + 1] + 0.114 * data[offset + 2];
          total += alpha * value + (1 - alpha) * ground;
        }
      }
      pixels[y * w + x] = total / area;
    }
  }
  return { pixels, w, h };
}

function borderMedian({ pixels, w, h }) {
  const values = [];
  for (let x = 0; x < w; x += 1) values.push(pixels[x], pixels[(h - 1) * w + x]);
  for (let y = 0; y < h; y += 1) values.push(pixels[y * w], pixels[y * w + w - 1]);
  values.sort((a, b) => a - b);
  return values[values.length >> 1];
}

/** Divide by the paper level, estimated per cell and interpolated, so shade and grey paper go white. */
function flatten({ pixels, w, h }) {
  const cells = 12;
  const cw = w / cells;
  const ch = h / cells;
  const level = new Float32Array(cells * cells);
  for (let cy = 0; cy < cells; cy += 1) {
    for (let cx = 0; cx < cells; cx += 1) {
      const values = [];
      for (let y = Math.floor(cy * ch); y < Math.floor((cy + 1) * ch); y += 1) {
        for (let x = Math.floor(cx * cw); x < Math.floor((cx + 1) * cw); x += 1) values.push(pixels[y * w + x]);
      }
      values.sort((a, b) => a - b);
      level[cy * cells + cx] = values.length ? values[Math.floor(values.length * 0.85)] : 1;
    }
  }
  // A cell buried in ink has no paper; borrow the brightest neighbour.
  const paper = new Float32Array(cells * cells);
  for (let cy = 0; cy < cells; cy += 1) {
    for (let cx = 0; cx < cells; cx += 1) {
      let own = level[cy * cells + cx];
      let best = own;
      for (let dy = -1; dy <= 1; dy += 1) {
        for (let dx = -1; dx <= 1; dx += 1) {
          const ny = cy + dy;
          const nx = cx + dx;
          if (ny >= 0 && ny < cells && nx >= 0 && nx < cells) best = Math.max(best, level[ny * cells + nx]);
        }
      }
      paper[cy * cells + cx] = own < 0.7 * best ? best : own;
    }
  }
  const out = new Float32Array(pixels.length);
  for (let y = 0; y < h; y += 1) {
    const fy = Math.min(cells - 1, Math.max(0, (y + 0.5) / ch - 0.5));
    const y0 = Math.floor(fy);
    const y1 = Math.min(cells - 1, y0 + 1);
    for (let x = 0; x < w; x += 1) {
      const fx = Math.min(cells - 1, Math.max(0, (x + 0.5) / cw - 0.5));
      const x0 = Math.floor(fx);
      const x1 = Math.min(cells - 1, x0 + 1);
      const top = paper[y0 * cells + x0] * (x1 - fx || 1 - (fx - x0)) + paper[y0 * cells + x1] * (fx - x0);
      const bottom = paper[y1 * cells + x0] * (x1 - fx || 1 - (fx - x0)) + paper[y1 * cells + x1] * (fx - x0);
      const ground = top * (1 - (fy - y0)) + bottom * (fy - y0);
      out[y * w + x] = Math.min(1, pixels[y * w + x] / Math.max(ground, 0.05));
    }
  }
  return { pixels: out, w, h };
}

/** Otsu's threshold with the mean ink and paper levels on either side of it. */
function otsu({ pixels }) {
  const bins = new Float64Array(256);
  for (const value of pixels) bins[Math.min(255, Math.max(0, Math.round(value * 255)))] += 1;
  let total = 0;
  for (let index = 0; index < 256; index += 1) total += index * bins[index];
  let below = 0;
  let count = 0;
  let best = -1;
  let threshold = 127;
  for (let index = 0; index < 256; index += 1) {
    count += bins[index];
    below += index * bins[index];
    const rest = pixels.length - count;
    if (!count || !rest) continue;
    const gap = below / count - (total - below) / rest;
    const between = count * rest * gap * gap;
    if (between > best) {
      best = between;
      threshold = index;
    }
  }
  let ink = 0;
  let inkCount = 0;
  let paper = 0;
  let paperCount = 0;
  for (let index = 0; index < 256; index += 1) {
    if (index <= threshold) {
      ink += index * bins[index];
      inkCount += bins[index];
    } else {
      paper += index * bins[index];
      paperCount += bins[index];
    }
  }
  return {
    threshold: (threshold + 0.5) / 255,
    ink: inkCount ? ink / inkCount / 255 : 0,
    paper: paperCount ? paper / paperCount / 255 : 1,
  };
}

/** Stretch so ink is black and paper white, clipping the noise at both ends. */
function levels(image, { ink, paper }, contrast) {
  const range = Math.max(0.02, paper - ink);
  const low = ink + contrast * range;
  const high = paper - contrast * range;
  return map(image, value => Math.min(1, Math.max(0, (value - low) / (high - low))));
}

/** Erase ink pieces far smaller than any stroke. */
function despeckle({ pixels, w, h }, cut) {
  const limit = Math.max(2, 0.02 * Math.max(w, h));
  const seen = new Uint8Array(w * h);
  const stack = [];
  for (let start = 0; start < pixels.length; start += 1) {
    if (seen[start] || pixels[start] >= cut) continue;
    let left = w;
    let right = 0;
    let top = h;
    let bottom = 0;
    const members = [];
    stack.push(start);
    seen[start] = 1;
    while (stack.length) {
      const at = stack.pop();
      members.push(at);
      const x = at % w;
      const y = (at - x) / w;
      if (x < left) left = x;
      if (x > right) right = x;
      if (y < top) top = y;
      if (y > bottom) bottom = y;
      for (let dy = -1; dy <= 1; dy += 1) {
        for (let dx = -1; dx <= 1; dx += 1) {
          const nx = x + dx;
          const ny = y + dy;
          if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
          const next = ny * w + nx;
          if (!seen[next] && pixels[next] < cut) {
            seen[next] = 1;
            stack.push(next);
          }
        }
      }
    }
    if (Math.max(right - left, bottom - top) + 1 >= limit) continue;
    for (let y = Math.max(0, top - 1); y <= Math.min(h - 1, bottom + 1); y += 1) {
      for (let x = Math.max(0, left - 1); x <= Math.min(w - 1, right + 1); x += 1) pixels[y * w + x] = 1;
    }
  }
}

/** The tilt in degrees whose removal makes the row and column profiles sharpest. */
function skew({ pixels, w, h }, cut) {
  const step = Math.max(1, Math.ceil(Math.max(w, h) / 160));
  const xs = [];
  const ys = [];
  for (let y = 0; y < h; y += step) {
    for (let x = 0; x < w; x += step) {
      if (pixels[y * w + x] < cut) {
        xs.push((x - w / 2) / step);
        ys.push((y - h / 2) / step);
      }
    }
  }
  if (xs.length < 40) return 0;
  const span = Math.ceil(Math.hypot(w, h) / step) + 4;
  const rows = new Float64Array(span);
  const columns = new Float64Array(span);
  const sharpness = degrees => {
    const radians = (degrees * Math.PI) / 180;
    const cos = Math.cos(radians);
    const sin = Math.sin(radians);
    rows.fill(0);
    columns.fill(0);
    for (let index = 0; index < xs.length; index += 1) {
      const column = xs[index] * cos + ys[index] * sin + span / 2;
      const row = -xs[index] * sin + ys[index] * cos + span / 2;
      const c0 = Math.floor(column);
      const r0 = Math.floor(row);
      columns[c0] += 1 - (column - c0);
      columns[c0 + 1] += column - c0;
      rows[r0] += 1 - (row - r0);
      rows[r0 + 1] += row - r0;
    }
    let total = 0;
    for (let index = 0; index < span; index += 1) total += rows[index] * rows[index] + columns[index] * columns[index];
    return total;
  };
  const level = sharpness(0);
  let best = 0;
  let bestScore = level;
  for (let degrees = -12; degrees <= 12; degrees += 1) {
    const score = sharpness(degrees);
    if (score > bestScore) {
      bestScore = score;
      best = degrees;
    }
  }
  if (best === 0 || bestScore < 1.04 * level) return 0;
  const coarse = best;
  for (let degrees = coarse - 1; degrees <= coarse + 1; degrees += 0.25) {
    const score = sharpness(degrees);
    if (score > bestScore) {
      bestScore = score;
      best = degrees;
    }
  }
  return best;
}

/** Turn the image about its centre, growing the canvas so nothing is cut. */
function rotate({ pixels, w, h }, degrees) {
  const radians = (degrees * Math.PI) / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  const nw = Math.ceil(Math.abs(w * cos) + Math.abs(h * sin));
  const nh = Math.ceil(Math.abs(w * sin) + Math.abs(h * cos));
  const out = new Float32Array(nw * nh).fill(1);
  for (let y = 0; y < nh; y += 1) {
    for (let x = 0; x < nw; x += 1) {
      const dx = x - nw / 2;
      const dy = y - nh / 2;
      const sx = dx * cos + dy * sin + w / 2;
      const sy = -dx * sin + dy * cos + h / 2;
      const x0 = Math.floor(sx);
      const y0 = Math.floor(sy);
      if (x0 < 0 || y0 < 0 || x0 >= w - 1 || y0 >= h - 1) continue;
      const fx = sx - x0;
      const fy = sy - y0;
      const at = y0 * w + x0;
      out[y * nw + x] = (pixels[at] * (1 - fx) + pixels[at + 1] * fx) * (1 - fy)
        + (pixels[at + w] * (1 - fx) + pixels[at + w + 1] * fx) * fy;
    }
  }
  return { pixels: out, w: nw, h: nh };
}

function inkBox({ pixels, w, h }, cut) {
  let left = w;
  let right = -1;
  let top = h;
  let bottom = -1;
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      if (pixels[y * w + x] >= cut) continue;
      if (x < left) left = x;
      if (x > right) right = x;
      if (y < top) top = y;
      if (y > bottom) bottom = y;
    }
  }
  if (right < 0) return { left: 0, top: 0, right: w, bottom: h };
  return { left, top, right: right + 1, bottom: bottom + 1 };
}

/** Scale the ink box to leave the margin on its longer side and centre it on white. */
function frame({ pixels, w, h }, box, margin) {
  const bw = box.right - box.left;
  const bh = box.bottom - box.top;
  const scale = (SIZE - 2 * margin) / Math.max(bw, bh);
  const ox = (SIZE - bw * scale) / 2;
  const oy = (SIZE - bh * scale) / 2;
  const out = new Float32Array(SIZE * SIZE).fill(1);
  const reach = Math.max(1, 1 / scale);
  for (let y = 0; y < SIZE; y += 1) {
    const sy = (y - oy) / scale + box.top;
    if (sy < box.top - reach || sy > box.bottom + reach) continue;
    for (let x = 0; x < SIZE; x += 1) {
      const sx = (x - ox) / scale + box.left;
      if (sx < box.left - reach || sx > box.right + reach) continue;
      out[y * SIZE + x] = scale < 1 ? average(pixels, w, h, sx, sy, reach) : bilinear(pixels, w, h, sx, sy);
    }
  }
  return out;
}

function bilinear(pixels, w, h, sx, sy) {
  const x = Math.min(w - 1, Math.max(0, sx - 0.5 + 0.5 * 0));
  const y = Math.min(h - 1, Math.max(0, sy));
  const x0 = Math.min(w - 2 < 0 ? 0 : w - 2, Math.floor(x));
  const y0 = Math.min(h - 2 < 0 ? 0 : h - 2, Math.floor(y));
  const fx = x - x0;
  const fy = y - y0;
  const at = y0 * w + x0;
  const right = w > 1 ? 1 : 0;
  const down = h > 1 ? w : 0;
  return (pixels[at] * (1 - fx) + pixels[at + right] * fx) * (1 - fy)
    + (pixels[at + down] * (1 - fx) + pixels[at + down + right] * fx) * fy;
}

function average(pixels, w, h, sx, sy, reach) {
  const x0 = Math.max(0, Math.floor(sx));
  const y0 = Math.max(0, Math.floor(sy));
  const x1 = Math.min(w, Math.max(x0 + 1, Math.ceil(sx + reach)));
  const y1 = Math.min(h, Math.max(y0 + 1, Math.ceil(sy + reach)));
  let total = 0;
  let count = 0;
  for (let y = y0; y < y1; y += 1) {
    for (let x = x0; x < x1; x += 1) {
      total += pixels[y * w + x];
      count += 1;
    }
  }
  return count ? total / count : 1;
}
