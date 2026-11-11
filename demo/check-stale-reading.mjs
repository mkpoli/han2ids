#!/usr/bin/env node
// Crop changes must discard the old item reading and reject an in-flight decode.
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
      this.classList = { add() {}, remove() {}, toggle() {} };
      this.hidden = false;
      this.value = '2';
      this.children = [];
      this.attributes = {};
      this.textContent = '';
    }
    addEventListener(type, handler) { (this.listeners[type] ??= []).push(handler); }
    dispatch(type, event = {}) {
      event.preventDefault ??= () => {};
      event.target ??= this;
      for (const handler of this.listeners[type] ?? []) handler(event);
    }
    get href() { return this.getAttribute('href'); }
    set href(value) { this.setAttribute('href', value); }
    setAttribute(name, value) { this.attributes[name] = value; }
    removeAttribute(name) { delete this.attributes[name]; }
    getAttribute(name) { return this.attributes[name] ?? null; }
    replaceChildren(...children) { this.children = children; }
    append(...children) { this.children.push(...children); }
    querySelectorAll() { return []; }
    closest() { return null; }
    focus() {}
    select() {}
    remove() {}
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
  document.execCommand = () => true;
  const window = new Element();
  const timers = new Map();
  let timerId = 0;
  const calls = [];
  const store = {
    load: async () => ({ items: [], sources: [], order: [] }),
    save: async () => {},
    clear: async () => {},
  };
  const context = {
    document, window,
    localStorage: {
      getItem() { return null; },
      setItem() {},
      removeItem() {},
    },
    location: { search: '' },
    navigator: { languages: [], language: 'en', clipboard: { async writeText() {} } },
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    URL, URLSearchParams,
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; },
    clearTimeout(id) { timers.delete(id); },
    requestAnimationFrame() {},
    DEFAULT_LOCALE: 'en',
    LOCALES: { en: { htmlLang: 'en', label: 'English', code: 'EN', messages: {} } },
    matchLocale() { return null; },
    analyseImage: () => ({ boxes: [], inkBox: { x: 0, y: 0, w: 1, h: 1 } }),
    IDC: /[\u2FF0-\u2FFF\u303E\u31EF]/,
    validIds: () => true,
    store,
  };
  const source = readFileSync(new URL('./static/app.js', import.meta.url), 'utf8')
    .replace(/^import .*?;\s*/gm, '');
  runInNewContext(`${source}
globalThis.app = { state, setCrop, renderResult };`, context);
  return { ...context, ...context.app, element, calls, timers,
    flushTimers() { const pending = [...timers.values()]; timers.clear(); for (const fn of pending) fn(); },
  };
}

const reading = ids => [{ ids, score: 0.9, valid: true }];
const tick = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };

function prepare() {
  const app = setup();
  const source = {
    id: 's', name: 'sheet.png', width: 100, height: 100, blob: {},
    transparent: false, inkLight: false, inkBox: { x: 0.1, y: 0.1, w: 0.5, h: 0.5 },
  };
  const item = {
    id: 'i', sourceId: 's', index: 1,
    box: { x: 0.1, y: 0.1, w: 0.5, h: 0.5 },
    crop: { x: 0.1, y: 0.1, w: 0.5, h: 0.5 },
    margin: 2, readings: [], phase: 'queued', errorKey: null,
    thumb: null, thumbUrl: '', seq: 0, final: '', status: 'pending', note: '',
  };
  app.state.sources.set('s', source);
  app.state.items = [item];
  app.state.selectedId = 'i';
  app.state.pending = [];
  app.state.modelLoaded = true;
  app.state.loading = false;
  return { app, item };
}

test('a crop change clears a completed reading immediately', () => {
  const { app, item } = prepare();
  item.readings = reading('old');
  item.phase = 'done';
  app.setCrop({ x: 0.2, y: 0.1, w: 0.5, h: 0.5 });
  assert.equal(item.readings.length, 0);
  assert.equal(item.phase, 'queued');
  assert.ok(item.seq > 0);
});

test('a drag keeps the read timer from firing until release', () => {
  const { app, item } = prepare();
  const before = app.state.readTimer;
  app.state.drag = { pointerId: 1 };
  app.setCrop({ x: 0.2, y: 0.1, w: 0.5, h: 0.5 });
  assert.equal(app.state.readTimer, before);
  app.state.drag = null;
  app.setCrop({ x: 0.3, y: 0.1, w: 0.5, h: 0.5 });
  assert.notEqual(app.state.readTimer, before);
});
