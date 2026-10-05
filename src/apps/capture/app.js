import { ApiClient, ApiError } from './api.js';
import { SOURCES, WebcamSource } from './camera.js';

// ---- 設定: ?api=http://host:8000&tagger=../tagger/index.html
const params = new URLSearchParams(location.search);
const API_BASE = params.get('api') || localStorage.getItem('ic.api') || 'http://localhost:8000';
const TAGGER_URL = params.get('tagger') || '../tagger/index.html';
localStorage.setItem('ic.api', API_BASE);
const api = new ApiClient(API_BASE);

const $ = id => document.getElementById(id);
const state = {
  session: null, declaration: null, lastDeclarationId: null,
  selected: new Map(),          // uid -> count
  instruments: new Map(),       // uid -> instrument
  camera: null, shots: [], captureCount: 0,
};

// ---- util
function toast(msg, err = false) {
  const t = $('toast'); t.textContent = msg; t.className = 'show' + (err ? ' err' : '');
  clearTimeout(toast.h); toast.h = setTimeout(() => (t.className = ''), 3200);
}
const fail = e => toast(e instanceof ApiError ? `${e.message}` : `エラー: ${e.message}`, true);
const STEPS = { session: '1/4 セッション', declare: '2/4 宣言', confirm: '3/4 配置確認', capture: '4/4 撮影', summary: '終了' };
function show(view) {
  for (const v of ['session', 'declare', 'confirm', 'capture', 'summary']) $('view-' + v).hidden = v !== view;
  $('step-label').textContent = STEPS[view];
}
function li(...children) { const e = document.createElement('li'); e.append(...children); return e; }
function el(tag, props = {}, ...kids) { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; }
function nameBlock(inst) {
  return el('span', { className: 'name' }, inst.name, el('span', { className: 'path' }, `${inst.category_path}　${inst.instrument_uid}`));
}

// ---- 1. セッション
const saved = JSON.parse(localStorage.getItem('ic.session-form') || '{}');
for (const k of ['operator', 'location', 'lighting', 'camera']) if (saved[k]) $('f-' + k).value = saved[k];
if (saved.source) $('f-source').value = saved.source;

$('f-source').onchange = async () => {
  const wrap = $('f-device-wrap');
  wrap.hidden = $('f-source').value !== 'webcam';
  if (wrap.hidden) return;
  try {
    const devs = await WebcamSource.listDevices();
    $('f-device').replaceChildren(...devs.map((d, i) => el('option', { value: d.deviceId }, d.label || `カメラ${i + 1}`)));
  } catch (e) { toast('カメラを取得できません: ' + e.message, true); }
};
$('f-source').onchange();

$('btn-start').onclick = async () => {
  try {
    const form = { operator: $('f-operator').value, location: $('f-location').value, lighting: $('f-lighting').value, camera: $('f-camera').value, source: $('f-source').value };
    localStorage.setItem('ic.session-form', JSON.stringify(form));
    const Source = SOURCES[form.source];
    state.camera = form.source === 'webcam' ? new Source({ deviceId: $('f-device').value || undefined }) : new Source();
    state.session = await api.startSession({ operator: form.operator, location: form.location, lighting: form.lighting, camera_model: form.camera });
    await loadInstruments('');
    resetDeclaration();
    show('declare');
  } catch (e) { fail(e); }
};

// ---- 2. 宣言
async function loadInstruments(q) {
  const list = await api.searchInstruments(q);
  list.forEach(i => state.instruments.set(i.instrument_uid, i));
  renderResults(list);
}
function renderResults(list) {
  $('search-results').replaceChildren(...list.map(i => {
    const b = el('button', { textContent: '追加', onclick: () => { state.selected.set(i.instrument_uid, (state.selected.get(i.instrument_uid) || 0) + 1); renderDeclared(); } });
    return li(nameBlock(i), b);
  }));
}
let searchTimer;
$('search').oninput = e => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadInstruments(e.target.value).catch(fail), 200); };

function renderDeclared() {
  const rows = [...state.selected].map(([uid, n]) => {
    const inst = state.instruments.get(uid);
    const minus = el('button', { textContent: '−', onclick: () => { n > 1 ? state.selected.set(uid, n - 1) : state.selected.delete(uid); renderDeclared(); } });
    const plus = el('button', { textContent: '＋', onclick: () => { state.selected.set(uid, n + 1); renderDeclared(); } });
    return li(nameBlock(inst), minus, el('b', {}, `×${n}`), plus);
  });
  $('declared').replaceChildren(...rows);
  const total = [...state.selected.values()].reduce((a, b) => a + b, 0);
  $('declared-summary').textContent = total === 0 ? '器具を追加してください' : (total === 1 ? '単体撮影モード（1器具1個）' : `複数撮影モード（合計${total}個）`);
  $('btn-declare').disabled = total === 0;
}
function resetDeclaration() { state.selected.clear(); renderDeclared(); $('btn-copy').hidden = !state.lastDeclarationId; show('declare'); }

$('btn-copy').onclick = async () => {
  try { state.declaration = await api.createDeclaration(state.session.session_id, [], state.lastDeclarationId); toConfirm(); } catch (e) { fail(e); }
};
$('btn-declare').onclick = async () => {
  try {
    const items = [...state.selected].map(([instrument_uid, count]) => ({ instrument_uid, count }));
    state.declaration = await api.createDeclaration(state.session.session_id, items);
    toConfirm();
  } catch (e) { fail(e); }
};

// ---- 3. 配置確認
function toConfirm() {
  $('confirm-list').replaceChildren(...state.declaration.items.map(it => li(nameBlock(state.instruments.get(it.instrument_uid) || { name: it.instrument_uid, category_path: '', instrument_uid: it.instrument_uid }), el('b', {}, `×${it.count}`))));
  $('chk-confirm').checked = false; $('btn-confirm').disabled = true;
  show('confirm');
}
$('chk-confirm').onchange = e => ($('btn-confirm').disabled = !e.target.checked);
$('btn-back-declare').onclick = () => resetDeclaration();
$('btn-confirm').onclick = async () => {
  try {
    state.declaration = await api.confirmDeclaration(state.declaration.declaration_id);
    state.lastDeclarationId = state.declaration.declaration_id;
    await startCapture();
  } catch (e) { fail(e); }
};

// ---- 4. 撮影
async function startCapture() {
  const d = state.declaration;
  $('cap-mode').textContent = d.mode === 'single' ? '単体撮影' : '複数撮影';
  $('cap-items').textContent = d.items.map(i => `${state.instruments.get(i.instrument_uid)?.name ?? i.instrument_uid}×${i.count}`).join(' / ');
  $('cap-arr').textContent = d.arrangement_no;
  $('auto-wrap').hidden = d.mode !== 'single';
  state.captureCount = 0; $('cap-count').textContent = 0; $('shots').replaceChildren();
  show('capture');
  try {
    await state.camera.start($('preview'));
    $('no-preview').hidden = !$('preview').hidden;
  } catch (e) { toast('カメラを開始できません: ' + e.message, true); }
}

$('btn-shoot').onclick = async () => {
  const btn = $('btn-shoot'); btn.disabled = true;
  try {
    const blob = await state.camera.capture();
    const d = state.declaration;
    const meta = { lighting: state.session.lighting, camera_model: state.session.camera_model, source: $('f-source').value };
    const img = await api.uploadImage(d.declaration_id, blob, meta);   // 撮影直後に生データを保存
    state.captureCount++; $('cap-count').textContent = state.captureCount;
    const shot = addShot(img, blob);
    if (d.mode === 'single' && $('chk-auto').checked) {
      await api.tagFromDeclaration(img.image_id);
      shot.setTagged(true);
    } else {
      openTagger(img.image_id, shot);
    }
  } catch (e) { if (e.message !== 'cancelled') fail(e); } finally { btn.disabled = false; }
};

function addShot(img, blob) {
  const tag = el('span', {}, '未タグ');
  const node = el('div', { className: 'shot' }, el('img', { src: URL.createObjectURL(blob), alt: '' }), tag, el('small', {}, `配置${img.arrangement_no}`));
  const shot = { img, node, setTagged(v) { node.classList.toggle('tagged', v); tag.textContent = v ? 'タグ済' : '未タグ'; } };
  node.onclick = () => openTagger(img.image_id, shot);   // 未タグ・再編集どちらも可
  $('shots').prepend(node);
  return shot;
}

$('btn-rearrange').onclick = async () => {
  try {
    state.declaration = await api.rearrange(state.declaration.declaration_id);
    $('cap-arr').textContent = state.declaration.arrangement_no;
    toast('配置番号を進めました。器具を置き直してください');
  } catch (e) { fail(e); }
};
$('btn-new-decl').onclick = () => { state.camera.stop(); resetDeclaration(); };

// ---- タグ付けUI（別アプリ）との連携: iframe + postMessage
let pendingShot = null;
function openTagger(imageId, shot) {
  pendingShot = shot;
  const u = new URL(TAGGER_URL, location.href);
  u.searchParams.set('api', API_BASE); u.searchParams.set('image', imageId); u.searchParams.set('embed', '1');
  $('tagger-frame').src = u.href;
  $('tagger-overlay').hidden = false;
}
window.addEventListener('message', ev => {
  const m = ev.data;
  if (!m || m.source !== 'instrument-tagger') return;
  $('tagger-overlay').hidden = true; $('tagger-frame').src = 'about:blank';
  if (m.type === 'saved') { pendingShot?.setTagged(true); toast('タグを保存しました'); }
  pendingShot = null;
});

// ---- 5. 終了
$('btn-finish').onclick = async () => {
  try {
    state.camera.stop();
    await api.closeSession(state.session.session_id);
    const d = await api.dailyStats();
    $('summary-kpi').replaceChildren(
      ...[['取得枚数', d.images], ['配置数', d.arrangements], ['タグ付け済', d.tagged_images], ['未タグ', d.untagged_images.length]]
        .map(([l, v]) => el('div', {}, el('b', {}, String(v)), l)));
    $('report-link').href = api.reportUrl();
    show('summary');
  } catch (e) { fail(e); }
};
$('btn-restart').onclick = () => location.reload();

$('api-badge').textContent = API_BASE;
api.health().catch(() => toast('APIに接続できません: ' + API_BASE, true));
show('session');
