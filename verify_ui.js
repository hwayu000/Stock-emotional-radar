// 以 DOM 樁在 Node 中執行儀表板的渲染邏輯，捕捉運行期錯誤
// 用法: node verify_ui.js
const fs = require('fs');

function makeCtx() {
  return new Proxy({}, {
    get(t, k) {
      if (k === 'createLinearGradient') return () => ({ addColorStop() {} });
      if (k === 'measureText') return () => ({ width: 10 });
      return typeof t[k] !== 'undefined' ? t[k] : () => {};
    },
    set(t, k, v) { t[k] = v; return true; },
  });
}

function makeEl(tag) {
  const el = {
    tag, style: {}, children: [], _innerHTML: '', _attrs: {},
    set innerHTML(v) { this._innerHTML = String(v); if (!v) this.children.length = 0; },
    get innerHTML() { return this._innerHTML; },
    set textContent(v) { this._tc = String(v); },
    get textContent() { return this._tc || ''; },
    className: '', tabIndex: 0,
    onclick: null, onkeydown: null, onmousemove: null, onmouseleave: null,
    clientWidth: 900, clientHeight: 200, width: 0, height: 0,
    appendChild(c) { this.children.push(c); },
    setAttribute(k, v) { this._attrs[k] = v; },
    getAttribute(k) { return this._attrs[k]; },
    contains() { return false; },
    getContext() { return makeCtx(); },
    getBoundingClientRect() { return { left: 0, top: 0, width: 900, height: 200 }; },
  };
  el.classList = {
    _s: new Set(),
    toggle(c) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); },
    add(c) { this._s.add(c); },
    remove(c) { this._s.delete(c); },
    contains(c) { return this._s.has(c); },
  };
  return el;
}

const registry = {};
const documentStub = {
  documentElement: makeEl('html'),
  getElementById(id) { return registry[id] || (registry[id] = makeEl('div#' + id)); },
  createElement(tag) { return makeEl(tag); },
  addEventListener() {},
};
const localStorageStub = { _m: {}, getItem(k) { return this._m[k] || null; }, setItem(k, v) { this._m[k] = v; } };
const matchMediaStub = () => ({ matches: false });
const getComputedStyleStub = () => ({ getPropertyValue: () => '#888888' });
const windowStub = { devicePixelRatio: 1, matchMedia: matchMediaStub };

new Function('window', fs.readFileSync('docs/data.js', 'utf8'))(windowStub);

const html = fs.readFileSync('docs/index.html', 'utf8');
const blocks = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]).filter(s => s.trim());
const main = blocks[blocks.length - 1];

let failures = 0;
function check(name, fn) {
  try { fn(); console.log('PASS', name); }
  catch (e) { failures++; console.error('FAIL', name, '—', e.message); }
}

try {
  new Function('window', 'document', 'addEventListener', 'innerWidth',
    'localStorage', 'matchMedia', 'getComputedStyle', main)(
    windowStub, documentStub, () => {}, 1200,
    localStorageStub, matchMediaStub, getComputedStyleStub);
} catch (e) {
  console.error('FAIL 初始渲染 —', e.stack);
  process.exit(1);
}
console.log('PASS 初始渲染');

const D = windowStub.RADAR_DATA;

check('分頁切換（含美股群組）', () => {
  for (let i = 0; i < D.assets.length; i++) registry['seg'].children[i].onclick();
});
check('美股排行 bar 點擊下鑽', () => {
  const usIdx = D.assets.findIndex(a => a.is_group);
  if (usIdx < 0) throw new Error('找不到美股群組');
  registry['seg'].children[usIdx].onclick();
  const rows = registry['rankList'].children;
  if (rows.length < 2) throw new Error('排行列數不足: ' + rows.length);
  for (const r of rows) r.onclick();
  rows[0].onkeydown({ key: 'Enter', preventDefault() {} });
});
check('時間週期 7/30/90/ALL 切換', () => {
  for (let i = 0; i < registry['rangeSeg'].children.length; i++)
    registry['rangeSeg'].children[i].onclick();
});
check('日夜主題切換', () => {
  registry['themeBtn'].onclick();
  if (documentStub.documentElement.getAttribute('data-theme') !== 'dark' &&
      documentStub.documentElement.getAttribute('data-theme') !== 'light')
    throw new Error('data-theme 未設定');
  registry['themeBtn'].onclick();
});
check('字體大小與對比設定', () => {
  registry['fontBtn'].onclick();
  for (let i = 0; i < registry['fsSeg'].children.length; i++) registry['fsSeg'].children[i].onclick();
  for (let i = 0; i < registry['ctSeg'].children.length; i++) registry['ctSeg'].children[i].onclick();
  if (!documentStub.documentElement.getAttribute('data-fs')) throw new Error('data-fs 未設定');
});
check('關鍵卡片皆有內容', () => {
  const usIdx = D.assets.findIndex(a => a.is_group);
  if (usIdx >= 0) registry['seg'].children[usIdx].onclick();
  for (const id of ['stats', 'teGrid', 'artList', 'distBar', 'stamp']) {
    const el = registry[id];
    if (!el || !el.innerHTML || el.innerHTML.length < 10)
      throw new Error(`#${id} 沒有渲染出內容`);
  }
  if (usIdx >= 0 && !registry['rankList'].children.length)
    throw new Error('#rankList 沒有渲染出排行列');
});

if (failures) { console.error(failures + ' 項檢查失敗'); process.exit(1); }
console.log('ALL UI CHECKS PASSED');
