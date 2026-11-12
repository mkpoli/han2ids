#!/usr/bin/env node
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createDisplay } from '../static/display.js';

const ELEMENT_NAMES = ['modelLoad', 'modelProgress', 'modelProgressText', 'resultEmpty', 'resultBody',
  'resultError', 'readingStatus', 'candidates', 'idsText', 'modelView', 'unifiedRow', 'unifiedText', 'copyUnified', 'resultCard', 'errorTitle', 'errorDetail',
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

function setup({ clipboard } = {}) {
  const elements = Object.fromEntries(ELEMENT_NAMES.map(name => [name, new Element(name)]));
  const button = elements.copyIds;
  let handler;
  button.addEventListener = (type, fn) => { if (type === 'click') handler = fn; };
  let fallbackElements = 0;
  let legacyCalls = 0;
  let activeElement = button;
  const document = {
    get activeElement() { return activeElement; },
    set activeElement(value) { activeElement = value; },
    body: { append() { fallbackElements++; } },
    execCommand() { legacyCalls++; return true; },
    createElement(tagName) {
      if (tagName === 'textarea') fallbackElements++;
      return new Element(tagName);
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
    get fallbackElements() { return fallbackElements; },
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
  assert.equal(app.fallbackElements, 0);
  assert.equal(app.elements.liveStatus.textContent, 'live.copied');
  assert.equal(app.button.textContent, 'reading.copied');
});

test('rejected clipboard shows and announces failure without changing focus', async t => {
  let calls = 0;
  const app = setup({ clipboard: { writeText: async () => {
    if (++calls > 1) throw new Error('denied');
  } } });
  t.after(() => app.restore());
  await app.click();
  await app.click();
  assert.equal(app.legacyCalls, 0);
  assert.equal(app.fallbackElements, 0);
  assert.equal(app.activeElement, app.button);
  assert.equal(app.elements.liveStatus.textContent, 'reading.copyFailed');
  assert.equal(app.button.textContent, 'reading.copyFailed');
  [...app.timers.values()][0]();
  assert.equal(app.button.textContent, 'reading.copy');
  assert.equal(app.elements.liveStatus.textContent, '');
});

test('missing clipboard shows and announces failure', async t => {
  const app = setup();
  t.after(() => app.restore());
  await app.click();
  assert.equal(app.legacyCalls, 0);
  assert.equal(app.fallbackElements, 0);
  assert.equal(app.activeElement, app.button);
  assert.equal(app.button.textContent, 'reading.copyFailed');
  assert.equal(app.elements.liveStatus.textContent, 'reading.copyFailed');
});

test('a new failure replaces the prior success and its timer', async t => {
  let calls = 0;
  const app = setup({ clipboard: { writeText: async () => {
    if (++calls > 1) throw new Error('denied');
  } } });
  t.after(() => app.restore());
  await app.click();
  await app.click();
  assert.equal(app.timers.size, 1);
  assert.equal(app.button.textContent, 'reading.copyFailed');
  assert.equal(app.elements.liveStatus.textContent, 'reading.copyFailed');
});

test('a failed copy can be retried successfully', async t => {
  let calls = 0;
  const app = setup({ clipboard: { writeText: async () => {
    if (++calls === 1) throw new Error('denied');
  } } });
  t.after(() => app.restore());
  await app.click();
  assert.equal(app.button.textContent, 'reading.copyFailed');
  await app.click();
  assert.equal(calls, 2);
  assert.equal(app.timers.size, 1);
  assert.equal(app.button.textContent, 'reading.copied');
  assert.equal(app.elements.liveStatus.textContent, 'live.copied');
});

test('copy timeout preserves a newer unrelated announcement', async t => {
  const app = setup({ clipboard: reject });
  t.after(() => app.restore());
  await app.click();
  app.elements.liveStatus.textContent = 'reading completed';
  [...app.timers.values()][0]();
  assert.equal(app.elements.liveStatus.textContent, 'reading completed');
});

test('successful feedback clears after timeout', async t => {
  const app = setup({ clipboard: { writeText: async () => {} } });
  t.after(() => app.restore());
  await app.click();
  [...app.timers.values()][0]();
  assert.equal(app.elements.liveStatus.textContent, '');
});

test('repeated successes change the live message after timeout', async t => {
  const app = setup({ clipboard: { writeText: async () => {} } });
  t.after(() => app.restore());
  await app.click();
  [...app.timers.values()][0]();
  await app.click();
  assert.equal(app.elements.liveStatus.textContent, 'live.copied\u00a0');
});

test('repeated failures change the live message for announcement', async t => {
  const app = setup({ clipboard: reject });
  t.after(() => app.restore());
  await app.click();
  assert.equal(app.elements.liveStatus.textContent, 'reading.copyFailed');
  [...app.timers.values()][0]();
  assert.equal(app.elements.liveStatus.textContent, '');
  await app.click();
  assert.equal(app.elements.liveStatus.textContent, 'reading.copyFailed\u00a0');
  await app.click();
  assert.equal(app.elements.liveStatus.textContent, 'reading.copyFailed');
});
