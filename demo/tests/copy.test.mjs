#!/usr/bin/env node
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createDisplay } from '../static/display.js';

const ELEMENT_NAMES = ['modelLoad', 'modelProgress', 'modelProgressText', 'resultEmpty', 'resultBody',
  'resultError', 'readingStatus', 'candidates', 'idsText', 'resultCard', 'errorTitle', 'errorDetail',
  'openWorkshop', 'scoreChip', 'validityChip', 'copyIds', 'sourceChip', 'candidateList',
  'readingStatusText', 'liveStatus'];

class Element {
  constructor(tagName = '') {
    this.tagName = tagName;
    this.listeners = {};
    this.dataset = {};
    this.style = { setProperty() {} };
    this.children = [];
    this.textContent = '';
    this.hidden = false;
  }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute() {}
  focus() {}
}

function setup({ clipboard, legacy = true } = {}) {
  const elements = Object.fromEntries(ELEMENT_NAMES.map(name => [name, new Element(name)]));
  const button = elements.copyIds;
  let handler;
  button.addEventListener = (type, fn) => { if (type === 'click') handler = fn; };
  let area;
  let removed = false;
  let legacyCalls = 0;
  let activeElement = button;
  const document = {
    get activeElement() { return activeElement; },
    set activeElement(value) { activeElement = value; },
    body: { append(element) { area = element; } },
    execCommand(command) {
      assert.equal(command, 'copy');
      legacyCalls++;
      if (legacy instanceof Error) throw legacy;
      return legacy;
    },
    createElement(tagName) {
      const element = new Element(tagName);
      if (tagName === 'textarea') {
        area = element;
        element.value = '';
        element.select = () => { activeElement = element; };
        element.remove = () => { removed = true; activeElement = null; };
      }
      return element;
    },
    createDocumentFragment: () => new Element('#fragment'),
    createTextNode: text => ({ textContent: text }),
  };
  button.focus = () => { activeElement = button; };

  const reading = { ids: '⿰木木', score: 0.9, valid: true };
  const item = { readings: [reading], phase: 'done', sourceId: 's', index: 0 };
  const deps = {
    t: key => key,
    selectedItem: () => item,
    getSource: () => ({ name: 'source' }),
    itemsOf: () => [item],
    isLoading: () => false,
  };

  const timers = new Map();
  let nextTimer = 0;
  const previous = {
    document: Object.getOwnPropertyDescriptor(globalThis, 'document'),
    navigator: Object.getOwnPropertyDescriptor(globalThis, 'navigator'),
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
  };
  Object.defineProperty(globalThis, 'document', { value: document, configurable: true, writable: true });
  Object.defineProperty(globalThis, 'navigator', { value: { clipboard }, configurable: true, writable: true });
  globalThis.setTimeout = fn => { timers.set(++nextTimer, fn); return nextTimer; };
  globalThis.clearTimeout = id => { timers.delete(id); };

  const restore = () => {
    if (previous.document) Object.defineProperty(globalThis, 'document', previous.document);
    else delete globalThis.document;
    if (previous.navigator) Object.defineProperty(globalThis, 'navigator', previous.navigator);
    else delete globalThis.navigator;
    globalThis.setTimeout = previous.setTimeout;
    globalThis.clearTimeout = previous.clearTimeout;
  };

  createDisplay(deps, elements);

  return {
    click: () => handler(), elements, button, document, timers, restore,
    get area() { return area; },
    get removed() { return removed; },
    get legacyCalls() { return legacyCalls; },
    get activeElement() { return activeElement; },
  };
}

const reject = { writeText: async () => { throw new Error('denied'); } };

test('clipboard success announces success without fallback', async t => {
  let copied;
  const app = setup({ clipboard: { writeText: async text => { copied = text; } } });
  t.after(() => app.restore());
  await app.click();
  assert.equal(copied, '⿰木木');
  assert.equal(app.legacyCalls, 0);
  assert.equal(app.elements.liveStatus.textContent, 'live.copied');
  assert.equal(app.button.textContent, 'reading.copied');
});

test('rejected clipboard and failed legacy copy announce failure and restore focus', async t => {
  const app = setup({ clipboard: reject, legacy: false });
  t.after(() => app.restore());
  await app.click();
  assert.equal(app.area.value, '⿰木木');
  assert.equal(app.legacyCalls, 1);
  assert.equal(app.removed, true);
  assert.equal(app.activeElement, app.button);
  assert.equal(app.elements.liveStatus.textContent, 'reading.copyFailed');
  assert.equal(app.button.textContent, 'reading.copyFailed');
  [...app.timers.values()][0]();
  assert.equal(app.button.textContent, 'reading.copy');
});

test('throwing legacy copy announces failure, cleans up, and restores focus', async t => {
  const app = setup({ clipboard: reject, legacy: new Error('unsupported') });
  t.after(() => app.restore());
  await app.click();
  assert.equal(app.removed, true);
  assert.equal(app.activeElement, app.button);
  assert.equal(app.button.textContent, 'reading.copyFailed');
  assert.equal(app.elements.liveStatus.textContent, 'reading.copyFailed');
});

test('successful fallback announces success and restores focus', async t => {
  const app = setup({ clipboard: reject });
  t.after(() => app.restore());
  await app.click();
  assert.equal(app.removed, true);
  assert.equal(app.activeElement, app.button);
  assert.equal(app.button.textContent, 'reading.copied');
  assert.equal(app.elements.liveStatus.textContent, 'live.copied');
});

test('a new failure replaces the prior success and its timer', async t => {
  let calls = 0;
  const app = setup({ clipboard: { writeText: async () => {
    if (++calls > 1) throw new Error('denied');
  } }, legacy: false });
  t.after(() => app.restore());
  await app.click();
  await app.click();
  assert.equal(app.timers.size, 1);
  assert.equal(app.button.textContent, 'reading.copyFailed');
  assert.equal(app.elements.liveStatus.textContent, 'reading.copyFailed');
});

test('repeated failures change the live message for announcement', async t => {
  const app = setup({ clipboard: reject, legacy: false });
  t.after(() => app.restore());
  await app.click();
  assert.equal(app.elements.liveStatus.textContent, 'reading.copyFailed');
  await app.click();
  assert.equal(app.elements.liveStatus.textContent, 'reading.copyFailed\u00a0');
  await app.click();
  assert.equal(app.elements.liveStatus.textContent, 'reading.copyFailed');
});

test('missing clipboard uses fallback', async t => {
  const app = setup();
  t.after(() => app.restore());
  await app.click();
  assert.equal(app.legacyCalls, 1);
  assert.equal(app.elements.liveStatus.textContent, 'live.copied');
  assert.equal(app.button.textContent, 'reading.copied');
});
