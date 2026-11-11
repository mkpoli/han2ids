#!/usr/bin/env node
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createStage } from '../static/stage.js';
import { createReading } from '../static/reading.js';

function setup() {
  class Element {
    constructor() {
      this.listeners = {}; this.dataset = {}; this.value = '2';
      this.style = { setProperty() {} }; this.classList = { add() {}, remove() {} };
    }
    addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
    dispatch(type, event = {}) {
      event.target ??= this; event.preventDefault ??= () => {};
      for (const fn of this.listeners[type] ?? []) fn(event);
    }
    closest() { return null; }
    focus() {}
    getBoundingClientRect() { return { left: 0, top: 0, width: 100, height: 100 }; }
  }
  const elements = new Map();
  const element = name => {
    if (!elements.has(name)) elements.set(name, new Element());
    return elements.get(name);
  };
  const names = ['margin', 'imageWrap', 'cropBox', 'boxLayer', 'marginValue', 'quickCut', 'autoCut', 'fullImage', 'recognize'];
  const els = Object.fromEntries(names.map(name => [name, element(name)]));
  const window = new Element();
  const timers = new Map(); let nextTimer = 0;
  const calls = [];
  const pixels = new Uint8ClampedArray(224 * 224 * 4).fill(255);
  const document = {
    createElement() { return { getContext() { return { fillRect() {}, drawImage() {}, getImageData() { return { data: pixels }; } }; } }; },
  };
  Object.assign(globalThis, {
    window, document,
    setTimeout(fn) { const id = ++nextTimer; timers.set(id, fn); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  const source = { id: 's', width: 100, height: 100, transparent: false, inkLight: false };
  const item = { id: 'i', sourceId: 's', crop: { x: 0.1, y: 0.1, w: 0.5, h: 0.5 },
    box: { x: 0.1, y: 0.1, w: 0.5, h: 0.5 }, margin: 2,
    readings: [], phase: 'queued', errorKey: null, seq: 0 };
  let stage, reading;
  stage = createStage({
    selectedItem: () => item, getSource: () => source, itemsOf: () => [item],
    onCropChanged: entry => reading.cropChanged(entry), scheduleRead: delay => reading.scheduleRead(delay),
    cancelScheduled: () => reading.cancelScheduled(),
  }, els);
  reading = createReading({
    selectedItem: () => item, byId: () => item, getSource: () => source,
    isDragging: () => stage.isDragging(), bitmapFor: async () => ({}), makeThumb: async () => {},
    touch() {}, cropInvalidated() {}, showModelProgress() {}, hideModelProgress() {}, setStatus() {},
    announceReading() {}, showError() {},
    loadInference: async () => ({ recognize: () => new Promise((resolve, reject) => calls.push({ resolve, reject })) }),
  }, els);
  return { stage, reading, item, window, element, calls, timers,
    flushTimers() { const pending = [...timers.values()]; timers.clear(); for (const fn of pending) fn(); },
  };
}
const tick = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const result = ids => [{ ids, score: 0.9, valid: true }];

test('a crop change clears a completed reading immediately', () => {
  const app = setup();
  app.item.readings = result('old'); app.item.phase = 'done';
  app.stage.setCrop({ x: 0.2, y: 0.1, w: 0.5, h: 0.5 });
  assert.deepEqual(app.item.readings, []);
  assert.equal(app.item.phase, 'queued');
  assert.ok(app.item.seq > 0);
});

test('a drag keeps the read timer from firing until release', () => {
  const app = setup();
  app.element('cropBox').dispatch('pointerdown', { button: 0, pointerId: 1, clientX: 20, clientY: 20 });
  app.stage.setCrop({ x: 0.2, y: 0.1, w: 0.5, h: 0.5 });
  assert.equal(app.timers.size, 0);
  app.window.dispatch('pointermove', { pointerId: 1, clientX: 30, clientY: 20 });
  app.window.dispatch('pointerup', { pointerId: 1 });
  assert.equal(app.timers.size, 1);
});

test('an edited crop rejects an in-flight reading and enqueues the replacement', async () => {
  const app = setup();
  app.reading.enqueue([app.item]);
  await tick();
  assert.equal(app.calls.length, 1);
  app.stage.setCrop({ x: 0.2, y: 0.1, w: 0.5, h: 0.5 });
  app.calls[0].resolve(result('stale'));
  await tick();
  assert.deepEqual(app.item.readings, []);
  app.flushTimers(); await tick();
  assert.equal(app.calls.length, 2);
  app.calls[1].resolve(result('fresh')); await tick();
  assert.equal(app.item.readings[0].ids, 'fresh');
});
