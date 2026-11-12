#!/usr/bin/env node
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { RAW, SIZE, prepare } from '../static/prepare.js';

/** A 200 px page with three bars and a stem of ink, drawn with the given paper and ink levels. */
function page({ paper = 255, ink = 0, tilt = 0, specks = false, shade = false } = {}) {
  const width = 200;
  const height = 200;
  const data = new Uint8ClampedArray(width * height * 4);
  const radians = (tilt * Math.PI) / 180;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const dx = x - 100;
      const dy = y - 100;
      const u = dx * Math.cos(radians) + dy * Math.sin(radians);
      const v = -dx * Math.sin(radians) + dy * Math.cos(radians);
      const bar = Math.abs(u) < 50 && (Math.abs(v) < 4 || Math.abs(v - 26) < 4 || Math.abs(v + 26) < 4);
      let value = bar || (Math.abs(u) < 4 && Math.abs(v) < 30) ? ink : paper;
      if (specks && x % 37 === 5 && y % 41 === 7) value = ink;
      if (shade) value *= 0.6 + (0.4 * x) / width;
      data.set([value, value, value, 255], (y * width + x) * 4);
    }
  }
  return { data, width, height };
}

function inkBox(view) {
  let left = SIZE, right = 0, top = SIZE, bottom = 0, count = 0;
  for (let y = 0; y < SIZE; y += 1) {
    for (let x = 0; x < SIZE; x += 1) {
      if (view[y * SIZE + x] >= 0.5) continue;
      left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y);
      count += 1;
    }
  }
  return { left, right, top, bottom, count };
}

test('ink is framed with the margin on its longer side, centred', () => {
  const box = inkBox(prepare(page()).view);
  assert.ok(Math.abs(box.left - 12) <= 1 && Math.abs(box.right - 211) <= 1, JSON.stringify(box));
  assert.ok(Math.abs(box.top + box.bottom - (SIZE - 1)) <= 2);
});

test('grey paper, shade and light-on-dark all come out as black ink on white', () => {
  for (const options of [{ paper: 200, ink: 60 }, { paper: 230, ink: 40, shade: true }, { paper: 20, ink: 235 },
    { paper: 100, ink: 20 }, { paper: 150, ink: 250 }]) {
    const { view } = prepare(page(options));
    assert.ok(view[0] > 0.95, `paper ${JSON.stringify(options)}`);
    assert.ok(view[(SIZE / 2) * SIZE + SIZE / 2] < 0.05, `ink ${JSON.stringify(options)}`);
  }
});

test('specks are erased and do not widen the frame', () => {
  const clean = inkBox(prepare(page()).view);
  const speckled = inkBox(prepare(page({ specks: true })).view);
  assert.ok(Math.abs(speckled.count - clean.count) / clean.count < 0.02);
});

test('a tilt is measured and removed; an upright glyph is left alone', () => {
  assert.equal(prepare(page()).angle, 0);
  const tilted = prepare(page({ tilt: 6 }));
  assert.ok(Math.abs(tilted.angle - 6) <= 0.5, String(tilted.angle));
  const box = inkBox(tilted.view);
  assert.ok((box.bottom - box.top) / (box.right - box.left) < 0.66);
});

test('the raw options keep the speck and the tilt', () => {
  assert.equal(prepare(page({ tilt: 6 }), RAW).angle, 0);
  const raw = inkBox(prepare(page({ specks: true }), RAW).view);
  assert.ok(raw.right - raw.left > 0 && raw.count > 0);
});

test('the tensor repeats the frame on three channels in -1..1', () => {
  const { input, view } = prepare(page());
  assert.equal(input.length, 3 * SIZE * SIZE);
  assert.equal(input[0], (view[0] - 0.5) / 0.5);
  assert.equal(input[2 * SIZE * SIZE + 5], input[5]);
});

test('a small cut keeps a dot wider than 2% of its side', () => {
  const width = 20;
  const data = new Uint8ClampedArray(width * width * 4).fill(255);
  const ink = (x, y) => data.set([0, 0, 0, 255], (y * width + x) * 4);
  for (let x = 4; x < 16; x += 1) ink(x, 14);
  ink(10, 5);
  const box = inkBox(prepare({ data, width, height: width }).view);
  assert.ok(box.bottom - box.top > 0.6 * (box.right - box.left), JSON.stringify(box));
});
