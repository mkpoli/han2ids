#!/usr/bin/env node
// Install outside the checkout and run from the repository root:
// PW_DIR="$(mktemp -d /tmp/han2ids-browser-test.XXXXXX)"
// bun add --cwd "$PW_DIR" playwright-core@1.59.1
// bun "$PW_DIR/node_modules/playwright-core/cli.js" install chromium
// NODE_PATH="$PW_DIR/node_modules" node demo/check-modules.mjs
// Optional: CHROMIUM_PATH=/path/to/chrome OCR_SCREENSHOTS_DIR=/tmp OCR_STATIC_ROOT=/path/to/static
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright-core');
const root = path.resolve(process.env.OCR_STATIC_ROOT || fileURLToPath(new URL('./static/', import.meta.url))) + path.sep;
const origin = 'https://ocr.test';
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };
const stub = `
export async function recognize(input, { onProgress } = {}) {
  onProgress?.(0.4);
  const response = await fetch('/__test__/recognize', { method: 'POST' });
  if (!response.ok) throw new Error('deterministic inference failure');
  return response.json();
}`;
const pending = [];
let inferenceRequests = 0;
let inferenceModules = 0;
const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_PATH && { executablePath: process.env.CHROMIUM_PATH }) });
let context;
try {
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2, colorScheme: 'light', permissions: ['clipboard-read', 'clipboard-write'] });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === '/__test__/recognize') {
      inferenceRequests++;
      pending.push(route);
      return;
    }
    const assetPath = url.pathname.startsWith('/ocr/') ? url.pathname.slice(4) : url.pathname;
    if (assetPath === '/inference.js') {
      inferenceModules++;
      return route.fulfill({ contentType: 'text/javascript', body: stub });
    }
    const file = path.resolve(root, '.' + (assetPath === '/' ? '/index.html' : assetPath));
    if (!file.startsWith(root)) return route.abort();
    try { return await route.fulfill({ body: await readFile(file), contentType: types[path.extname(file)] || 'application/octet-stream' }); }
    catch (error) {
      if (error.code === 'ENOENT') return route.fulfill({ status: 404, body: 'Not found' });
      throw error;
    }
  });
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  const shot = async name => {
    if (process.env.OCR_SCREENSHOTS_DIR) await page.screenshot({ path: path.join(process.env.OCR_SCREENSHOTS_DIR, `ocr-baseline-${name}.png`), fullPage: true, animations: 'disabled' });
  };
  const waitCall = async () => {
    const deadline = Date.now() + 5000;
    while (!pending.length && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 20));
    assert.ok(pending.length, 'expected an inference request');
    return pending.shift();
  };
  const answer = (route, ids) => route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ ids, score: 0.9, valid: true }]) });
  const visible = async text => page.getByText(text, { exact: true }).first().waitFor({ state: 'visible' });
  const selectLanguage = async name => {
    await page.locator('#language-button').click();
    await page.getByRole('option', { name, exact: true }).click();
  };
  await page.goto(`${origin}/?lang=en`);
  await visible('No reading yet.');
  assert.equal(inferenceModules, 0, 'inference stays unloaded at startup');
  await page.getByLabel('Light', { exact: true }).check();
  assert.equal(await page.getByLabel('Light', { exact: true }).isChecked(), true);
  await shot('initial-light');
  const lightBackground = await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor);
  await page.getByLabel('Dark', { exact: true }).check();
  assert.equal(await page.getByLabel('Dark', { exact: true }).isChecked(), true);
  await shot('initial-dark');
  assert.notEqual(await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor), lightBackground, 'theme changes the rendered background');
  await selectLanguage('日本語');
  assert.equal(new URL(page.url()).searchParams.get('lang'), 'ja');
  assert.equal(await page.locator('html').getAttribute('lang'), 'ja');
  assert.notEqual(await page.getByRole('heading', { level: 1 }).innerText(), "Read a glyph's IDS");
  await page.reload();
  assert.equal(await page.getByLabel('ダーク', { exact: true }).isChecked(), true);
  assert.equal(await page.locator('html').getAttribute('lang'), 'ja');
  await selectLanguage('English');
  assert.equal(new URL(page.url()).searchParams.get('lang'), 'en');
  await visible('No reading yet.');
  console.log('PASS theme and language selection, URL and reload');

  await page.getByRole('button', { name: 'Try 疑' }).click();
  const initial = await waitCall();
  await visible('256 × 256');
  await answer(initial, '⿰亻木');
  await visible('⿰亻木');
  assert.equal(new URL(await page.getByRole('link', { name: 'Open in IDS Workshop' }).getAttribute('href')).searchParams.get('ids'), '⿰亻木');
  await shot('sample-dark');
  await page.getByLabel('Light', { exact: true }).check();
  await shot('sample-light');
  await page.getByRole('button', { name: 'Copy IDS' }).click();
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), '⿰亻木');
  console.log('PASS sample load, reading, workshop link and clipboard');

  await page.getByRole('button', { name: 'Recognise', exact: true }).click();
  const stale = await waitCall();
  const crop = page.getByRole('group', { name: 'Cut region' });
  const before = await crop.boundingBox();
  await crop.focus();
  await page.keyboard.press('ArrowRight');
  const after = await crop.boundingBox();
  assert.ok(Math.abs(after.x - before.x) > 0.1, 'arrow key should move the crop');
  assert.equal(await page.getByRole('button', { name: 'Copy IDS' }).isVisible(), false, 'crop edit clears the old reading');
  await answer(stale, '⿱日月');
  const fresh = await waitCall();
  assert.equal(await page.getByText('⿱日月', { exact: true }).count(), 0, 'stale reading must not appear');
  await answer(fresh, '⿱山川');
  await visible('⿱山川');
  console.log('PASS keyboard crop edit, delayed stale result and fresh reading');

  const dragStart = await crop.boundingBox();
  const x = dragStart.x + dragStart.width / 2;
  const y = dragStart.y + dragStart.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 8, y + 4, { steps: 3 });
  await page.mouse.up();
  await answer(await waitCall(), '⿰木木');
  await visible('⿰木木');
  console.log('PASS pointer crop and reread');

  await page.getByRole('button', { name: 'Recognise', exact: true }).click();
  const failure = await waitCall();
  await failure.fulfill({ status: 500, body: 'failed' });
  await visible('The glyph could not be read.');
  await visible('Try a different cut, or read again.');
  console.log('PASS inference error is shown');
  await page.locator('#file-input').setInputFiles(path.join(root, 'samples/sample-yi.png'));
  const uploaded = await waitCall();
  await answer(uploaded, '⿰日月');
  await visible('⿰日月');
  assert.equal(await page.locator('#item-list [role="option"]').count(), 2);
  console.log('PASS uploaded image appends another queue item');

  await page.reload();
  await page.getByRole('button', { name: 'Try a sheet' }).click();
  const rows = page.locator('#item-list [role="option"]');
  const firstSheet = await waitCall();
  assert.equal(await rows.count(), 4, 'sheet creates four queue items');
  assert.equal(await rows.nth(0).getAttribute('aria-selected'), 'true');
  assert.equal(await rows.nth(1).locator('.item-state').getAttribute('data-state'), 'queued');
  await answer(firstSheet, '⿰日月');
  const secondSheet = await waitCall();
  await rows.nth(0).focus();
  await page.keyboard.press('ArrowDown');
  assert.equal(await rows.nth(1).getAttribute('aria-selected'), 'true');
  assert.equal(await page.locator('#queue-position').innerText(), '2 / 4');
  await answer(secondSheet, '⿱日又');
  const thirdSheet = await waitCall();
  await answer(thirdSheet, '川');
  const fourthSheet = await waitCall();
  await answer(fourthSheet, '二');
  await page.waitForFunction(() => [...document.querySelectorAll('#item-list .item-state')].every(mark => mark.dataset.state === 'done'));
  for (let i = 0; i < 4; i++) assert.ok(await rows.nth(i).locator('.item-thumb').getAttribute('src'), `thumbnail ${i + 1}`);
  assert.match(await rows.nth(0).innerText(), /⿰日月/);
  assert.match(await rows.nth(1).innerText(), /⿱日又/);
  await page.keyboard.press('End');
  assert.equal(await rows.nth(3).getAttribute('aria-selected'), 'true');
  await page.keyboard.press('Home');
  assert.equal(await rows.nth(0).getAttribute('aria-selected'), 'true');
  await page.locator('#item-next').click();
  assert.equal(await rows.nth(1).getAttribute('aria-selected'), 'true');
  await page.locator('#item-prev').click();
  assert.equal(await rows.nth(0).getAttribute('aria-selected'), 'true');
  await page.locator('#quick-cut').click();
  for (const ids of ['⿰日月', '⿱日又', '川', '二']) await answer(await waitCall(), ids);
  await page.waitForFunction(() => [...document.querySelectorAll('#item-list .item-state')].every(mark => mark.dataset.state === 'done'));
  assert.equal(await rows.count(), 4, 'quick cut replaces the sheet items');
  assert.equal(await rows.nth(0).getAttribute('aria-selected'), 'true');
  console.log('PASS sheet queue, per-item reads and thumbnails, keyboard navigation and quick cut');

  await page.goto(`${origin}/ocr/?lang=en`);
  await visible('No reading yet.');
  await page.getByRole('button', { name: 'Try 疑' }).click();
  await answer(await waitCall(), '⿰亻木');
  await visible('⿰亻木');
  assert.deepEqual(pageErrors, [], 'page errors');
  console.log(`PASS /ocr/ module and sample paths; inference requests: ${inferenceRequests}`);
} finally {
  for (const route of pending) await route.abort().catch(() => {});
  try { await context?.close(); } finally { await browser.close(); }
}
