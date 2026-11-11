import * as ort from './ort/ort.wasm.min.mjs';
import { ARITY, advance, validIds } from './ids.js';

const MAX_LEN = 48;
const BOS = 1;
const EOS = 2;
const PAD = 0;
const BEAMS = 5;

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
  try {
    const response = await fetch(url('./models/itos.json'));
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    itos = await response.json();
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

/** Log-softmax of one decoder position, in place of a full softmax over every step. */
function stepLogprobs(logits, width, step) {
  const offset = step * width;
  let maximum = -Infinity;
  for (let index = 0; index < width; index += 1) {
    const value = logits[offset + index];
    if (value > maximum) maximum = value;
  }
  let sum = 0;
  for (let index = 0; index < width; index += 1) sum += Math.exp(logits[offset + index] - maximum);
  const logsum = maximum + Math.log(sum);
  const out = new Float32Array(width);
  for (let index = 0; index < width; index += 1) out[index] = logits[offset + index] - logsum;
  return out;
}

/** The k best tokens the operand stack allows here: an operator first, EOS only once every slot is filled. */
function allowed(model, logprobs, stack, step, k) {
  const width = model.itos.length;
  const best = [];
  const offer = (index, logprob) => {
    if (best.length < k) {
      best.push({ index, logprob });
      best.sort((first, second) => second.logprob - first.logprob);
    } else if (logprob > best[best.length - 1].logprob) {
      best[best.length - 1] = { index, logprob };
      best.sort((first, second) => second.logprob - first.logprob);
    }
  };

  if (!stack.length) {
    offer(EOS, logprobs[EOS]);
    return best;
  }
  for (let index = 4; index < width; index += 1) {
    if (step === 0 && !model.opIds.has(index)) continue;
    offer(index, logprobs[index]);
  }
  return best;
}

function beamText(model, tokens) {
  let text = '';
  for (let at = 1; at < tokens.length; at += 1) {
    const token = tokens[at];
    if (token !== EOS && token !== PAD) text += model.itos[token];
  }
  return text;
}

/** Beam search over the same grammar as the CLI, newest first; score is the geometric mean. */
async function run(model, input, width) {
  const images = new ort.Tensor('float32', input, [1, 3, 224, 224]);
  const encoded = await model.encoder.run({ images });
  const vocabulary = model.itos.length;
  let beams = [{ tokens: [BOS], stack: [1], score: 0, finished: false }];

  for (let step = 0; step < MAX_LEN; step += 1) {
    if (beams.every(beam => beam.finished)) break;
    const pool = [];
    for (const beam of beams) {
      if (beam.finished) {
        pool.push(beam);
        continue;
      }
      const tokens = new BigInt64Array(MAX_LEN);
      for (let at = 0; at < beam.tokens.length; at += 1) tokens[at] = BigInt(beam.tokens[at]);
      const output = await model.decoder.run({
        memory: encoded.memory,
        tokens: new ort.Tensor('int64', tokens, [1, MAX_LEN]),
      });
      const logprobs = stepLogprobs(output.logits.data, vocabulary, beam.tokens.length - 1);
      for (const { index, logprob } of allowed(model, logprobs, beam.stack, step, width)) {
        if (!Number.isFinite(logprob)) continue;
        const stack = beam.stack.slice();
        let finished = false;
        if (index === EOS) {
          finished = true;
          stack.length = 0;
        } else {
          advance(stack, model.itos[index]);
        }
        pool.push({ tokens: [...beam.tokens, index], stack, score: beam.score + logprob, finished });
      }
    }
    if (!pool.length) throw new InferenceError('The decoder produced no allowed token.');
    pool.sort((first, second) => second.score - first.score);
    beams = pool.slice(0, width);
  }

  const readings = [];
  const seen = new Set();
  for (const beam of beams) {
    const text = beamText(model, beam.tokens);
    if (!text || seen.has(text)) continue;
    seen.add(text);
    readings.push({
      ids: text,
      score: Math.exp(beam.score / Math.max(1, beam.tokens.length - 1)),
      variant: 'em',
      valid: validIds(text),
    });
  }
  readings.sort((first, second) => second.score - first.score);
  return readings;
}

async function recognize(input, { onProgress, width = BEAMS } = {}) {
  let loaded;
  try {
    loaded = await model(onProgress);
  } catch (error) {
    throw error instanceof ModelLoadError ? error : new ModelLoadError('The model could not be loaded.', { cause: error });
  }
  try {
    return await run(loaded, input, Math.max(1, Math.min(8, width)));
  } catch (error) {
    throw error instanceof InferenceError ? error : new InferenceError('The glyph could not be read.', { cause: error });
  }
}

self.onmessage = async event => {
  const { type, requestId, input, width } = event.data || {};
  if (type !== 'recognize') return;
  try {
    const readings = await recognize(new Float32Array(input), {
      width,
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
