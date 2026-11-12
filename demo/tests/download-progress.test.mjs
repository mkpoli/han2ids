#!/usr/bin/env node
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { registerHooks } from 'node:module';
import { test } from 'node:test';
import { createDisplay } from '../static/display.js';

let stubId = 0;
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === './ort/ort.wasm.min.mjs') {
      return {
        url: `data:text/javascript,export const env = globalThis.__ORT__.env; export const InferenceSession = globalThis.__ORT__.InferenceSession;//${++stubId}`,
        shortCircuit: true,
      };
    }
    return nextResolve(specifier, context);
  },
});

const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

let moduleId = 0;

async function setup() {
  const requests = { encoder: deferred(), decoder: deferred() };
  const sessions = [deferred(), deferred()];
  const progress = [];
  const signals = [];
  globalThis.__ORT__ = {
    env: { wasm: {} },
    InferenceSession: { create: () => sessions.shift().promise },
  };
  globalThis.self = {};
  globalThis.fetch = (target, options) => {
    const path = target.pathname;
    if (path.endsWith('/itos.json')) return Promise.resolve({ ok: true, json: async () => [] });
    if (path.endsWith('/forms.json')) return Promise.resolve({ ok: true, json: async () => ({}) });
    signals.push(options.signal);
    return requests[path.includes('encoder') ? 'encoder' : 'decoder'].promise;
  };
  const { initialize } = await import(`../static/inference-worker.js?test=${++moduleId}`);
  const sessionResults = [...sessions];
  const result = initialize(value => progress.push(value));
  await tick();
  return { requests, sessionResults, progress, result, signals };
}

function streamResponse(length) {
  let controller;
  const body = new ReadableStream({ start(value) { controller = value; } });
  const headers = new Headers();
  if (length !== null) headers.set('content-length', String(length));
  return { response: { ok: true, headers, body }, controller };
}

function last(values) { return values.at(-1); }
function closeTo(actual, expected) { assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} != ${expected}`); }

test('the decoder arriving first does not stand in for the encoder', async () => {
  const { requests, sessionResults, progress, result } = await setup();
  const decoder = streamResponse(10);
  const encoder = streamResponse(90);
  requests.decoder.resolve(decoder.response);
  await tick();
  decoder.controller.enqueue(new Uint8Array(10));
  decoder.controller.close();
  await tick();
  assert.equal(last(progress), null);
  requests.encoder.resolve(encoder.response);
  await tick();
  closeTo(last(progress), 0.095);
  encoder.controller.enqueue(new Uint8Array(45));
  await tick();
  closeTo(last(progress), 0.5225);
  encoder.controller.enqueue(new Uint8Array(45));
  await tick();
  assert.ok(last(progress) < 0.95);
  encoder.controller.close();
  await tick();
  assert.equal(last(progress), 0.95);
  sessionResults[0].resolve({});
  await tick();
  assert.equal(last(progress), 0.95);
  sessionResults[1].resolve({});
  await result;
  assert.equal(last(progress), 1);
});

test('a missing length stays indeterminate until EOF supplies the actual size', async () => {
  const { requests, sessionResults, progress, result } = await setup();
  const encoder = streamResponse(null);
  const decoder = streamResponse(30);
  requests.encoder.resolve(encoder.response);
  requests.decoder.resolve(decoder.response);
  await tick();
  encoder.controller.enqueue(new Uint8Array(10));
  decoder.controller.enqueue(new Uint8Array(15));
  await tick();
  assert.equal(last(progress), null);
  encoder.controller.close();
  await tick();
  closeTo(last(progress), 0.95 * 25 / 40);
  decoder.controller.enqueue(new Uint8Array(15));
  decoder.controller.close();
  await tick();
  assert.equal(last(progress), 0.95);
  sessionResults.forEach(session => session.resolve({}));
  await result;
});

test('encoded responses do not use their encoded lengths', async () => {
  const { requests, sessionResults, progress, result } = await setup();
  const encoder = streamResponse(20);
  encoder.response.headers.set('content-encoding', 'gzip');
  const decoder = streamResponse(30);
  requests.encoder.resolve(encoder.response);
  requests.decoder.resolve(decoder.response);
  await tick();
  encoder.controller.enqueue(new Uint8Array(10));
  decoder.controller.enqueue(new Uint8Array(15));
  await tick();
  assert.equal(last(progress), null);
  encoder.controller.close();
  await tick();
  closeTo(last(progress), 0.95 * 25 / 40);
  decoder.controller.close();
  await tick();
  sessionResults.forEach(session => session.resolve({}));
  await result;
});

test('inaccurate short lengths revert to indeterminate and arrayBuffer responses count at EOF', async () => {
  const { requests, sessionResults, progress, result } = await setup();
  const encoder = streamResponse(2);
  requests.encoder.resolve(encoder.response);
  requests.decoder.resolve({ ok: true, headers: new Headers(), body: null, arrayBuffer: async () => new Uint8Array(4).buffer });
  await tick();
  encoder.controller.enqueue(new Uint8Array(3));
  await tick();
  assert.equal(last(progress), null);
  encoder.controller.close();
  await tick();
  assert.equal(last(progress), 0.95);
  sessionResults.forEach(session => session.resolve({}));
  await result;
});

test('a failed download stops its sibling from reporting after a retry can start', async () => {
  const { requests, progress, result, signals } = await setup();
  const encoder = streamResponse(100);
  requests.encoder.resolve(encoder.response);
  await tick();
  requests.decoder.resolve({ ok: false, status: 503 });
  await assert.rejects(result, /HTTP 503/);
  assert.equal(signals.length, 2);
  assert.ok(signals.every(signal => signal.aborted));
  const count = progress.length;
  encoder.controller.enqueue(new Uint8Array(10));
  await tick();
  assert.equal(progress.length, count, 'obsolete download reported after failure');
  encoder.controller.close();
});

test('shared loads notify each request and stale messages cannot reach a retry', async () => {
  const requests = [];
  const workerSelf = {};
  let clientWorker;
  globalThis.__ORT__ = {
    env: { wasm: {} },
    InferenceSession: { create: async () => ({}) },
  };
  globalThis.fetch = (target, options) => {
    if (target.pathname.endsWith('/itos.json')) return Promise.resolve({ ok: true, json: async () => [] });
    if (target.pathname.endsWith('/forms.json')) return Promise.resolve({ ok: true, json: async () => ({}) });
    const request = deferred();
    requests.push({ ...request, signal: options.signal });
    return request.promise;
  };
  globalThis.self = workerSelf;
  await import(`../static/inference-worker.js?test=${++moduleId}`);

  class FakeWorker {
    constructor() { clientWorker = this; }
    postMessage(data) { queueMicrotask(() => workerSelf.onmessage({ data })); }
  }
  workerSelf.postMessage = data => queueMicrotask(() => clientWorker.onmessage({ data }));
  globalThis.Worker = FakeWorker;
  const { recognize } = await import(`../static/inference.js?test=${++moduleId}`);

  const first = [], second = [], retry = [];
  const firstResult = recognize(new Float32Array(1), { onProgress: value => first.push(value) });
  const secondResult = recognize(new Float32Array(1), { onProgress: value => second.push(value) });
  const failed = Promise.all([assert.rejects(firstResult), assert.rejects(secondResult)]);
  await tick();
  assert.equal(requests.length, 2);
  const oldEncoder = streamResponse(100);
  requests[0].resolve(oldEncoder.response);
  await tick();
  assert.ok(first.length && second.length, 'both shared-load subscribers should receive progress');
  requests[1].resolve({ ok: false, status: 503 });
  await failed;
  assert.ok(requests[0].signal.aborted);

  const retryResult = recognize(new Float32Array(1), { onProgress: value => retry.push(value) });
  const retryFailed = assert.rejects(retryResult, error => error.name === 'InferenceError');
  await tick();
  assert.equal(requests.length, 4);
  const count = retry.length;
  clientWorker.onmessage({ data: { type: 'progress', requestId: 1, fraction: 0.9 } });
  oldEncoder.controller.enqueue(new Uint8Array(10));
  await tick();
  assert.equal(retry.length, count, 'old progress reached the retry');
  oldEncoder.controller.close();

  const nextEncoder = streamResponse(10);
  const nextDecoder = streamResponse(10);
  requests[2].resolve(nextEncoder.response);
  requests[3].resolve(nextDecoder.response);
  await tick();
  nextEncoder.controller.enqueue(new Uint8Array(10));
  nextEncoder.controller.close();
  nextDecoder.controller.enqueue(new Uint8Array(10));
  nextDecoder.controller.close();
  await retryFailed; // Session creation succeeds; inference is deliberately unstubbed.
  assert.equal(last(retry), 1);
});

test('the progress element hides its determinate bar when the aggregate size is unknown', async () => {
  const html = await readFile(new URL('../static/index.html', import.meta.url), 'utf8');
  assert.match(html, /<label\s+for="model-progress"\s+data-i18n="model\.loading"/);
  assert.match(html, /<progress\s+class="model-progress"\s+id="model-progress"\s+max="100"\s+value="0"><\/progress>/);

  const els = {
    copyIds: { addEventListener() {} },
    copyUnified: { addEventListener() {} },
    modelLoad: { hidden: true },
    modelProgress: { hidden: false, value: 0 },
    modelProgressText: { textContent: '' },
  };
  const display = createDisplay({ t: key => key }, els);
  display.showModelProgress(null);
  assert.equal(els.modelLoad.hidden, false);
  assert.equal(els.modelProgress.hidden, true);
  assert.equal(els.modelProgressText.textContent, '—');
  display.showModelProgress(0.949999);
  assert.equal(els.modelProgress.hidden, false);
  assert.equal(els.modelProgressText.textContent, '94%');
  assert.equal(els.modelProgress.value, 94);
  display.showModelProgress(0.95);
  assert.equal(els.modelProgress.value, 95);
  assert.equal(els.modelProgressText.textContent, '95%');
  display.showModelProgress(null);
  assert.equal(els.modelProgress.hidden, true);
  display.showModelProgress(1);
  assert.equal(els.modelProgress.hidden, false);
  assert.equal(els.modelProgress.value, 100);
});
