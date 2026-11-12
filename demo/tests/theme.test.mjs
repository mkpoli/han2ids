#!/usr/bin/env node
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { initTheme } from '../static/theme.js';

function page(initialValue, { blocked = false } = {}) {
  const meta = { content: 'light dark' };
  const values = new Map(initialValue === null ? [] : [['han2ids:theme', initialValue]]);
  const storage = {
    getItem(key) { if (blocked) throw Error('blocked'); return values.get(key) ?? null; },
    setItem(key, value) { if (blocked) throw Error('blocked'); values.set(key, value); },
    removeItem(key) { if (blocked) throw Error('blocked'); values.delete(key); },
  };
  const radios = ['system', 'light', 'dark'].map(value => ({
    value, checked: false, addEventListener(type, handler) { this[type] = handler; },
  }));
  const listeners = {};
  Object.assign(globalThis, {
    localStorage: storage,
    document: {
      querySelector: selector => (selector === 'meta[name="color-scheme"]' ? meta : null),
      querySelectorAll: () => radios,
    },
    window: { addEventListener(type, handler) { listeners[type] = handler; } },
  });
  return {
    meta, values, storage, radios,
    start() { initTheme(); },
    select(value) {
      const radio = radios.find(item => item.value === value);
      radio.checked = true;
      radio.change();
    },
    storageEvent(key, storageArea = storage) { listeners.storage({ key, storageArea }); },
    selected() { return radios.find(radio => radio.checked)?.value; },
  };
}

for (const [stored, expected, selected] of [
  [null, 'light dark', 'system'], ['invalid', 'light dark', 'system'],
  ['light', 'light', 'light'], ['dark', 'dark', 'dark'],
]) {
  test(`stored theme sets the metadata and initial radio: ${stored ?? 'system'}`, () => {
    const p = page(stored);
    p.start();
    assert.equal(p.meta.content, expected);
    assert.equal(p.selected(), selected);
  });
}

test('selection persists explicit themes and removes system override', () => {
  const p = page(null);
  p.start();
  for (const value of ['dark', 'light', 'system']) {
    p.select(value);
    assert.equal(p.meta.content, value === 'system' ? 'light dark' : value);
    assert.equal(p.selected(), value);
    assert.equal(p.values.get('han2ids:theme'), value === 'system' ? undefined : value);
  }
});

test('cross-tab changes, invalid values and clear update meta and radios', () => {
  const p = page('dark');
  p.start();
  p.values.set('han2ids:theme', 'light');
  p.storageEvent('han2ids:theme');
  assert.equal(p.meta.content, 'light');
  assert.equal(p.selected(), 'light');
  p.values.set('han2ids:theme', 'invalid');
  p.storageEvent('han2ids:theme');
  assert.equal(p.meta.content, 'light dark');
  assert.equal(p.selected(), 'system');
  p.values.set('han2ids:theme', 'dark');
  p.storageEvent('other');
  p.storageEvent('han2ids:theme', {});
  assert.equal(p.meta.content, 'light dark');
  p.storageEvent('han2ids:theme');
  assert.equal(p.meta.content, 'dark');
  p.values.clear();
  p.storageEvent(null);
  assert.equal(p.meta.content, 'light dark');
  assert.equal(p.selected(), 'system');
});

test('blocked storage still allows an in-page theme change', () => {
  const p = page(null, { blocked: true });
  p.start(); p.select('dark');
  assert.equal(p.meta.content, 'dark');
  assert.equal(p.selected(), 'dark');
});
