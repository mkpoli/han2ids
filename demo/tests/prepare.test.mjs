#!/usr/bin/env node
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  carryPoint, estimateSkew, frameScale, frameSize, greyLevels, inkAmountFor, inkMask, inkSide, MAX_FRAME_PIXELS,
  normaliseTurn, removeSpecks, snapTurn, turnedSize,
} from '../static/prepare.js';

/** A mask with filled rectangles [x, y, w, h], turned `degrees` clockwise about the centre. */
function draw(width, height, rects, degrees = 0) {
  const mask = new Uint8Array(width * height);
  const radians = (-degrees * Math.PI) / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const dx = x + 0.5 - width / 2;
      const dy = y + 0.5 - height / 2;
      const sx = dx * cos - dy * sin + width / 2;
      const sy = dx * sin + dy * cos + height / 2;
      if (rects.some(([rx, ry, rw, rh]) => sx >= rx && sx < rx + rw && sy >= ry && sy < ry + rh)) {
        mask[y * width + x] = 1;
      }
    }
  }
  return mask;
}

/** Strokes of 田 in a size × size cell at (x, y). */
const glyph = {
  tian: (x, y, s) => [
    [x + s * 0.1, y + s * 0.1, s * 0.8, s * 0.07], [x + s * 0.1, y + s * 0.48, s * 0.8, s * 0.07], [x + s * 0.1, y + s * 0.85, s * 0.8, s * 0.07],
    [x + s * 0.1, y + s * 0.1, s * 0.07, s * 0.82], [x + s * 0.47, y + s * 0.1, s * 0.07, s * 0.82], [x + s * 0.83, y + s * 0.1, s * 0.07, s * 0.82],
  ],
};

test('ink side follows the paper, and the ink amount runs the same way on both papers', () => {
  const width = 20;
  const height = 20;
  const light = new Uint8Array(width * height).fill(250);
  for (let y = 6; y < 14; y += 1) for (let x = 6; x < 14; x += 1) light[y * width + x] = 10;
  const dark = light.map(value => 255 - value);
  const onLight = inkSide(light, width, height);
  const onDark = inkSide(dark, width, height);
  assert.equal(onLight.brightPaper, true);
  assert.equal(onDark.brightPaper, false);
  const lightMask = inkMask(light, inkAmountFor(onLight.threshold, true), true);
  const darkMask = inkMask(dark, inkAmountFor(onDark.threshold, false), false);
  assert.deepEqual(lightMask, darkMask);
  assert.equal(lightMask.reduce((a, b) => a + b, 0), 64);
  assert.equal(inkMask(light, 255, true).reduce((a, b) => a + b, 0), width * height);
  assert.equal(inkMask(light, 0, true).reduce((a, b) => a + b, 0), 0);
});

test('grey levels weight the channels', () => {
  assert.deepEqual([...greyLevels(new Uint8ClampedArray([255, 255, 255, 255, 0, 0, 0, 255]))], [255, 0]);
});

test('specks go and strokes stay', () => {
  const width = 80;
  const height = 80;
  const mask = draw(width, height, glyph.tian(10, 10, 60));
  const strokes = mask.reduce((a, b) => a + b, 0);
  mask[2 * width + 2] = 1;
  mask[77 * width + 5] = 1;
  mask[78 * width + 5] = 1;
  const cleared = removeSpecks(mask, width, height);
  assert.equal(cleared, 3);
  assert.equal(mask.reduce((a, b) => a + b, 0), strokes);
});

test('skew is measured as the turn that straightens the strokes', () => {
  for (const tilt of [-7, 4.5]) {
    const mask = draw(160, 160, glyph.tian(30, 30, 100), tilt);
    const turn = estimateSkew(mask, 160, 160);
    assert.ok(Math.abs(turn + tilt) <= 0.6, `tilt ${tilt} measured ${turn}`);
  }
  assert.ok(Math.abs(estimateSkew(draw(160, 160, glyph.tian(30, 30, 100)), 160, 160)) <= 0.2);
});

test('turns fold, snap and size their frames', () => {
  assert.equal(normaliseTurn(270), -90);
  assert.equal(normaliseTurn(-180), 180);
  assert.equal(snapTurn(91.2), 90);
  assert.equal(snapTurn(3), 3);
  assert.deepEqual(turnedSize(200, 100, 90), { width: 100, height: 200 });
  assert.deepEqual(turnedSize(100, 100, 45), { width: 141, height: 141 });
  const from = { width: 200, height: 100, turn: 0 };
  const to = { width: 100, height: 200, turn: 90 };
  const there = carryPoint({ x: 0.75, y: 0.5 }, from, to);
  assert.ok(Math.abs(there.x - 0.5) < 1e-9 && Math.abs(there.y - 0.75) < 1e-9);
  const back = carryPoint(there, to, from);
  assert.ok(Math.abs(back.x - 0.75) < 1e-9 && Math.abs(back.y - 0.5) < 1e-9);
});

test('enlarging stays within the frame budget and never shrinks', () => {
  assert.equal(frameScale(200, 200, 2), 2);
  assert.equal(frameScale(5000, 4000, 1), 1);
  assert.equal(frameScale(5000, 4000, 4), 1);
  assert.deepEqual(frameSize({ width: 200, height: 100, prep: { enlarge: 2, turn: 90 } }), { width: 200, height: 400 });
  const scale = frameScale(2000, 2000, 4);
  assert.ok(scale > 1 && 2000 * 2000 * scale * scale <= MAX_FRAME_PIXELS + 1);
});
