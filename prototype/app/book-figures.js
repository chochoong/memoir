(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     book-figures — 책 안의 사진 · 삽화 (자서전 화면 + 서버)
       · 서버가 자서전을 저장하면 사진 없는 장마다 삽화를 저절로 만든다 (memoir_illust_service.py).
         여기서는 그 결과를 받아 해당 장 · 문단 뒤에 그린다. 고르거나 승인하는 버튼은 없다.
       · GET /api/memoirs/saved/{id}/illustrations → {status, chapters:[{no, state, figures:[{kind, url, after_paragraph, …}]}]}
         status 가 running 이면 몇 초마다 다시 받아, 새 그림이 생기면 책 · 초안을 다시 그린다.
       · 사진은 /api/photos/{id}, 삽화는 /api/memoirs/saved/{id}/illustrations/{장} — 둘 다 이 서버를 지나 로그인한 주인에게만.
       · 자리는 장 번호 + 문단 번호다. 이 기기에서 글을 고친 책(문단이 장과 이어지지 않는다)에는 그리지 않는다.
       · 그림은 미리 크기(가로:세로)를 잡아 둔다 — 그림이 늦게 와도 쪽 나눔이 흔들리지 않는다.
     ═══════════════════════════════════════════════════════════════ */
  const POLL_MS = 5000, POLL_MAX = 60;       // 5초마다 · 5분까지 (그 뒤에는 책을 다시 열 때 받는다)
  const views = new Map();                    // memoir_id → 서버 응답
  let polling = null;

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const base = () => (window.Srv && window.Srv.CONFIG && window.Srv.CONFIG.apiBase) || '';
  const sig = (v) => JSON.stringify(v ? [v.status, (v.chapters || []).map((c) => [c.no, c.state, (c.figures || []).map((f) => f.url)])] : null);

  /** 이 문단 뒤에 놓을 그림들 (section = service-contract 의 문단 정보 {chapterNo, paragraphIndex}) */
  function figuresFor(memoirId, section) {
    const v = memoirId && views.get(memoirId);
    if (!v || !section || !Number.isInteger(section.chapterNo) || !Number.isInteger(section.paragraphIndex)) return [];
    const ch = (v.chapters || []).find((c) => c.no === section.chapterNo);
    return ch ? (ch.figures || []).filter((f) => f.after_paragraph === section.paragraphIndex) : [];
  }

  function figureHTML(f) {
    const w = Number(f.width) > 0 ? Number(f.width) : 5, h = Number(f.height) > 0 ? Number(f.height) : 4;
    const ai = f.kind === 'illustration';
    const alt = ai ? `AI가 그린 그림${f.scene_title ? ` — ${f.scene_title}` : ''}` : '이 이야기의 사진';
    return `<figure class="mf-figure ${ai ? 'mf-illustration' : 'mf-photo'}" style="--mf-ratio:${w} / ${h}">`
      + `<img src="${esc(base() + f.url)}" alt="${esc(alt)}" width="${w}" height="${h}" decoding="async" draggable="false">`
      + (ai ? `<figcaption>${esc(f.caption || 'AI가 그린 그림')}</figcaption>` : '') + '</figure>';
  }

  /** 문단 하나 뒤에 붙일 HTML. 그릴 것이 없으면 빈 글 */
  function html(memoirId, section) {
    return figuresFor(memoirId, section).map(figureHTML).join('');
  }

  async function load(memoirId) {
    if (!memoirId || !window.Srv || !window.Srv.call) return null;
    try {
      const v = await window.Srv.call(`/memoirs/saved/${encodeURIComponent(memoirId)}/illustrations`);
      const changed = sig(v) !== sig(views.get(memoirId));
      views.set(memoirId, v);
      if (changed) window.dispatchEvent(new CustomEvent('memoir:figures', {detail: {memoirId, status: v.status}}));
      return v;
    } catch (_) { return views.get(memoirId) || null; }   // 그림을 못 받아도 책은 그대로 읽힌다
  }

  function stop() { if (polling) { clearTimeout(polling.timer); polling = null; } }

  /** 책 · 초안을 펼칠 때 부른다. 만드는 중이면 끝날 때까지(5분) 다시 받는다 */
  async function watch(memoirId) {
    if (!memoirId) { stop(); return; }
    if (polling && polling.id === memoirId) return;
    stop();
    const me = polling = {id: memoirId, n: 0, timer: null};
    const tick = async () => {
      if (polling !== me) return;
      const v = await load(memoirId);
      if (polling !== me) return;
      if (v && v.status === 'running' && ++me.n < POLL_MAX) me.timer = setTimeout(tick, POLL_MS);
      else stop();
    };
    await tick();
  }

  /* ── 초안 화면 — 문단(<p>) 뒤에 그림을 붙이고, 그리는 중이면 한 줄 알린다 ── */
  function decorateDraft() {
    const body = document.getElementById('draft-body');
    if (!body || typeof state === 'undefined') return;
    const id = state.savedMemoirId, sections = state.document && state.document.sections;
    [...body.children].filter((el) => el.tagName === 'P').forEach((p, i) => {
      const extra = html(id, sections && sections[i]);
      if (extra) p.insertAdjacentHTML('afterend', extra);
    });
    const v = id && views.get(id);
    if (!v || (state.document && state.document.edited)) return;
    if (v.status === 'running') {
      body.insertAdjacentHTML('afterbegin', '<div class="mf-note" role="status">사진이 없는 장에 넣을 그림을 그리고 있어요. 다 그려지면 이 자리에 저절로 들어가요.</div>');
      return;
    }
    // 그림을 넣지 못한 장은 숨기지 않고 알린다 — 본문은 그대로다
    const why = {failed: '그림을 만들지 못했어요', held: '민감한 내용이 있어 그리지 않았어요', photo_unknown: '사진 정보를 확인하지 못했어요'};
    const missed = (v.chapters || []).filter((c) => why[c.state]);
    if (missed.length) {
      body.insertAdjacentHTML('afterbegin', `<div class="mf-note mf-missed" role="status">그림을 넣지 못한 장이 있어요 — ${missed.map((c) => `${c.no}장(${why[c.state]})`).join(', ')}. 글은 그대로 읽을 수 있어요.</div>`);
    }
  }
  if (typeof window.renderDraft === 'function') {
    const renderDraftOriginal = window.renderDraft;
    window.renderDraft = function () { renderDraftOriginal(); decorateDraft(); };
  }
  window.addEventListener('memoir:figures', () => {
    const reading = document.getElementById('draft-reading');
    if (location.hash === '#draft' && reading && !reading.hidden) window.renderDraft();
  });

  // 책 · 초안 화면에 들어오면 지금 책의 그림을 받는다. 다른 화면으로 가면 그만 받는다
  window.addEventListener('memoir:screen', (e) => {
    const screen = e.detail && e.detail.screen;
    if ((screen === 'reader' || screen === 'draft') && typeof state !== 'undefined') void watch(state.savedMemoirId);
    else stop();
  });

  window.MemoirFigures = {html, figuresFor, load, watch, stop, views};
}());
