import { clamp } from './geometry.js';
import { prepare } from './prepare.js';

const MAX_SIDE = 640;

/** The crop's pixels, prepared for the model: its tensor and the greyscale frame it shows. */
export function modelInput(bitmap, source, crop, options) {
  const sx = clamp(Math.floor(crop.x * source.width), 0, source.width - 1);
  const sy = clamp(Math.floor(crop.y * source.height), 0, source.height - 1);
  const ex = clamp(Math.ceil((crop.x + crop.w) * source.width), sx + 1, source.width);
  const ey = clamp(Math.ceil((crop.y + crop.h) * source.height), sy + 1, source.height);
  const scale = Math.min(1, MAX_SIDE / Math.max(ex - sx, ey - sy));
  const width = Math.max(1, Math.round((ex - sx) * scale));
  const height = Math.max(1, Math.round((ey - sy) * scale));

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = 'high';
  context.drawImage(bitmap, sx, sy, ex - sx, ey - sy, 0, 0, width, height);
  return prepare({ data: context.getImageData(0, 0, width, height).data, width, height }, options);
}
