/* One fetch helper for the whole app.
   - same-origin cookies
   - throws ApiError {status, detail, retryable} built from the server's {detail, retryable} body
   - a 401 anywhere calls the unauthorized handler (the shell shows the login screen on top of the
     current screen, so unsent input survives)
   - a timeout, because mobile fetches can hang forever in a tunnel */
export class ApiError extends Error {
  constructor(status, detail, retryable = false) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.retryable = retryable;
  }
  get offline() { return this.status === 0; }
  get cancelled() { return this.status === -1; }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

function describe(status, data) {
  if (data && typeof data.detail === 'string') return data.detail;
  if (data && Array.isArray(data.detail)) {
    // FastAPI validation errors: make the first one readable instead of dumping JSON.
    const e = data.detail[0] || {};
    return `${(e.loc || []).slice(1).join('.')}: ${e.msg || 'invalid'}`;
  }
  if (status === 429) return 'Too many requests. Wait a minute and try again.';
  if (status >= 500) return 'The server had a problem. Try again in a minute.';
  return `Request failed (${status})`;
}

export async function api(path, { method = 'GET', body, headers = {}, timeout = 120000, raw = false, signal = null } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  if (signal) signal.addEventListener('abort', () => ctrl.abort(), { once: true });
  const opts = { method, credentials: 'same-origin', headers: { ...headers }, signal: ctrl.signal };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    clearTimeout(timer);
    if (e.name === 'AbortError') {
      if (signal && signal.aborted) throw new ApiError(-1, 'Cancelled.', false);
      throw new ApiError(0, 'The request timed out. Check the connection and retry.', true);
    }
    throw new ApiError(0, navigator.onLine === false ? 'You are offline.' : 'Network error. Retry in a moment.', true);
  }
  clearTimeout(timer);
  if (raw) {
    if (!res.ok) {
      let data = null;
      try { data = await res.json(); } catch { /* not json */ }
      if (res.status === 401) onUnauthorized();
      throw new ApiError(res.status, describe(res.status, data), !!(data && data.retryable) || res.status === 429 || res.status >= 500);
    }
    return res;
  }
  const type = res.headers.get('content-type') || '';
  let data = null;
  if (type.includes('application/json')) {
    try { data = await res.json(); } catch { data = null; }
  }
  if (!res.ok) {
    if (res.status === 401) onUnauthorized();
    throw new ApiError(res.status, describe(res.status, data), !!(data && data.retryable) || res.status === 429 || res.status >= 500);
  }
  return data;
}

/* Multipart upload of a recording. `fields` are extra form fields. */
export function upload(path, blob, filename, fields = {}, opts = {}) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) if (v != null) fd.append(k, v);
  fd.append('file', blob, filename);
  return api(path, { method: 'POST', body: fd, ...opts });
}

/* MediaRecorder picks its own container: iOS gives audio/mp4, Chrome audio/webm. Name the file so
   the server's mime fallback (by extension) also works. */
export function audioFilename(mime) {
  const m = (mime || '').toLowerCase();
  if (m.includes('mp4') || m.includes('m4a') || m.includes('aac')) return 'clip.m4a';
  if (m.includes('ogg')) return 'clip.ogg';
  if (m.includes('wav')) return 'clip.wav';
  return 'clip.webm';
}
