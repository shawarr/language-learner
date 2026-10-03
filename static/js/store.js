/* IndexedDB, promise-wrapped. Two queues that must survive a tunnel, a 503 or an app restart:
   - recordings: a voice turn's blob, kept until the server answers 2xx
   - ratings: review ratings made offline, flushed when back online
   Nothing here is the source of truth; the server is. */
const DB_NAME = 'deutsch-tutor';
const VERSION = 1;
let dbp = null;

function open() {
  if (dbp) return dbp;
  dbp = new Promise((resolve, reject) => {
    if (!('indexedDB' in window)) { reject(new Error('no indexedDB')); return; }
    const req = indexedDB.open(DB_NAME, VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('recordings')) db.createObjectStore('recordings', { keyPath: 'id', autoIncrement: true });
      if (!db.objectStoreNames.contains('ratings')) db.createObjectStore('ratings', { keyPath: 'id', autoIncrement: true });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbp;
}

function tx(store, mode, fn) {
  return open().then((db) => new Promise((resolve, reject) => {
    const t = db.transaction(store, mode);
    const req = fn(t.objectStore(store));
    t.oncomplete = () => resolve(req && req.result);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error);
  })).catch((e) => { console.warn('store unavailable', e); return undefined; });
}

export const store = {
  add: (s, value) => tx(s, 'readwrite', (os) => os.add(value)),
  put: (s, value) => tx(s, 'readwrite', (os) => os.put(value)),
  remove: (s, id) => tx(s, 'readwrite', (os) => os.delete(id)),
  all: (s) => tx(s, 'readonly', (os) => os.getAll()).then((r) => r || []),
  clear: (s) => tx(s, 'readwrite', (os) => os.clear()),
};
