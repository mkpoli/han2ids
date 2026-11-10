let worker = null;
let sequence = 0;
let progress = null;
const pending = new Map();

function start() {
  if (worker) return worker;
  worker = new Worker(new URL('./inference-worker.js', import.meta.url), { type: 'module' });
  worker.onmessage = event => {
    const message = event.data || {};
    if (message.type === 'progress') {
      progress?.(message.fraction);
      return;
    }
    const item = pending.get(message.requestId);
    if (!item) return;
    pending.delete(message.requestId);
    if (message.type === 'result') item.resolve(message.readings);
    else if (message.type === 'error') item.reject(Object.assign(new Error(message.message), { name: message.name }));
  };
  worker.onerror = event => {
    for (const item of pending.values()) {
      item.reject(Object.assign(new Error('The browser model worker failed.'), { name: 'ModelLoadError' }));
    }
    pending.clear();
    worker?.terminate();
    worker = null;
    event.preventDefault?.();
  };
  return worker;
}

export function recognize(input, { onProgress } = {}) {
  const active = start();
  progress = onProgress || null;
  const requestId = ++sequence;
  return new Promise((resolve, reject) => {
    pending.set(requestId, { resolve, reject });
    active.postMessage({ type: 'recognize', requestId, input: input.buffer }, [input.buffer]);
  });
}
