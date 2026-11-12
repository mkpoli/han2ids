let worker = null;
let sequence = 0;
const pending = new Map();

function start() {
  if (worker) return worker;
  worker = new Worker(new URL('./inference-worker.js', import.meta.url), { type: 'module' });
  worker.onmessage = event => {
    const message = event.data || {};
    const item = pending.get(message.requestId);
    if (!item) return;
    if (message.type === 'progress') {
      item.onProgress?.(message.fraction);
      return;
    }
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
  const requestId = ++sequence;
  return new Promise((resolve, reject) => {
    pending.set(requestId, { resolve, reject, onProgress });
    active.postMessage({ type: 'recognize', requestId, input: input.buffer }, [input.buffer]);
  });
}
