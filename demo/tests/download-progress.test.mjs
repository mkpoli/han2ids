#!/usr/bin/env node
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { test } from 'node:test';

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
  globalThis.__ORT__ = {
    env: { wasm: {} },
    InferenceSession: { create: () => sessions.shift().promise },
  };
  globalThis.self = {};
  globalThis.fetch = target => {
    const path = target.pathname;
    if (path.endsWith('/itos.json')) return Promise.resolve({ ok: true, json: async () => [] });
    return requests[path.includes('encoder') ? 'encoder' : 'decoder'].promise;
  };
  const { initialize } = await import(`../static/inference-worker.js?test=${++moduleId}`);
  const sessionResults = [...sessions];
  const result = initialize(value => progress.push(value));
  await tick();
  return { requests, sessionResults, progress, result };
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
