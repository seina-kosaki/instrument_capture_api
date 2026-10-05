// 撮影アプリ用 APIクライアント。HTTP契約（/docs の OpenAPI）だけに依存する。
export class ApiError extends Error {
  constructor(status, payload) {
    super(payload?.message || `HTTP ${status}`);
    this.status = status;
    this.payload = payload;
  }
}

export class ApiClient {
  constructor(base) { this.base = base.replace(/\/$/, ''); }

  async #req(path, opts = {}) {
    const res = await fetch(this.base + path, opts);
    if (!res.ok) {
      let payload = null;
      try { payload = await res.json(); } catch { /* noop */ }
      throw new ApiError(res.status, payload);
    }
    return res.status === 204 ? null : res.json();
  }
  #json(method, body) {
    return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) };
  }

  health() { return this.#req('/health'); }
  searchInstruments(q = '') { return this.#req('/instruments?limit=200&q=' + encodeURIComponent(q)); }
  startSession(info) { return this.#req('/sessions', this.#json('POST', info)); }
  closeSession(id) { return this.#req(`/sessions/${id}/close`, { method: 'POST' }); }
  createDeclaration(sessionId, items, copyFrom = null) {
    return this.#req(`/sessions/${sessionId}/declarations`, this.#json('POST', { items, copy_from: copyFrom }));
  }
  confirmDeclaration(id) { return this.#req(`/declarations/${id}/confirm`, { method: 'POST' }); }
  rearrange(id) { return this.#req(`/declarations/${id}/rearrange`, { method: 'POST' }); }
  uploadImage(declarationId, blob, meta = {}) {
    const fd = new FormData();
    fd.append('file', blob, 'capture.jpg');
    fd.append('meta', JSON.stringify(meta));
    return this.#req(`/declarations/${declarationId}/images`, { method: 'POST', body: fd });
  }
  tagFromDeclaration(imageId) { return this.#req(`/images/${imageId}/tags/from-declaration`, { method: 'POST' }); }
  dailyStats() { return this.#req('/stats/daily'); }
  reportUrl() { return this.base + '/reports/daily'; }
}
