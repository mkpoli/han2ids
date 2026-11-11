#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import assert from 'node:assert/strict';
import { test } from 'node:test';

function setup() {
  const elements = new Map();
  class Element {
    constructor() {
      this.listeners = {};
      this.dataset = {};
      this.style = { setProperty() {} };
      this.classList = { add() {}, remove() {} };
      this.hidden = false;
      this.value = '2';
      this.children = [];
      this.attributes = {};
    }
    addEventListener(type, handler) { (this.listeners[type] ??= []).push(handler); }
    dispatch(type, event = {}) {
      event.preventDefault ??= () => {};
      event.target ??= this;
      for (const handler of this.listeners[type] ?? []) handler(event);
    }
    setAttribute(name, value) { this.attributes[name] = value; }
    removeAttribute(name) { delete this.attributes[name]; }
    getAttribute(name) { return this.attributes[name] ?? null; }
    replaceChildren(...children) { this.children = children; }
    append(...children) { this.children.push(...children); }
    querySelectorAll() { return []; }
    closest() { return null; }
    focus() {}
    getBoundingClientRect() { return { left: 0, top: 0, width: 100, height: 100 }; }
  }
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const document = new Element();
  document.documentElement = new Element();
  document.body = new Element();
  document.querySelector = selector => selector.startsWith('#') ? element(selector.slice(1)) : null;
  document.querySelectorAll = () => [];
  document.createElement = () => new Element();
  document.createDocumentFragment = () => new Element();
  document.createTextNode = text => ({ textContent: text });
  const window = new Element();
  const timers = new Map();
  let timerId = 0;
  const calls = [];
  const clipboard = [];
  const context = {
    document, window,
    localStorage: { getItem() { return null; } },
    location: { search: '' },
    navigator: { languages: [], clipboard: { async writeText(text) { clipboard.push(text); } } },
    URL, URLSearchParams,
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; },
    clearTimeout(id) { timers.delete(id); },
    requestAnimationFrame() {},
    DEFAULT_LOCALE: 'en',
    LOCALES: { en: { htmlLang: 'en', label: 'English', code: 'EN', messages: {} } },
    matchLocale() { return null; },
  };
  const source = readFileSync(new URL('./static/app.js', import.meta.url), 'utf8')
    .replace(/^import .*?;\s*/, '');
  context.calls = calls;
  runInNewContext(`${source}\nmakeModelInput = () => new Float32Array(1);\nloadInference = async () => ({ recognize: () => new Promise((resolve, reject) => calls.push({ resolve, reject })) });\nglobalThis.app = { state, setCrop, readNow, showReadings, resetResult };`, context);
  return { ...context, ...context.app, element, calls, clipboard, timers,
    flushTimers() { const pending = [...timers.values()]; timers.clear(); for (const fn of pending) fn(); },
  };
}

const reading = ids => [{ ids, score: 0.9, valid: true }];
const tick = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };

function prepare() {
  const app = setup();
  app.state.natural = { width: 100, height: 100 };
  app.state.crop = { x: 0.1, y: 0.1, w: 0.5, h: 0.5 };
  return app;
}

test('crop mutation immediately removes readings and rejects old success and error', async () => {
  for (const failure of [false, true]) {
    const app = prepare();
    app.showReadings(reading('old'));
    app.readNow();
    await tick();
    app.setCrop({ x: 0.2, y: 0.1, w: 0.5, h: 0.5 });
    assert.equal(app.element('result-body').hidden, true);
    assert.equal(app.element('open-workshop').getAttribute('href'), null);
    app.element('copy-ids').dispatch('click');
    assert.deepEqual(app.clipboard, []);
    if (failure) app.calls[0].reject(new Error('stale'));
    else app.calls[0].resolve(reading('stale'));
    await tick();
    assert.equal(app.element('result-body').hidden, true);
    assert.equal(app.element('result-error').hidden, true);
    app.flushTimers();
    await tick();
    app.calls[1].resolve(reading('fresh'));
    await tick();
    assert.equal(app.state.readings[0].ids, 'fresh');
    assert.equal(app.element('result-body').hidden, false);
  }
});

test('drag holds queued inference until release and invalidates on actual movement', async () => {
  const app = prepare();
  app.readNow();
  await tick();
  app.readNow(); // queued before the drag
  app.element('crop-box').dispatch('pointerdown', { button: 0, pointerId: 1, clientX: 20, clientY: 20 });
  app.calls[0].resolve(reading('first'));
  await tick();
  assert.equal(app.calls.length, 1);
  app.window.dispatch('pointermove', { pointerId: 1, clientX: 30, clientY: 20 });
  assert.equal(app.state.readings.length, 0);
  app.flushTimers();
  await tick();
  assert.equal(app.calls.length, 1);
  app.window.dispatch('pointerup', { pointerId: 1 });
  app.flushTimers();
  await tick();
  assert.equal(app.calls.length, 2);
  app.calls[1].resolve(reading('fresh'));
  await tick();
  assert.equal(app.state.readings[0].ids, 'fresh');
});

test('unmoved drag preserves readings and resumes a pending read', async () => {
  const app = prepare();
  app.showReadings(reading('old'));
  app.setCrop({ ...app.state.crop });
  app.element('crop-box').dispatch('pointerdown', { button: 0, pointerId: 1, clientX: 20, clientY: 20 });
  app.flushTimers();
  await tick();
  assert.equal(app.calls.length, 0);
  assert.equal(app.state.readings[0].ids, 'old');
  app.window.dispatch('pointerup', { pointerId: 1 });
  app.flushTimers();
  await tick();
  assert.equal(app.calls.length, 1);
});

test('drag invalidates a running read before release, including lost capture', async () => {
  const app = prepare();
  app.readNow();
  await tick();
  app.element('crop-box').dispatch('pointerdown', { button: 0, pointerId: 1, clientX: 20, clientY: 20 });
  app.window.dispatch('pointermove', { pointerId: 2, clientX: 50, clientY: 20 });
  assert.equal(app.state.crop.x, 0.1);
  app.window.dispatch('pointermove', { pointerId: 1, clientX: 30, clientY: 20 });
  app.calls[0].resolve(reading('stale'));
  await tick();
  assert.equal(app.state.readings.length, 0);
  assert.equal(app.calls.length, 1);
  app.element('crop-box').dispatch('lostpointercapture', { pointerId: 1 });
  app.flushTimers();
  await tick();
  assert.equal(app.calls.length, 2);
  app.calls[1].resolve(reading('fresh'));
  await tick();
  assert.equal(app.state.readings[0].ids, 'fresh');
});

test('full image and margin changes invalidate queued reads and use the latest crop', async () => {
  const app = prepare();
  app.state.inkBox = { x: 0.2, y: 0.2, w: 0.4, h: 0.4 };
  app.readNow();
  await tick();
  app.element('full-image').dispatch('click');
  app.flushTimers();
  assert.equal(app.state.queued, true);
  app.element('margin').value = '10';
  app.element('margin').dispatch('input');
  assert.equal(app.state.queued, false);
  app.calls[0].resolve(reading('stale'));
  await tick();
  assert.equal(app.calls.length, 1);
  assert.equal(app.state.readings.length, 0);
  app.flushTimers();
  await tick();
  assert.equal(app.calls.length, 2);
  app.calls[1].resolve(reading('fresh'));
  await tick();
  assert.equal(app.state.readings[0].ids, 'fresh');
});

test('copy feedback expires when a reread of the same crop fails', async () => {
  const app = prepare();
  app.showReadings(reading('old'));
  app.element('copy-ids').dispatch('click');
  await tick();
  assert.equal(app.state.copied, true);
  app.readNow();
  await tick();
  app.calls[0].reject(new Error('read failed'));
  await tick();
  assert.equal(app.state.readings[0].ids, 'old');
  app.flushTimers();
  assert.equal(app.state.copied, false);
  assert.equal(app.element('copy-ids').textContent, 'reading.copy');
});

test('a rejected pending copy never falls back after a crop change', async () => {
  const app = prepare();
  let rejectCopy;
  app.navigator.clipboard.writeText = () => new Promise((resolve, reject) => { rejectCopy = reject; });
  app.showReadings(reading('old'));
  app.element('copy-ids').dispatch('click');
  app.setCrop({ x: 0.2, y: 0.1, w: 0.5, h: 0.5 });
  rejectCopy(new Error('unavailable'));
  await tick();
  assert.equal(app.document.body.children.length, 0);
  assert.equal(app.element('live-status').textContent, '');
});

test('keyboard crop changes discard the old in-flight result before debounce', async () => {
  const app = prepare();
  app.readNow();
  await tick();
  app.element('crop-box').dispatch('keydown', { key: 'ArrowRight' });
  app.calls[0].resolve(reading('stale'));
  await tick();
  assert.equal(app.state.readings.length, 0);
  app.flushTimers();
  await tick();
  app.calls[1].resolve(reading('fresh'));
  await tick();
  assert.equal(app.state.readings[0].ids, 'fresh');
});
