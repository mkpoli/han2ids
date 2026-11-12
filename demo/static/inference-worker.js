import * as ort from './ort/ort.wasm.min.mjs';
import { unify } from './ids.js';

const MAX_LEN = 48;
const BOS = 1;
const EOS = 2;
const ARITY = {
  '⿰': 2, '⿱': 2, '⿲': 3, '⿳': 3, '⿴': 2, '⿵': 2, '⿶': 2, '⿷': 2,
  '⿸': 2, '⿹': 2, '⿺': 2, '⿻': 2, '⿼': 2, '⿽': 2, '㇯': 2,
  '⿾': 1, '⿿': 1, '〾': 1,
};

class ModelLoadError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = 'ModelLoadError';
  }
}

class InferenceError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = 'InferenceError';
  }
}

let ready = null;

function url(path) {
  return new URL(path, import.meta.url);
}

async function fetchProgress(target, onProgress, start, span) {
  const response = await fetch(target);
  if (!response.ok) throw new ModelLoadError(`HTTP ${response.status}`);
  const total = Number(response.headers.get('content-length')) || 0;
  if (!response.body) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    onProgress?.(start + span);
    return bytes;
  }
  const reader = response.body.getReader();
  const chunks = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    if (total) onProgress?.(start + span * (loaded / total));
  }
  const bytes = new Uint8Array(loaded);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  onProgress?.(start + span);
  return bytes;
}

async function initialize(onProgress) {
  ort.env.wasm.wasmPaths = url('./ort/').href;
  ort.env.wasm.numThreads = 1;
  ort.env.wasm.simd = true;

  let itos;
  let forms;
  try {
    const responses = await Promise.all([fetch(url('./models/itos.json')), fetch(url('./models/forms.json'))]);
    for (const response of responses) if (!response.ok) throw new Error(`HTTP ${response.status}`);
    [itos, forms] = await Promise.all(responses.map(response => response.json()));
  } catch (error) {
    throw new ModelLoadError('The vocabulary could not be loaded.', { cause: error });
  }

  const [encoderBytes, decoderBytes] = await Promise.all([
    fetchProgress(url('./models/encoder-int8.onnx'), onProgress, 0, 0.55).catch(error => {
      throw error instanceof ModelLoadError ? error : new ModelLoadError('The encoder could not be loaded.', { cause: error });
    }),
    fetchProgress(url('./models/decoder-int8.onnx'), onProgress, 0.55, 0.4).catch(error => {
      throw error instanceof ModelLoadError ? error : new ModelLoadError('The decoder could not be loaded.', { cause: error });
    }),
  ]);

  onProgress?.(0.95);
  try {
    const [encoder, decoder] = await Promise.all([
      ort.InferenceSession.create(encoderBytes, { executionProviders: ['wasm'] }),
      ort.InferenceSession.create(decoderBytes, { executionProviders: ['wasm'] }),
    ]);
    onProgress?.(1);
    return {
      encoder,
      decoder,
      itos,
      forms,
      opIds: new Set(itos.map((char, index) => (ARITY[char] ? index : -1)).filter(index => index >= 0)),
    };
  } catch (error) {
    throw new ModelLoadError('The model sessions could not be created.', { cause: error });
  }
}

async function model(onProgress) {
  if (!ready) {
    ready = initialize(onProgress).catch(error => {
      ready = null;
      throw error;
    });
  }
  return ready;
}

function advance(stack, char) {
  while (stack.length && stack[stack.length - 1] === 0) stack.pop();
  if (!stack.length) return;
  stack[stack.length - 1] -= 1;
  if (ARITY[char]) stack.push(ARITY[char]);
  while (stack.length && stack[stack.length - 1] === 0) stack.pop();
}

function decode(model, memory, logits, step) {
  const { itos, opIds } = model;
  const width = itos.length;
  const offset = step * width;
  let maximum = -Infinity;
  for (let index = 0; index < width; index += 1) {
    const value = logits[offset + index];
    if (value > maximum) maximum = value;
  }
  let sum = 0;
  for (let index = 0; index < width; index += 1) sum += Math.exp(logits[offset + index] - maximum);
  const logsum = maximum + Math.log(sum);

  let best = -Infinity;
  let choice = -1;
  if (!model.stack.length) {
    choice = EOS;
    best = logits[offset + EOS] - logsum;
  } else {
    for (let index = 4; index < width; index += 1) {
      if (step === 0 && !opIds.has(index)) continue;
      const value = logits[offset + index] - logsum;
      if (value > best) {
        best = value;
        choice = index;
      }
    }
  }
  if (choice < 0) throw new InferenceError('The decoder produced no allowed token.');
  return { choice, logprob: best };
}

async function run(model, input) {
  const images = new ort.Tensor('float32', input, [1, 3, 224, 224]);
  const encoded = await model.encoder.run({ images });
  const tokens = new BigInt64Array(MAX_LEN);
  tokens[0] = BigInt(BOS);
  model.stack = [1];
  let score = 0;
  let steps = 0;
  let text = '';

  for (let step = 0; step < MAX_LEN; step += 1) {
    const output = await model.decoder.run({
      memory: encoded.memory,
      tokens: new ort.Tensor('int64', tokens, [1, MAX_LEN]),
    });
    const { choice, logprob } = decode(model, encoded.memory, output.logits.data, step);
    score += logprob;
    steps += 1;
    if (choice === EOS) break;
    tokens[step + 1] = BigInt(choice);
    text += model.itos[choice];
    advance(model.stack, model.itos[choice]);
  }

  const readingScore = Math.exp(score / Math.max(1, steps));
  const valid = Boolean(text) && model.stack.length === 0;
  return [{ ids: text, unified: unify(text, model.forms), score: readingScore, variant: 'em', valid }];
}

async function recognize(input, { onProgress } = {}) {
  let loaded;
  try {
    loaded = await model(onProgress);
  } catch (error) {
    throw error instanceof ModelLoadError ? error : new ModelLoadError('The model could not be loaded.', { cause: error });
  }
  try {
    return await run(loaded, input);
  } catch (error) {
    throw error instanceof InferenceError ? error : new InferenceError('The glyph could not be read.', { cause: error });
  }
}

self.onmessage = async event => {
  const { type, requestId, input } = event.data || {};
  if (type !== 'recognize') return;
  try {
    const readings = await recognize(new Float32Array(input), {
      onProgress: fraction => self.postMessage({ type: 'progress', fraction }),
    });
    self.postMessage({ type: 'result', requestId, readings });
  } catch (error) {
    self.postMessage({
      type: 'error',
      requestId,
      name: error?.name || 'InferenceError',
      message: error?.message || 'The glyph could not be read.',
    });
  }
};
