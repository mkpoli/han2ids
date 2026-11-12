import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('./ocr-worker.js', import.meta.url), 'utf8');
const { default: worker } = await import(`data:text/javascript,${encodeURIComponent(source)}`);

function assets(status, headers = {}) {
  const calls = [];
  return {
    calls,
    env: { ASSETS: { fetch(request) {
      calls.push(request);
      return new Response(status === 304 ? null : 'asset', { status, headers });
    } } },
  };
}

for (const path of ['/models/encoder-int8.onnx', '/models/itos.json', '/ort/ort.wasm.min.mjs', '/ort/ort-wasm-simd-threaded.wasm', '/fonts/han2ids-glyphs.woff2', '/app.js', '/']) {
  test(`revalidates unversioned ${path}`, async () => {
    const mock = assets(200, { etag: '"v1"', 'content-type': 'application/octet-stream' });
    const response = await worker.fetch(new Request(`https://example.com/ocr${path}?lang=en`), mock.env);
    assert.equal(response.headers.get('cache-control'), 'no-cache');
    assert.equal(response.headers.get('etag'), '"v1"');
    assert.equal(response.headers.get('content-type'), 'application/octet-stream');
    assert.equal(await response.text(), 'asset');
    assert.equal(mock.calls[0].url, `https://example.com${path}?lang=en`);
  });
}

for (const status of [206, 304]) {
  test(`preserves ${status} revalidation and range responses`, async () => {
    const mock = assets(status, { etag: '"v1"', 'content-range': 'bytes 0-4/10' });
    const response = await worker.fetch(new Request('https://example.com/ocr/models/a.onnx', {
      method: 'HEAD', headers: { 'if-none-match': '"v1"', range: 'bytes=0-4' },
    }), mock.env);
    assert.equal(response.status, status);
    assert.equal(response.headers.get('cache-control'), 'no-cache');
    assert.equal(response.headers.get('etag'), '"v1"');
    assert.equal(mock.calls[0].method, 'HEAD');
    assert.equal(mock.calls[0].headers.get('if-none-match'), '"v1"');
    assert.equal(mock.calls[0].headers.get('range'), 'bytes=0-4');
  });
}

for (const status of [404, 429, 500, 503]) {
  test(`does not cache asset error ${status}`, async () => {
    const mock = assets(status, { 'cache-control': 'public, max-age=86400' });
    const response = await worker.fetch(new Request('https://example.com/ocr/models/a.onnx'), mock.env);
    assert.equal(response.status, status);
    assert.equal(response.headers.get('cache-control'), 'no-store');
  });
}

test('retains a stricter no-store asset policy', async () => {
  const mock = assets(200, { 'cache-control': 'private, no-store' });
  const response = await worker.fetch(new Request('https://example.com/ocr/app.js'), mock.env);
  assert.equal(response.headers.get('cache-control'), 'private, no-store');
});

test('does not cache routing and method errors', async () => {
  for (const [path, method, status] of [['/other', 'GET', 404], ['/ocr/', 'POST', 405]]) {
    const response = await worker.fetch(new Request(`https://example.com${path}`, { method }), {});
    assert.equal(response.status, status);
    assert.equal(response.headers.get('cache-control'), 'no-store');
  }
});

test('redirects the OCR root with its query', async () => {
  const response = await worker.fetch(new Request('https://example.com/ocr?lang=ja'), {});
  assert.equal(response.status, 308);
  assert.equal(response.headers.get('location'), 'https://example.com/ocr/?lang=ja');
});

test('keeps asset redirects under the OCR prefix', async () => {
  for (const location of ['/benchmark', 'https://example.com/benchmark']) {
    const mock = assets(307, { location });
    const response = await worker.fetch(new Request('https://example.com/ocr/benchmark.html?lang=ja'), mock.env);
    assert.equal(response.status, 307);
    assert.equal(response.headers.get('location'), '/ocr/benchmark');
    assert.equal(response.headers.get('cache-control'), 'no-store');
  }
  const elsewhere = assets(302, { location: 'https://other.example/x' });
  const response = await worker.fetch(new Request('https://example.com/ocr/x'), elsewhere.env);
  assert.equal(response.headers.get('location'), 'https://other.example/x');
});
