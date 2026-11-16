(function () {
  'use strict';
  // 엽서 목록 — 시안의 recordData 를 서버 회차로 채운다.
  //   · GET /api/sessions?has_postcard=1&elder_id=<고른 화자>  (엽서가 있는 회차만, 최근 순)
  //   · 화면은 record.id 를 숫자로 쓴다 → 회차마다 숫자 번호를 붙이고 session_id 는 따로 들고 있는다.
  //   · 엽서 글(body)은 목록에 없다 → GET /api/sessions/{id}/record 의 postcard.text 를 뒤에서 천천히 받는다.
  //   · 주제(분류)는 회차 제목(=인터뷰 주제)으로 가른다. 모르면 「삶과 일」.
  //   · 지우기는 DELETE /api/sessions/{id} (서버는 숨김 처리) — postcards-cork 의 지우기가 부른다.
  const {api, AUTH, CONFIG} = window.Srv;
  const ids = new Map();      // session_id → 화면 번호
  let nextId = 1, loadSeq = 0, ctl = null;
  const numberFor = (sid) => { if (!ids.has(sid)) ids.set(sid, nextId++); return ids.get(sid); };
  const fmtDate = (iso) => { const d = new Date(iso); return isNaN(d) ? '' : `${d.getFullYear()}. ${d.getMonth() + 1}. ${d.getDate()}.`; };
  function categoryOf(title) {
    const t = String(title || '');
    if (/어린|유년|학교|동네|어릴/.test(t)) return 'childhood';
    if (/가족|부모|어머니|아버지|자녀|결혼|family/.test(t)) return 'family';
    return 'life';
  }
  const ICON = {childhood: 'leaf', family: 'home', life: 'letter'};
  const firstLine = (text) => { const s = String(text || '').replace(/\s+/g, ' ').trim(); return s.length > 70 ? s.slice(0, 68) + '…' : s; };

  function toRecord(row) {
    const category = categoryOf(row.title);
    const title = (row.postcard_title || '').trim() || (row.title || '').trim() || '제목 없는 이야기';
    return {
      id: numberFor(row.session_id), session_id: row.session_id, elder_id: row.elder_id || '',
      title, created_at: row.created_at, date: fmtDate(row.created_at),
      category, icon: ICON[category], topic: row.title || '',
      description: '엽서를 불러오는 중이에요…', body: undefined, photo_id: row.photo_id || null,
      sourceSession: {created_at: row.created_at, session_id: row.session_id},
    };
  }
  function redraw() {
    renderRecent();
    if (location.hash === '#records') renderRecords();
    window.dispatchEvent(new CustomEvent('memoir:records'));
  }

  async function reload() {
    const my = ++loadSeq;
    if (ctl) ctl.abort();
    if (!AUTH.user || !AUTH.elderId) { recordData.length = 0; pending = []; state.recordState = 'normal'; redraw(); return; }
    ctl = new AbortController();
    try {
      const r = await api.sessions(100, ctl.signal, {elderId: AUTH.elderId, hasPostcard: true});
      if (my !== loadSeq) return;
      const rows = ((r && r.sessions) || []).filter((x) => x.has_postcard !== false && (!x.elder_id || x.elder_id === AUTH.elderId));
      const keep = new Map(recordData.map((x) => [x.session_id, x]));
      recordData.length = 0;
      rows.forEach((row) => {
        const old = keep.get(row.session_id), rec = toRecord(row);
        if (old && old.body !== undefined) { rec.body = old.body; rec.description = old.description; }
        recordData.push(rec);
      });
      // 고른 엽서 중 사라진 것은 빼 둔다
      [...state.selected].forEach((id) => { if (!recordData.some((x) => x.id === id)) state.selected.delete(id); });
      state.recordState = 'normal';
      redraw();
      void fillBodies(my);
      void loadPending(my);
    } catch (e) {
      if (e.name === 'AbortError' || my !== loadSeq) return;
      state.recordState = e.status === 401 ? 'normal' : 'error';
      redraw();
    }
  }

  // 엽서 글을 뒤에서 천천히 — 한 번에 셋씩
  async function fillBodies(my) {
    const queue = recordData.filter((x) => x.body === undefined);
    const worker = async () => {
      while (queue.length && my === loadSeq) {
        const rec = queue.shift();
        await loadBody(rec);
      }
    };
    await Promise.all([worker(), worker(), worker()]);
    if (my === loadSeq) redraw();
  }
  async function loadBody(rec) {
    if (rec.body !== undefined) return rec.body;
    if (rec._loading) return rec._loading;
    rec._loading = (async () => {
      try {
        const r = await api.record(rec.session_id);
        const pc = (r && r.postcard) || {};
        rec.body = String(pc.text || '').trim();
        if (pc.title && String(pc.title).trim()) rec.title = String(pc.title).trim();
        rec.description = firstLine(rec.body) || '엽서 글이 비어 있어요.';
        rec.caption = String(pc.caption || '');
        rec.postcard = pc;
      } catch (_) {
        rec.description = '엽서 글을 불러오지 못했어요.';
      } finally { delete rec._loading; }
      return rec.body;
    })();
    return rec._loading;
  }

  async function remove(records) {
    const done = [], failed = [];
    for (const rec of records) {
      try { await window.Srv.call(`/sessions/${encodeURIComponent(rec.session_id)}`, {method: 'DELETE'}); done.push(rec); }
      catch (e) { if (e.status === 404) done.push(rec); else failed.push(rec); }
    }
    return {done, failed};
  }

  // 엽서 글 — 서버에서 받은 글만 쓴다 (시안의 예시 글로 채우지 않는다)
  window.postcardBody = (r) => typeof r.body === 'string' ? (r.body || '엽서 글이 비어 있어요.') : '엽서 글을 불러오는 중이에요…';
  // 처음가기 「최근 나눈 이야기」에서 여는 엽서 창 — 글을 받은 뒤 연다
  const openOriginal = window.openPostcard;
  window.openPostcard = async (id, opener = document.activeElement) => {
    const rec = recordData.find((x) => x.id === id);
    if (rec && rec.body === undefined) await loadBody(rec);
    openOriginal(id, opener);
  };
  // 시안이 넣어 둔 예시 엽서는 지운다 — 로그인 전에는 빈 목록
  recordData.length = 0;
  // 다시 불러오기는 role-preview-view 의 refreshOwnership(로그인 · 화자 바꿈)이 부른다
  // ── 엽서로 만들기 전의 이야기 — 마친(CLOSED) · 말씀 있는(has_words) · 엽서 없는 회차 ──
  let pending = [];
  async function loadPending(my) {
    try {
      const r = await api.sessions(50, undefined, {elderId: AUTH.elderId});
      if (my !== loadSeq) return;
      pending = ((r && r.sessions) || []).filter((x) => String(x.state || '').toUpperCase() === 'CLOSED' && x.has_words && !x.has_postcard
        && (!x.elder_id || x.elder_id === AUTH.elderId))
        .map((x) => ({session_id: x.session_id, title: (x.title || '').trim() || '제목 없는 이야기', date: fmtDate(x.created_at)}));
    } catch (_) { pending = []; }
    if (location.hash === '#records') renderPendingStories();
  }
  window.renderPendingStories = () => {
    const box = document.getElementById('pending-stories');
    box.hidden = !pending.length;
    document.getElementById('pending-stories-summary').textContent = `엽서로 만들기 전의 이야기 (${pending.length})`;
    document.getElementById('pending-story-list').innerHTML = pending.map((p) => `<div class="pending-story-row"><strong>${escapeText(p.title)}<small> · ${escapeText(p.date)}</small></strong><button type="button" class="button outline compact" data-review-story="${escapeText(p.session_id)}" aria-label="${escapeText(p.title)} 확인">이야기 확인</button></div>`).join('');
  };
  window.SrvRecords = {reload, loadBody, remove, bySession: (sid) => recordData.find((x) => x.session_id === sid), numberFor, pending: () => pending.slice()};
  void CONFIG;
}());
