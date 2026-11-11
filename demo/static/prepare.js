/* Image preparation: grey levels, black and white, specks, skew and the turned frame.
   Every function works on plain typed arrays, so the checks run in Node without a canvas.
   Where the glyphs are is detect.js's job. */

import { otsu } from './detect.js';

/** Largest working frame, in pixels. Enlarging stops short of it. */
export const MAX_FRAME_PIXELS = 8_000_000;

/** Turns within this many degrees of a quarter turn land on it. */
export const SNAP_DEGREES = 1.5;

/** How an image is prepared before it is cut and read. */
export const DEFAULT_PREP = Object.freeze({ turn: 0, enlarge: 1, bw: false, ink: null, specks: false });

/** Grey level (0–255) of each RGBA pixel. */
export function greyLevels(rgba, out = new Uint8Array(rgba.length / 4)) {
  for (let index = 0, offset = 0; index < out.length; index += 1, offset += 4) {
    out[index] = (0.299 * rgba[offset] + 0.587 * rgba[offset + 1] + 0.114 * rgba[offset + 2] + 0.5) | 0;
  }
  return out;
}

function histogramOf(grey) {
  const histogram = new Uint32Array(256);
  for (let index = 0; index < grey.length; index += 1) histogram[grey[index]] += 1;
  return histogram;
}

/**
 * The automatic split between ink and paper, and which side the paper is on. The paper is the
 * side the image's border falls on.
 */
export function inkSide(grey, width, height) {
  const threshold = otsu(histogramOf(grey), grey.length);
  const border = Math.max(1, Math.round(Math.min(width, height) * 0.02));
  let total = 0;
  let count = 0;
  for (let y = 0; y < height; y += 1) {
    const edgeRow = y < border || y >= height - border;
    for (let x = 0; x < width; x += 1) {
      if (!edgeRow && x >= border && x < width - border) {
        x = width - border - 1;
        continue;
      }
      total += grey[y * width + x];
      count += 1;
    }
  }
  const paper = count ? total / count : 255;
  return { threshold, brightPaper: paper > threshold };
}

/**
 * Ink-slider value for a threshold. The slider runs from less ink to more ink whichever way
 * round the paper is, so the same value means the same thing on dark and light paper.
 */
export function inkAmountFor(threshold, brightPaper) {
  return brightPaper ? threshold : 255 - threshold;
}

/** 1 where a pixel is ink at the given ink amount (0–255, more is more ink). */
export function inkMask(grey, amount, brightPaper, out = new Uint8Array(grey.length)) {
  if (brightPaper) {
    for (let index = 0; index < grey.length; index += 1) out[index] = grey[index] <= amount ? 1 : 0;
  } else {
    const cut = 255 - amount;
    for (let index = 0; index < grey.length; index += 1) out[index] = grey[index] > cut ? 1 : 0;
  }
  return out;
}

/**
 * Clears ink components too small to be a stroke: below `fraction` of all ink, and never
 * fewer than `minimum` pixels. Returns the number of pixels cleared.
 */
export function removeSpecks(mask, width, height, { fraction = 0.0015, minimum = 3 } = {}) {
  let ink = 0;
  for (let index = 0; index < mask.length; index += 1) ink += mask[index];
  if (!ink) return 0;
  const limit = Math.max(minimum, ink * fraction);

  const seen = new Uint8Array(mask.length);
  const stack = new Int32Array(mask.length);
  const component = [];
  let cleared = 0;

  for (let start = 0; start < mask.length; start += 1) {
    if (!mask[start] || seen[start]) continue;
    let top = 0;
    stack[top++] = start;
    seen[start] = 1;
    component.length = 0;
    let large = false;
    while (top) {
      const at = stack[--top];
      if (!large) {
        component.push(at);
        large = component.length >= limit;
      }
      const x = at % width;
      const y = (at - x) / width;
      for (let dy = -1; dy <= 1; dy += 1) {
        const ny = y + dy;
        if (ny < 0 || ny >= height) continue;
        for (let dx = -1; dx <= 1; dx += 1) {
          const nx = x + dx;
          if (nx < 0 || nx >= width) continue;
          const next = ny * width + nx;
          if (mask[next] && !seen[next]) {
            seen[next] = 1;
            stack[top++] = next;
          }
        }
      }
    }
    if (!large) {
      for (const at of component) mask[at] = 0;
      cleared += component.length;
    }
  }
  return cleared;
}

/**
 * The turn, in degrees clockwise, that best lines the ink's strokes up with the frame: the
 * angle whose row and column profiles are sharpest. Searches ±range.
 */
export function estimateSkew(mask, width, height, { range = 15, samples = 40_000 } = {}) {
  let ink = 0;
  for (let index = 0; index < mask.length; index += 1) ink += mask[index];
  if (ink < 16) return 0;
  const stride = Math.max(1, Math.floor(ink / samples));
  const count = Math.ceil(ink / stride);
  const xs = new Float32Array(count);
  const ys = new Float32Array(count);
  let seen = 0;
  let taken = 0;
  for (let index = 0; index < mask.length && taken < count; index += 1) {
    if (!mask[index]) continue;
    if (seen++ % stride) continue;
    const x = index % width;
    xs[taken] = x - width / 2;
    ys[taken] = (index - x) / width - height / 2;
    taken += 1;
  }

  const size = Math.ceil(Math.hypot(width, height)) + 2;
  const rows = new Uint32Array(size);
  const columns = new Uint32Array(size);
  const half = size / 2;
  const sharpness = degrees => {
    const radians = (degrees * Math.PI) / 180;
    const cos = Math.cos(radians);
    const sin = Math.sin(radians);
    rows.fill(0);
    columns.fill(0);
    for (let index = 0; index < taken; index += 1) {
      const x = xs[index];
      const y = ys[index];
      columns[(x * cos - y * sin + half) | 0] += 1;
      rows[(x * sin + y * cos + half) | 0] += 1;
    }
    let score = 0;
    for (let index = 0; index < size; index += 1) score += rows[index] ** 2 + columns[index] ** 2;
    return score;
  };

  let best = 0;
  let bestScore = sharpness(0);
  for (let degrees = -range; degrees <= range; degrees += 0.5) {
    const score = sharpness(degrees);
    if (score > bestScore) {
      bestScore = score;
      best = degrees;
    }
  }
  const coarse = best;
  for (let degrees = coarse - 0.5; degrees <= coarse + 0.5; degrees += 0.1) {
    const score = sharpness(degrees);
    if (score > bestScore) {
      bestScore = score;
      best = degrees;
    }
  }
  return Math.round(best * 10) / 10;
}

/** A turn folded into (-180, 180]. */
export function normaliseTurn(degrees) {
  const folded = ((((degrees + 180) % 360) + 360) % 360) - 180;
  return folded === -180 ? 180 : folded === 0 ? 0 : folded;
}

/** A turn that lands on the nearest quarter turn when it is within SNAP_DEGREES of it. */
export function snapTurn(degrees) {
  const quarter = Math.round(degrees / 90) * 90;
  return normaliseTurn(Math.abs(degrees - quarter) <= SNAP_DEGREES ? quarter : degrees);
}

/** Size of the frame that holds a width × height image turned by `degrees`. */
export function turnedSize(width, height, degrees) {
  const radians = (degrees * Math.PI) / 180;
  const cos = Math.abs(Math.cos(radians));
  const sin = Math.abs(Math.sin(radians));
  const round = value => Math.max(1, Math.round(value - 1e-6));
  return { width: round(width * cos + height * sin), height: round(width * sin + height * cos) };
}

/** The enlargement actually used: the chosen one, reduced so the frame stays in budget. */
export function frameScale(width, height, enlarge) {
  if (enlarge <= 1) return 1;
  const room = Math.sqrt(MAX_FRAME_PIXELS / Math.max(1, width * height));
  return Math.max(1, Math.min(enlarge, room));
}

/** Size of a source's frame: the image enlarged, then turned. */
export function frameSize({ width, height, prep }, turn = prep.turn) {
  const scale = frameScale(width, height, prep.enlarge);
  return turnedSize(width * scale, height * scale, turn);
}

/** Where a point of one turned frame lands in another, as fractions of each frame. */
export function carryPoint(point, from, to) {
  const radians = ((to.turn - from.turn) * Math.PI) / 180;
  const x = (point.x - 0.5) * from.width;
  const y = (point.y - 0.5) * from.height;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  return {
    x: (x * cos - y * sin) / to.width + 0.5,
    y: (x * sin + y * cos) / to.height + 0.5,
  };
}
