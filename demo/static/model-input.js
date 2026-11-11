import { clamp } from './geometry.js';

/** The model's 224 × 224 input for a cut of the prepared image. */
export function modelInput(image, crop) {
  const naturalWidth = image.width;
  const naturalHeight = image.height;
  const { x, y, w, h } = crop;

  const sx = clamp(Math.floor(x * naturalWidth), 0, naturalWidth - 1);
  const sy = clamp(Math.floor(y * naturalHeight), 0, naturalHeight - 1);
  const ex = clamp(Math.ceil((x + w) * naturalWidth), sx + 1, naturalWidth);
  const ey = clamp(Math.ceil((y + h) * naturalHeight), sy + 1, naturalHeight);
  const sourceWidth = ex - sx;
  const sourceHeight = ey - sy;
  const scale = 224 / Math.max(sourceWidth, sourceHeight);
  const width = Math.max(1, Math.round(sourceWidth * scale));
  const height = Math.max(1, Math.round(sourceHeight * scale));

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = 'high';
  context.drawImage(image, sx, sy, sourceWidth, sourceHeight, 0, 0, width, height);
  const pixels = context.getImageData(0, 0, width, height).data;

  const gray = new Float32Array(width * height);
  let mean = 0;
  for (let index = 0; index < gray.length; index += 1) {
    const offset = index * 4;
    const value = 0.299 * pixels[offset] + 0.587 * pixels[offset + 1] + 0.114 * pixels[offset + 2];
    gray[index] = value;
    mean += value;
  }
  const invert = mean / gray.length < 127;
  const data = new Float32Array(3 * 224 * 224);
  data.fill(1);
  const left = Math.floor((224 - width) / 2);
  const top = Math.floor((224 - height) / 2);
  for (let row = 0; row < height; row += 1) {
    for (let column = 0; column < width; column += 1) {
      let value = gray[row * width + column];
      if (invert) value = 255 - value;
      const normalized = (value / 255 - 0.5) / 0.5;
      const target = (top + row) * 224 + left + column;
      data[target] = normalized;
      data[224 * 224 + target] = normalized;
      data[2 * 224 * 224 + target] = normalized;
    }
  }
  return data;
}
