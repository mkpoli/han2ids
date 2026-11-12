#!/usr/bin/env node
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { split, unify, validIds } from '../static/ids.js';

const B = '鄕\u{E0102}';
const C = '鄕\u{E0101}';
const forms = { [B]: '鄉', [C]: '鄉', 鄕: '鄉', 郷: '鄉' };

test('a variation selector stays on its base character', () => {
  assert.deepEqual(split(`⿵門${B}`), ['⿵', '門', B]);
  assert.equal(validIds(`⿵門${B}`), true);
  assert.equal(validIds('⿰\u{FE00}'), false);
});

test('printed forms share one unified reading', () => {
  for (const text of [`⿵門${B}`, `⿵門${C}`, '⿵門鄉']) assert.equal(unify(text, forms), '⿵門鄉');
  assert.equal(unify('⿱郷音', forms), '⿱鄉音');
  assert.equal(unify('⿰亻五', forms), '⿰亻五');
});
