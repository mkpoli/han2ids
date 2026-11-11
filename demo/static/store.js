/* The review set, kept in this browser. One implicit local project: images, crops, readings,
   final text, notes and status, with nothing sent anywhere. */

const NAME = 'han2ids-ocr';
const VERSION = 1;
const STORES = ['sources', 'items', 'meta'];

let database = null;

function open() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(NAME, VERSION);
    request.onupgradeneeded = () => {
      const base = request.result;
      for (const name of STORES) {
        if (!base.objectStoreNames.contains(name)) {
          base.createObjectStore(name, { keyPath: name === 'meta' ? 'key' : 'id' });
        }
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error('The database is blocked by another tab.'));
  });
}

async function base() {
  if (!database) database = await open();
  return database;
}

function wrap(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function done(transaction) {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

/** Everything held for the local project, in the order it was last saved in. */
export async function load() {
  const db = await base();
  const transaction = db.transaction(STORES, 'readonly');
  const [sources, items, order] = await Promise.all([
    wrap(transaction.objectStore('sources').getAll()),
    wrap(transaction.objectStore('items').getAll()),
    wrap(transaction.objectStore('meta').get('order')),
  ]);
  await done(transaction);
  return { sources, items, order: order?.ids ?? [] };
}

export async function save({ sources = [], items = [], order = null, dropItems = [], dropSources = [] } = {}) {
  const db = await base();
  const transaction = db.transaction(STORES, 'readwrite');
  for (const source of sources) transaction.objectStore('sources').put(source);
  for (const item of items) transaction.objectStore('items').put(item);
  for (const id of dropItems) transaction.objectStore('items').delete(id);
  for (const id of dropSources) transaction.objectStore('sources').delete(id);
  if (order) transaction.objectStore('meta').put({ key: 'order', ids: order });
  await done(transaction);
}

export async function clear() {
  const db = await base();
  const transaction = db.transaction(STORES, 'readwrite');
  for (const name of STORES) transaction.objectStore(name).clear();
  await done(transaction);
}
