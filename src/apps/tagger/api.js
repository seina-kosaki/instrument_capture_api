// タグ付けUI用 APIクライアント（撮影アプリとは独立。HTTP契約のみに依存）
export class ApiError extends Error {
  constructor(status, payload) { super(payload?.message || `HTTP ${status}`); this.status = status; this.payload = payload; }
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
    return res.json();
  }
  #json(body) { return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }; }

  getImage(id) { return this.#req(`/images/${id}`); }
  fileUrl(img) { return this.base + img.file_url; }
  listUntagged() { return this.#req('/images?tag_status=untagged&limit=200'); }
  getDeclaration(id) { return this.#req(`/declarations/${id}`); }
  getInstruments() { return this.#req('/instruments?limit=1000'); }
  getTags(id) { return this.#req(`/images/${id}/tags`); }
  validate(id, hints) { return this.#req(`/images/${id}/tags/validate`, this.#json({ hints })); }
  saveTags(id, hints, taggedBy = '') {
    return this.#req(`/images/${id}/tags`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ hints, tagged_by: taggedBy }) });
  }
  tagFromDeclaration(id) { return this.#req(`/images/${id}/tags/from-declaration`, { method: 'POST' }); }
}
