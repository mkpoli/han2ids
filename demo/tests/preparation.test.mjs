#!/usr/bin/env node
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createPreparation } from '../static/preparation.js';

function setup() {
  class Element {
    constructor() {
      this.listeners = {}; this.dataset = {}; this.value = '128'; this.checked = false; this.hidden = false;
      this.attributes = {}; this.style = { setProperty() {} };
      this.classList = { add() {}, remove() {}, toggle() {} };
    }
    addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
    dispatch(type, event = {}) {
      event.target ??= this; event.preventDefault ??= () => {};
      for (const fn of this.listeners[type] ?? []) fn(event);
    }
    setAttribute(name, value) { this.attributes[name] = value; }
  }
  const names = ['imageWrap', 'frame', 'turnSurface', 'compare', 'prepReset', 'turnLeft', 'turnRight', 'straighten', 'prepBw', 'inkField', 'ink', 'inkAuto', 'specksRow', 'prepSpecks'];
  const els = Object.fromEntries(names.map(name => [name, new Element()]));
  const frames = [];
  Object.assign(globalThis, {
    document: { querySelectorAll: () => [] },
    setTimeout: () => 0, clearTimeout() {},
    requestAnimationFrame(fn) { frames.push(fn); return frames.length; }, cancelAnimationFrame() {},
  });
  const source = { id: 's', width: 200, height: 100, prep: { turn: 0, enlarge: 1, bw: false, ink: null, specks: false } };
  const items = [
    { id: 'a', sourceId: 's', crop: { x: 0.7, y: 0.4, w: 0.2, h: 0.2 } },
    { id: 'b', sourceId: 's', crop: { x: 0.1, y: 0.4, w: 0.2, h: 0.2 } },
  ];
  const calls = { restart: [], recut: [], render: 0 };
  const preparation = createPreparation({
    t: key => key, selectedItem: () => items[0], getSource: () => source, itemsOf: () => items,
    frameFor: async () => null, peekFrame: () => null, announce() {},
    restart: (list, options) => calls.restart.push({ list, options }),
    renderStage: () => { calls.render += 1; },
    recut: (target, options) => calls.recut.push({ target, options }),
  }, els);
  return { preparation, els, source, items, calls, frames };
}

test('black and white restarts every item of the image', () => {
  const app = setup();
  app.els.prepBw.checked = true;
  app.els.prepBw.dispatch('change');
  assert.equal(app.source.prep.bw, true);
  assert.equal(app.calls.restart.length, 1);
  assert.deepEqual(app.calls.restart[0].list.map(item => item.id), ['a', 'b']);
  assert.equal(app.calls.recut.length, 0);
});

test('the ink slider drops readings at once and applies the level on the next frame', () => {
  const app = setup();
  app.els.ink.value = '90';
  app.els.ink.dispatch('input');
  assert.deepEqual(app.calls.restart[0].options, { read: false });
  assert.equal(app.source.prep.ink, null);
  app.frames.shift()();
  assert.equal(app.source.prep.ink, 90);
  assert.equal(app.calls.restart.length, 2);
});

test('a quarter turn finds the glyphs again around the selected cut', () => {
  const app = setup();
  app.els.turnRight.dispatch('click');
  assert.equal(app.source.prep.turn, 90);
  assert.deepEqual(app.calls.restart[0].options, { read: false });
  const [{ options }] = app.calls.recut;
  assert.equal(options.afterTurn, true);
  // The selected cut's centre (0.8, 0.5) on a 200 × 100 image sits at (0.5, 0.8) once turned.
  assert.ok(Math.abs(options.focus.x - 0.5) < 1e-9 && Math.abs(options.focus.y - 0.8) < 1e-9);
});

test('reset is offered only once something is prepared', () => {
  const app = setup();
  app.preparation.render(app.source);
  assert.equal(app.els.prepReset.hidden, true);
  app.source.prep = { ...app.source.prep, enlarge: 2 };
  app.preparation.render(app.source);
  assert.equal(app.els.prepReset.hidden, false);
});
