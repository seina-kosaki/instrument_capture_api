import { ApiClient, ApiError } from './api.js';

// ?api=...&image=<id>&embed=1   embed=1 のときは親ウィンドウへ postMessage で結果を通知する
const params = new URLSearchParams(location.search);
const API_BASE = params.get('api') || localStorage.getItem('ic.api') || 'http://localhost:8000';
const IMAGE_ID = params.get('image');
const EMBED = params.get('embed') === '1';
const api = new ApiClient(API_BASE);
const $ = id => document.getElementById(id);
const COLORS = ['#e4572e', '#17a398', '#7b2cbf', '#f2a541', '#1d6fa5', '#6a994e'];

const S = {
  image: null, decl: null, instruments: new Map(), imgEl: null,
  hints: [],            // {uid, center, end_a, end_b, occluded, visible, added, hint_source}
  selectedUid: null,    // 次にタップした位置に置く器具
  active: null,         // 描画中のhint（端点入力待ち）
  mode: null,           // 'end_a' | 'end_b' | null
  extraUids: new Set(), // 宣言外から追加した器具
};

function toast(msg, err = false) {
  const t = $('toast'); t.textContent = msg; t.className = 'show' + (err ? ' err' : '');
  clearTimeout(toast.h); toast.h = setTimeout(() => (t.className = ''), 3000);
}
const fail = e => toast(e instanceof ApiError ? e.message : 'エラー: ' + e.message, true);
const el = (tag, props = {}, ...kids) => { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; };
const inst = uid => S.instruments.get(uid) || { name: uid };
const colorOf = uid => COLORS[[...S.instruments.keys()].indexOf(uid) % COLORS.length] || '#444';
const notify = (type) => { if (EMBED && window.parent !== window) window.parent.postMessage({ source: 'instrument-tagger', type, image_id: IMAGE_ID }, '*'); };

// ---- 起動
async function main() {
  if (!IMAGE_ID) return showList();
  try {
    S.image = await api.getImage(IMAGE_ID);
    const [decl, list, tags] = await Promise.all([api.getDeclaration(S.image.declaration_id), api.getInstruments(), api.getTags(IMAGE_ID)]);
    S.decl = decl; list.forEach(i => S.instruments.set(i.instrument_uid, i));
    S.hints = tags.hints.map(h => ({ uid: h.instrument_uid, center: h.center, end_a: h.end_a, end_b: h.end_b, occluded: h.occluded,
      visible: h.visible, added: h.added_after_capture, hint_source: h.hint_source }));
    await loadImage(); buildPalette(); $('view-tag').hidden = false;
    $('btn-accept').hidden = decl.mode !== 'single';
    if (!S.hints.length && decl.items.length === 1) select(decl.items[0].instrument_uid);
    render();
  } catch (e) { fail(e); }
}

async function showList() {
  $('view-list').hidden = false;
  try {
    const imgs = await api.listUntagged();
    $('untagged').replaceChildren(...imgs.map(i => {
      const a = el('a', { href: `?api=${encodeURIComponent(API_BASE)}&image=${i.image_id}` }, el('img', { src: api.fileUrl(i), alt: '' }), el('span', {}, `${i.captured_at.slice(0, 16).replace('T', ' ')} 配置${i.arrangement_no}`));
      return a;
    }));
    if (!imgs.length) $('untagged').textContent = '未タグの画像はありません';
  } catch (e) { fail(e); }
}

function loadImage() {
  return new Promise((res, rej) => {
    const im = new Image(); im.crossOrigin = 'anonymous';
    im.onload = () => { S.imgEl = im; res(); }; im.onerror = () => rej(new Error('画像を読み込めません'));
    im.src = api.fileUrl(S.image);
  });
}

// ---- パレット（宣言された器具 + 残数）
const placed = uid => S.hints.filter(h => h.uid === uid && !h.added).length;
function buildPalette() {
  const rows = S.decl.items.map(it => {
    const remain = it.count - placed(it.instrument_uid);
    const li = el('li', { className: (S.selectedUid === it.instrument_uid ? 'sel ' : '') + (remain <= 0 ? 'done' : '') },
      el('span', { className: 'dot', style: `background:${colorOf(it.instrument_uid)}` }),
      el('span', { className: 'name', onclick: () => select(it.instrument_uid) }, `${inst(it.instrument_uid).name}　残り${Math.max(remain, 0)}/${it.count}`),
      el('button', { textContent: '見えない', title: '画面外・完全に隠れている', disabled: remain <= 0, onclick: () => addInvisible(it.instrument_uid) }));
    return li;
  });
  for (const uid of S.extraUids) {
    rows.push(el('li', { className: S.selectedUid === uid ? 'sel' : '' },
      el('span', { className: 'dot', style: `background:${colorOf(uid)}` }),
      el('span', { className: 'name', onclick: () => select(uid) }, `${inst(uid).name}（宣言外）`)));
  }
  $('palette').replaceChildren(...rows);
  const sel = $('extra-select');
  if (!sel.options.length) sel.replaceChildren(...[...S.instruments.values()].map(i => el('option', { value: i.instrument_uid }, i.name)));
}
$('btn-extra-pick').onclick = () => { const uid = $('extra-select').value; S.extraUids.add(uid); select(uid); };

function select(uid) { S.selectedUid = uid; S.active = null; S.mode = null; render(); }

function addInvisible(uid) {
  S.hints.push({ uid, visible: false, hint_source: 'none', center: null, end_a: null, end_b: null, occluded: false, added: false });
  render();
}

// ---- キャンバス操作: 中心 → 端点A → 端点B
const canvas = $('canvas');
canvas.addEventListener('pointerdown', ev => {
  if (!S.imgEl) return;
  const r = canvas.getBoundingClientRect();
  const x = Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width));
  const y = Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height));
  const status = $('chk-estimated').checked ? 'estimated' : 'visible';
  const pt = { x: +x.toFixed(5), y: +y.toFixed(5), status };
  if (S.mode && S.active) {
    S.active[S.mode] = pt;
    S.mode = S.mode === 'end_a' ? 'end_b' : null;
    if (!S.mode) S.active = null;
  } else if (S.selectedUid) {
    const declared = S.decl.items.find(i => i.instrument_uid === S.selectedUid);
    const isAdded = !declared || placed(S.selectedUid) >= declared.count;
    const h = { uid: S.selectedUid, visible: true, hint_source: 'manual', center: pt, end_a: null, end_b: null, occluded: pt.status === 'estimated', added: isAdded };
    S.hints.push(h); S.active = h; S.mode = 'end_a';
  } else { toast('先に器具を選択してください', true); return; }
  render();
});
$('btn-finish-hint').onclick = () => { S.active = null; S.mode = null; render(); };

function draw() {
  const im = S.imgEl; if (!im) return;
  const maxW = Math.min(1400, im.naturalWidth);
  canvas.width = maxW; canvas.height = Math.round(maxW * im.naturalHeight / im.naturalWidth);
  const g = canvas.getContext('2d'), W = canvas.width, H = canvas.height;
  g.drawImage(im, 0, 0, W, H);
  const P = p => [p.x * W, p.y * H];
  S.hints.forEach((h, idx) => {
    if (!h.center) return;
    const col = colorOf(h.uid), [cx, cy] = P(h.center);
    g.strokeStyle = col; g.fillStyle = col; g.lineWidth = Math.max(2, W / 400);
    if (h.end_a && h.end_b) { g.setLineDash([8, 6]); g.beginPath(); g.moveTo(...P(h.end_a)); g.lineTo(...P(h.end_b)); g.stroke(); g.setLineDash([]); }
    for (const [k, p] of [['end_a', h.end_a], ['end_b', h.end_b]]) {
      if (!p) continue; const [x, y] = P(p), s = W / 110;
      g.fillRect(x - s / 2, y - s / 2, s, s);
      g.font = `${Math.round(W / 60)}px sans-serif`; g.fillText(k === 'end_a' ? 'A' : 'B', x + s, y - s);
    }
    g.beginPath(); g.arc(cx, cy, W / 120, 0, Math.PI * 2);
    if (h.center.status === 'estimated') { g.setLineDash([4, 3]); g.stroke(); g.setLineDash([]); } else g.fill();
    const label = `${inst(h.uid).name} #${S.hints.slice(0, idx + 1).filter(x => x.uid === h.uid).length}`;
    g.font = `bold ${Math.round(W / 55)}px sans-serif`;
    const tw = g.measureText(label).width + 10, lh = W / 45;
    g.fillStyle = col; g.fillRect(cx + W / 100, cy - lh - 4, tw, lh);
    g.fillStyle = '#fff'; g.fillText(label, cx + W / 100 + 5, cy - 8);
  });
}

// ---- 描画・状態表示
function render() {
  draw(); buildPalette();
  const def = S.mode === 'end_a' ? '端点A（先端側）' : '端点B（基部側）';
  $('prompt').textContent = S.mode ? `${inst(S.active.uid).name}：${def}をタップ（不要なら「中心のみで完了」）`
    : S.selectedUid ? `${inst(S.selectedUid).name}：中心をタップ` : '器具を選択してください';
  $('btn-finish-hint').disabled = !S.mode;
  $('hints').replaceChildren(...S.hints.map((h, i) => {
    const q = !h.visible ? '見えない' : (h.end_a && h.end_b ? '3点' : '中心のみ');
    const occ = el('input', { type: 'checkbox', checked: h.occluded, disabled: !h.visible, title: '重なり・遮蔽あり', onchange: e => { h.occluded = e.target.checked; scheduleValidate(); } });
    return el('li', {}, el('span', { className: 'dot', style: `background:${colorOf(h.uid)}` }),
      el('span', { className: 'name' }, inst(h.uid).name, ' ', el('span', { className: 'q' }, `(${q}${h.added ? '・宣言外' : ''})`)),
      el('label', { className: 'q' }, occ, '遮蔽'),
      el('button', { textContent: '削除', onclick: () => { S.hints.splice(i, 1); if (S.active === h) { S.active = null; S.mode = null; } render(); } }));
  }));
  scheduleValidate();
}

// ---- ライブ検証（保存しない）
const toApi = h => ({
  instrument_uid: h.uid, hint_source: h.visible ? h.hint_source : 'none', visible: h.visible,
  center: h.center, end_a: h.end_a, end_b: h.end_b, occluded: !!h.occluded, added_after_capture: !!h.added,
});
let vTimer;
function scheduleValidate() { clearTimeout(vTimer); vTimer = setTimeout(runValidate, 250); }
async function runValidate() {
  try {
    const r = await api.validate(IMAGE_ID, S.hints.map(toApi));
    const box = $('issues');
    const rows = [...r.errors.map(i => el('div', { className: 'err' }, '✖ ' + i.message + (i.instrument_uid ? `（${inst(i.instrument_uid).name}）` : ''))),
      ...r.warnings.map(i => el('div', { className: 'warn' }, '△ ' + i.message))];
    if (!rows.length) rows.push(el('div', { className: 'ok' }, '整合性チェック OK'));
    box.replaceChildren(...rows);
    $('btn-save').disabled = r.errors.length > 0;
  } catch (e) { /* 検証失敗時は保存時に再チェックされる */ }
}

// ---- 保存・キャンセル
$('btn-save').onclick = async () => {
  try { await api.saveTags(IMAGE_ID, S.hints.map(toApi), 'tagger-ui'); done('saved'); } catch (e) { fail(e); }
};
$('btn-accept').onclick = async () => {
  try { await api.tagFromDeclaration(IMAGE_ID); done('saved'); } catch (e) { fail(e); }
};
$('btn-cancel').onclick = () => done('cancel');
function done(type) {
  notify(type);
  if (!EMBED) { toast(type === 'saved' ? '保存しました' : '保留にしました'); setTimeout(() => (location.search = `?api=${encodeURIComponent(API_BASE)}`), 600); }
}
window.addEventListener('resize', () => draw());
main();
