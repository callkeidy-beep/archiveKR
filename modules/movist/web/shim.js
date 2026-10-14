/* 로컬판 연결 장치: claude.ai 기능 대신 내 컴퓨터의 서버(app_server.py)를 쓴다 */
(function(){
  window.MOVIST_LOCAL = true;

  // 1) 보관함·편집국 규칙을 브라우저 대신 컴퓨터 파일(data/store.json)에 저장
  const KEYS = ['movist_history', 'movist_rules'];
  let store = {};
  try { const x = new XMLHttpRequest(); x.open('GET', '/api/movist/store', false); x.send(); store = JSON.parse(x.responseText || '{}'); } catch (_) {}
  const og = Storage.prototype.getItem, os = Storage.prototype.setItem, timers = {};
  Storage.prototype.getItem = function (k) { return (this === window.localStorage && KEYS.includes(k)) ? (store[k] ?? null) : og.call(this, k); };
  Storage.prototype.setItem = function (k, v) {
    if (this === window.localStorage && KEYS.includes(k)) {
      store[k] = String(v); clearTimeout(timers[k]);
      timers[k] = setTimeout(() => fetch('/api/movist/store', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: k, value: store[k] }), keepalive: true }), 300);
      return;
    }
    return os.call(this, k, v);
  };

  // 2) Claude 호출 → 내 API 키로
  const sample = {
    async json(prompt, opts) {
      let r;
      try {
        r = await fetch('/api/movist/claude', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt }), signal: opts && opts.signal });
      } catch (e) { if (e && e.name === 'AbortError') throw { code: 'cancelled' }; throw { code: 'server_off' }; }
      const d = await r.json().catch(() => ({ error: 'bad_response' }));
      if (!r.ok || d.error) throw { code: r.status === 429 ? 'rate_limited' : (d.error || 'error') };
      return d.result;
    },
    async text(prompt, opts) { const r = await sample.json(prompt + '\n\n{"text": "..."} 형식 JSON으로만 답하라.', opts); return r.text; }
  };

  // 3) 파일 저장 → output 폴더로
  const downloads = {
    async save({ filename, data }) {
      const body = data instanceof Blob ? data : new Blob([data]);
      const r = await fetch('/api/movist/save?filename=' + encodeURIComponent(filename), { method: 'POST', body });
      const d = await r.json();
      if (!r.ok) throw { code: d.error || 'error' };
      if (window.toast) toast('저장: ' + d.path);
      return { status: 'saved' };
    }
  };
  window.claude = { use: async (name) => name === 'sample' ? sample : name === 'downloads' ? downloads : null };

  // 4) URL 자동 불러오기 버튼
  async function loadFromUrl() {
    const url = document.getElementById('url').value.trim();
    if (!/^https?:\/\//.test(url)) { setStatus('기사 주소를 http로 시작하게 넣어 주세요.', true); return; }
    const btn = document.getElementById('fetchUrl'); btn.disabled = true;
    setStatus('기사를 불러오는 중… 사진까지 내려받습니다.');
    try {
      const r = await fetch('/api/movist/fetch?url=' + encodeURIComponent(url));
      const a = await r.json();
      if (!r.ok || a.error) throw new Error(a.error || '불러오기 실패');
      ['title', 'author', 'credit', 'body'].forEach(k => { if (a[k]) document.getElementById(k).value = a[k]; });
      pool.length = 0;
      const files = [];
      for (const [i, src] of (a.images || []).entries()) {
        const b = await (await fetch(src)).blob();
        files.push(new File([b], `photo_${i + 1}.jpg`, { type: b.type || 'image/jpeg' }));
      }
      if (files.length) await addFiles(files);
      setStatus(`불러왔습니다. 본문 ${a.body.length.toLocaleString()}자, 사진 ${files.length}장. 채널별로 변환을 누르세요.` + (a.body.length < 200 ? ' (본문이 짧습니다. 직접 붙여넣어 주세요)' : ''), a.body.length < 200);
    } catch (e) {
      setStatus('불러오지 못했습니다: ' + e.message + ' — 본문을 직접 붙여넣어 주세요.', true);
    } finally { btn.disabled = false; }
  }
  document.addEventListener('DOMContentLoaded', () => {
    const u = document.getElementById('url'); if (!u) return;
    const wrap = document.createElement('div'); wrap.style.cssText = 'display:flex;gap:8px';
    u.parentNode.insertBefore(wrap, u); wrap.appendChild(u);
    const b = document.createElement('button'); b.id = 'fetchUrl'; b.type = 'button'; b.textContent = '불러오기'; b.style.whiteSpace = 'nowrap';
    b.onclick = loadFromUrl; wrap.appendChild(b);
    u.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); loadFromUrl(); } });
    u.addEventListener('change', () => { if (!document.getElementById('body').value.trim()) loadFromUrl(); });
    const sub = document.querySelector('.sub'); if (sub) sub.textContent = '로컬판 · 기사 주소를 넣고 불러오기를 누르면 본문과 사진을 가져옵니다.';
  });
})();
