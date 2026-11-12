// Browser check. Install Playwright outside the checkout and point NODE_PATH at it:
//   PW_DIR="$(mktemp -d /tmp/han2ids-browser-test.XXXXXX)"
//   bun add --cwd "$PW_DIR" playwright-core@1.59.1
//   bun "$PW_DIR/node_modules/playwright-core/cli.js" install chromium
//   NODE_PATH="$PW_DIR/node_modules" node --test demo/tests/crop-accessibility.test.mjs
// The browser check is skipped when Playwright is not available.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { LOCALES } from '../static/i18n.js';

const require = createRequire(import.meta.url);
const root = path.resolve(fileURLToPath(new URL('../static/', import.meta.url))) + path.sep;
const origin = 'http://crop.test';
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };
const inferenceStub = "export async function recognize() { return [{ ids: '一', score: 0.9 }]; }";

function loadChromium() {
  for (const name of ['playwright-core', 'playwright']) {
    try {
      return require(name).chromium;
    } catch {}
  }
  return null;
}

test('crop control exposes its position to screen readers', async t => {
  const chromium = loadChromium();
  if (!chromium) return t.skip('Playwright is not installed');

  const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_PATH && { executablePath: process.env.CHROMIUM_PATH }) });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.route(`${origin}/**`, async route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/inference.js') {
        return route.fulfill({ contentType: 'text/javascript', body: inferenceStub });
      }
      const asset = url.pathname === '/' ? '/index.html' : decodeURIComponent(url.pathname);
      const file = path.resolve(root, '.' + asset);
      if (!file.startsWith(root)) return route.abort();
      try {
        return route.fulfill({ contentType: types[path.extname(file)] || 'application/octet-stream', body: await readFile(file) });
      } catch (error) {
        if (error.code === 'ENOENT') return route.fulfill({ status: 404, body: 'Not found' });
        throw error;
      }
    });

    const page = await context.newPage();
    page.setDefaultTimeout(5000);
    await page.goto(`${origin}/?lang=en`);
    await page.locator('#try-sample').click();
    await page.locator('#crop-box').waitFor({ state: 'visible' });
    const crop = page.getByRole('application', { name: 'Cut region' });
    const description = page.locator('#crop-state');
    const live = page.locator('#crop-live');
    assert.equal(await crop.getAttribute('aria-describedby'), 'crop-hint crop-state');
    assert.match(await description.textContent(), /^Left [\d.]+%, top [\d.]+%, width [\d.]+%, height [\d.]+% of the image\.$/);
    assert.equal(await live.getAttribute('aria-live'), 'polite');
    assert.equal(await live.textContent(), '');

    await page.locator('#full-image').click();
    await page.waitForTimeout(300);
    assert.equal(await description.textContent(), 'Left 0%, top 0%, width 100%, height 100% of the image.');
    assert.equal(await live.textContent(), await description.textContent());
    await crop.focus();
    const cdp = await page.context().newCDPSession(page);
    const { root: documentNode } = await cdp.send('DOM.getDocument');
    const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: documentNode.nodeId, selector: '#crop-box' });
    const { nodes } = await cdp.send('Accessibility.getPartialAXTree', { nodeId });
    assert.equal(nodes[0].role.value, 'application');
    assert.match(nodes[0].description.value, /Arrow keys move it.*Left 0%, top 0%, width 100%, height 100%/);
    await page.waitForTimeout(300);
    assert.equal(await live.textContent(), await description.textContent()); // focus announces the crop
    await page.keyboard.press('Shift+ArrowLeft');
    assert.equal(await description.textContent(), 'Left 0%, top 0%, width 98%, height 100% of the image.');
    assert.equal(await live.textContent(), '');
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowRight');
    assert.equal(await description.textContent(), 'Left 1%, top 0%, width 98%, height 100% of the image.');
    assert.equal(await live.textContent(), '');
    await page.waitForTimeout(300);
    assert.equal(await live.textContent(), await description.textContent());
    await page.keyboard.press('ArrowRight');
    assert.match(await description.textContent(), /^Left 1\.5%,/);
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowRight');
    assert.match(await description.textContent(), /^Left 2%,/); // clamped at the right edge

    await page.locator('#full-image').click();
    await page.waitForTimeout(300);
    assert.equal(await live.textContent(), 'Left 0%, top 0%, width 100%, height 100% of the image.');
    await page.locator('#auto-cut').click();
    await page.waitForTimeout(300);
    assert.equal(await live.textContent(), await description.textContent());
    const beforeDrag = await description.textContent();
    const handleLocator = page.locator('[data-handle="se"]');
    await handleLocator.scrollIntoViewIfNeeded();
    const handle = await handleLocator.boundingBox();
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
    await page.mouse.down();
    await page.mouse.move(handle.x + handle.width / 2 - 20, handle.y + handle.height / 2 - 20);
    await page.mouse.up();
    assert.notEqual(await description.textContent(), beforeDrag);
    await page.waitForTimeout(300);
    assert.equal(await live.textContent(), await description.textContent());

    await crop.focus();
    await page.keyboard.press('Shift+ArrowLeft');
    await page.locator('#language-button').click();
    await page.getByRole('option', { name: /日本語/ }).click();
    await page.waitForTimeout(300);
    assert.match(await description.textContent(), /^画像に対して左から/);
    assert.equal(await live.textContent(), ''); // language changes cancel pending speech
    await page.getByRole('application', { name: '切り取り範囲' }).focus();
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(300);
    assert.equal(await live.textContent(), await description.textContent());
    assert.match(await live.textContent(), /幅.*高さ/);
    for (const [code, entry] of Object.entries(LOCALES)) {
      await page.locator('#language-button').click();
      await page.locator(`[data-value="${code}"]`).click();
      assert.equal(await page.locator('#crop-box').getAttribute('aria-label'), entry.messages['crop.region']);
      assert.equal(await page.locator('#crop-hint').textContent(), entry.messages['crop.hint']);
      assert.doesNotMatch(await description.textContent(), /\{[xywh]\}/);
      assert.notEqual(await description.textContent(), '');
    }
    console.log('Crop accessibility browser checks passed');
  } finally {
    await browser.close();
  }
});
