(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     photo-edit — 완성된 자서전의 「사진 편집」 (v1.24 PC 목차 · 휴대폰 알약 탭 · v1.18 장 탭 · v1.17 · 업무지시서 「자서전 사진 추가 · 이동 · 삭제」 · 서버 계약 9-C1)
       · 들어가기: 책 읽기 화면 독서 메뉴 「사진 편집」, 초안 화면 「사진 편집」 → 편집 모드(전체 화면 창)
       · 장 탭(v1.18): 책마다 원고의 장으로 탭이 저절로 생긴다. 고른 장의 문단만 보이고, 탭에 그 장의 그림 수.
         이동 · 넣기 자리를 고르는 중에도 탭을 바꿔 다른 장으로 옮길 수 있다. 장이 하나뿐이면 탭을 그리지 않는다.
       · 추가: 문단마다 「+ 사진 추가」 → 사진 여러 장 고르기 → 미리보기(고른 순서) → 한 장씩 차례로 올리며 배치
               POST /api/memoirs/saved/{id}/photos?chapter_no=&after_paragraph=&display_order=&request_id= (본문 = 사진 바이트).
               책에 넣지 못한 사진은 같은 주소에 JSON {photo_id, …}. 사진마다 request_id 를 붙여 다시 보내도 한 장만.
       · AI 삽화는 옮기거나 빼지 않는다(서버: origin ai · placement_id null) — 단추 대신 안내만.
       · 이동: 사진의 「이동」 → 다른 장 · 문단의 「여기로 옮기기」 → PATCH …/photos/{placement_id}
       · 끌어서 옮기기(v1.21): 사진(자동 · 넣은 사진 · 넣지 못한 사진)을 끌어 문단 아래 원하는 차례에 놓는다. 마우스는 사진 어디든,
         손가락은 사진 위 「끌기」 손잡이로(화면 밀기와 헷갈리지 않게). 장 탭(또는 「N장으로」)에 잠깐 대고 있으면 그 장이 열린다.
         같은 문단 안 차례는 display_order 하나로 맞추고, 틈이 없으면 그 문단 사진 차례를 0,1,2… 로 다시 매긴다(PATCH 여러 번).
         AI 그림은 서버가 옮기지 않으므로 끌 수 없다. 키보드 · 화면 읽기는 지금처럼 「이동」 단추.
       · 화면 (v1.24): PC = 머리(설명) + 왼쪽 세로 목차, 목차 맨 아래 「편집 마치기」. 휴대폰 = 위 알약 탭(고정), 설명은 내용과 함께
         스크롤, 「편집 마치기」는 장 맨 끝. 이전 · 다음 장 단추는 없다. 휴대폰에서 사진을 끄는 동안 탭 줄이 커진다(52 → 88px).
       · 탭에 놓기(v1.22): 장 탭(또는 「N장으로」) 위에서 손을 떼면 그 장 「1번째 문단 아래 맨 앞」으로(서버는 문단 아래에만 놓는다).
         그 장을 열어 옮긴 사진을 잠깐 노랗게 보여 주고, 아래 띠 「되돌리기」로 원래 자리 · 차례로 되돌린다(PATCH 한 번).
         넣지 못한 사진을 탭에 놓은 경우는 되돌리기 대신 안내만 — 빼면 다시 「넣지 못한 사진」으로 돌아오는지 서버 확인 전이라.
       · 삭제: 사진의 「삭제」 → 확인 → DELETE …/photos/{placement_id} (그 자서전에서만 · 엽서는 그대로)
       · 교체(다른 파일로 바꾸기)는 이번 범위가 아니다 — 메뉴를 만들지 않는다.
       · 자리 = 장 번호 + 그 장의 문단 번호(0부터, 서버 after_paragraph). 화면 말은 「1장 2번째 문단 아래」.
         읽기 화면과 같은 문단 정보(document.sections)를 쓴다. 문단을 셀 수 없으면 저장하지 않고 알린다.
       · 요청마다 서버 상태를 다시 받아(SrvLibrary.refreshArrange) 그린다. 실패하면 화면은 그대로, 오류 문구 + 다시 시도.
         요청 중에는 모든 단추를 막는다(두 번 눌림 방지).
       · 서버가 아직 사진 편집을 받지 않으면(그림에 origin 칸 없음) 창은 보기만 — 꾸며서 성공처럼 보이지 않는다.
     ═══════════════════════════════════════════════════════════════ */
  const S = window.Srv, lib = window.SrvLibrary;
  if (!S || !S.api || !S.api.memoirPhotoAdd || !lib || !lib.arrangeInfo) return;
  const MAX_FILES = 10, MAX_MB = 20, MAX_BOOK = 30;   // 책 한 권에 넣은 사진 30장 (서버 MEMOIR_PHOTOS_MAX)
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const icon = (n) => `<svg class="icon" aria-hidden="true"><use href="#i-${n}"/></svg>`;
  const toast = (m, ms = 3600) => { const t = document.getElementById('toast'); if (!t) return; t.textContent = m; t.hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, ms); };
  const spot = (ch, para) => `${ch}장 ${para + 1}번째 문단 아래`;
  const REASON = () => (window.MemoirUnplaced && window.MemoirUnplaced.REASON) || {};
  // 서버 9-C1 의 실패 갈래 → 화면 말. 서버 detail 은 「화면에 보일 말」이라 모르는 갈래면 그대로 쓴다
  const errText = (e) => {
    if (!e) return '알 수 없는 문제가 생겼어요.';
    const say = {
      memoir_not_found: '이 자서전을 찾을 수 없어요. 책장에서 다시 열어 주세요.',
      placement_not_found: '그 사진을 찾을 수 없어요. 이미 빠졌을 수 있어요 — 화면을 새로 받아 올게요.',
      photo_not_found: '그 사진을 찾을 수 없어요.',
      bad_position: '그 자리에는 사진을 넣을 수 없어요. 다른 문단을 골라 주세요.',
      no_such_chapter: '그 장을 찾을 수 없어요. 화면을 새로 받아 올게요.',
      no_such_paragraph: '그 문단을 찾을 수 없어요. 다른 문단을 골라 주세요.',
      too_many_photos: `책 한 권에 넣을 수 있는 사진은 ${MAX_BOOK}장까지예요. 다른 사진을 빼고 넣어 주세요.`,
      photo_not_stored: '아직 다 올라가지 않은 사진이에요. 잠시 뒤 다시 해 주세요.',
    }[e.code];
    if (say) return say;
    if (e.status === 413) return '사진이 너무 커요. 다른 사진을 골라 주세요.';
    if (e.status === 400) return '이 사진은 넣을 수 없어요. 다른 사진을 골라 주세요.';
    if (e.status === 401) return '로그인이 풀렸어요. 다시 로그인해 주세요.';
    if (e.status === 404) return '서버가 아직 사진 편집을 받지 않아요. 잠시 뒤 다시 해 주세요.';
    if (e.status === 422 && e.message) return e.message;
    return '연결이 잠시 끊겼어요. 다시 시도해 주세요.';
  };
  const newRequestId = () => (window.crypto && crypto.randomUUID ? crypto.randomUUID() : 'r' + Date.now().toString(36) + Math.random().toString(36).slice(2));

  // ── 편집 창 ──
  // v1.24: PC 는 머리(설명) + 왼쪽 목차(맨 아래 「편집 마치기」). 휴대폰은 머리를 숨기고 같은 설명을 내용 맨 위(.pe-intro)에 —
  //        내용과 함께 스크롤되고, 「편집 마치기」는 장 맨 끝(.pe-end). 어느 쪽이 보일지는 CSS(760px)가 정한다
  const HELP = '문단 아래 <b>「+ 사진 추가」</b>로 사진을 넣고, 사진을 <b>끌어서</b> 옮기거나 <b>「이동」 · 「삭제」</b>로 고칠 수 있어요. 고친 내용은 바로 저장돼요.';
  const DONE = `<button type="button" class="button primary pe-done" data-pe="close">${icon('check')}<span>편집 마치기</span></button>`;
  const isPhone = () => window.matchMedia('(max-width: 760px)').matches;
  const dlg = document.createElement('dialog');
  dlg.id = 'photo-edit'; dlg.className = 'pe-dialog';
  dlg.setAttribute('aria-labelledby', 'pe-title');
  dlg.innerHTML = `
    <header class="pe-head">
      <div><span class="eyebrow">자서전 꾸미기</span><h2 id="pe-title" tabindex="-1">사진 편집</h2>
      <p class="pe-help">${HELP}</p></div>
    </header>
    <div class="pe-tabbar"><div class="pe-tablist"></div><div class="pe-side-foot">${DONE}</div></div>
    <div class="pe-banner" role="status" aria-live="polite" hidden></div>
    <div class="pe-body"></div>
    <div class="pe-undo" role="status" aria-live="polite" hidden><span class="pe-undotext"></span><button type="button" class="button outline" data-pe="undo" hidden>되돌리기</button></div>
    <div class="pe-movebar" hidden><span class="pe-movetext"></span><button type="button" class="button outline" data-pe="cancel-move">옮기지 않기</button></div>
    <input type="file" class="pe-file" accept="image/*" multiple hidden>`;
  document.body.append(dlg);
  const $ = (q) => dlg.querySelector(q);

  // ── 미리보기 · 확인 창 ──
  const sheet = document.createElement('dialog');
  sheet.id = 'photo-edit-sheet'; sheet.className = 'review-dialog pe-sheet';
  sheet.setAttribute('aria-labelledby', 'pe-sheet-title');
  document.body.append(sheet);

  let cur = null;  // {id, doc, info, mode: null|{kind:'move', fig}|{kind:'place', u}, busy}
  let drag = null, noClickUntil = 0;   // 끌기를 마친 손을 떼며 생기는 누르기는 흘려보낸다 // 끌어서 옮기기: {kind:'f'|'u', id, pid, x0, y0, on, ghost, at:{ch, para, k}|null, spring}
  const thumbs = new Map();

  function chapters(doc) {
    const out = [];
    (doc.sections || []).forEach((s) => {
      if (!Number.isInteger(s.chapterNo) || !Number.isInteger(s.paragraphIndex)) return;
      let c = out.find((x) => x.no === s.chapterNo);
      if (!c) { c = {no: s.chapterNo, title: s.chapterTitle || '', paras: []}; out.push(c); }
      c.paras.push({i: s.paragraphIndex, text: s.text});
    });
    return out;
  }
  const validSpot = (ch, para) => chapters(cur.doc).some((c) => c.no === ch && c.paras.some((p) => p.i === para));
  const figLabel = (f) => (f.ai || f.origin === 'ai' ? 'AI가 그린 그림' : f.origin === 'manual' ? '내가 넣은 사진' : '이야기 사진');

  const canDrag = () => cur.info.editable && !cur.busy && !cur.mode;
  const grip = (kind, id) => `<span class="pe-grip" data-pe-drag="${kind}:${esc(id)}" aria-hidden="true"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><g fill="currentColor" stroke="none"><circle cx="9" cy="6" r="1.7"/><circle cx="15" cy="6" r="1.7"/><circle cx="9" cy="12" r="1.7"/><circle cx="15" cy="12" r="1.7"/><circle cx="9" cy="18" r="1.7"/><circle cx="15" cy="18" r="1.7"/></g></svg>끌기</span>`;
  function figHTML(f) {
    const moving = cur.mode && cur.mode.kind === 'move' && cur.mode.fig.id === f.id;
    const can = cur.info.editable && f.id && !cur.busy;
    const dr = !f.ai && f.id && canDrag();
    const dragging = drag && drag.on && drag.kind === 'f' && drag.id === f.id;
    const just = cur.just && cur.just.id === f.id && Date.now() < cur.just.until;
    return `<figure class="pe-fig ${f.ai ? 'is-ai' : ''} ${moving ? 'is-moving' : ''} ${just ? 'is-just' : ''} ${dr ? 'can-drag' : ''} ${dragging ? 'is-dragging' : ''}" ${f.ai || !f.id ? '' : `data-pe-fid="${esc(f.id)}"`}>
      <span class="pe-thumb" data-pe-src="${esc(f.url)}" ${dr ? `data-pe-drag="f:${esc(f.id)}"` : ''}><img alt="${esc(figLabel(f))}" draggable="false">${dr ? grip('f', f.id) : ''}</span>
      <figcaption>${esc(figLabel(f))}${moving ? ' · 옮기는 중' : ''}</figcaption>
      ${f.ai || !f.id ? '<span class="pe-fixed">AI 그림은 이번에 옮기거나 뺄 수 없어요</span>' : `<span class="pe-ctl">
        <button type="button" class="pe-btn" data-pe-move="${esc(f.id)}" ${can && !cur.mode ? '' : 'disabled'}>${icon('arrow')}<span>이동</span></button>
        <button type="button" class="pe-btn is-del" data-pe-del="${esc(f.id)}" ${can && !cur.mode ? '' : 'disabled'}>${icon('close')}<span>삭제</span></button>
      </span>`}</figure>`;
  }
  function paraHTML(c, p) {
    const here = cur.info.server.filter((f) => f.ch === c.no && f.para === p.i);
    const ed = cur.info.editable && !cur.busy;
    let act;
    if (cur.mode && cur.mode.kind === 'move') {
      const same = cur.mode.fig.ch === c.no && cur.mode.fig.para === p.i;
      act = `<button type="button" class="pe-slot is-target" data-pe-to="${c.no}:${p.i}" ${same || !ed ? 'disabled' : ''}>${icon('arrow')}${same ? '지금 자리예요' : '여기로 옮기기'}</button>`;
    } else if (cur.mode && cur.mode.kind === 'place') {
      act = `<button type="button" class="pe-slot is-target" data-pe-put="${c.no}:${p.i}" ${ed ? '' : 'disabled'}>${icon('plus')}여기에 넣기</button>`;
    } else {
      act = `<button type="button" class="pe-slot" data-pe-add="${c.no}:${p.i}" ${ed ? '' : 'disabled'} aria-label="${esc(spot(c.no, p.i))}에 사진 추가">${icon('plus')}사진 추가</button>`;
    }
    return `<div class="pe-para" data-pe-para="${c.no}:${p.i}"><span class="pe-where">${p.i + 1}번째 문단</span><p>${esc(p.text)}</p>
      ${here.length ? `<div class="pe-here">${here.map(figHTML).join('')}</div>` : ''}${act}</div>`;
  }
  function render() {
    const unplaced = cur.info.unplaced.filter((u) => u.url);
    const top = !cur.info.editable
      ? '<div class="pe-note is-warn">서버에 사진 편집 기능이 아직 연결되지 않았어요. 지금은 사진을 볼 수만 있어요.</div>'
      : unplaced.length ? `<section class="pe-unplaced"><h3>책에 넣지 못한 사진 ${unplaced.length}장</h3><p>넣을 자리를 고르거나 사진을 끌어 문단에 놓으면 그 문단 아래에 들어가요. <button type="button" class="text-button" data-pe="why">넣지 못한 까닭 보기</button></p>
        <div class="pe-here">${unplaced.map((u) => `<figure class="pe-fig ${cur.mode && cur.mode.kind === 'place' && cur.mode.u.id === u.id ? 'is-moving' : ''} ${canDrag() ? 'can-drag' : ''} ${drag && drag.on && drag.kind === 'u' && drag.id === u.id ? 'is-dragging' : ''}"><span class="pe-thumb" data-pe-src="${esc(u.url)}" ${canDrag() ? `data-pe-drag="u:${esc(u.id)}"` : ''}><img alt="책에 넣지 못한 사진" draggable="false">${canDrag() ? grip('u', u.id) : ''}</span>
          <figcaption>${esc((REASON()[u.reason] || {}).title || '책에 넣지 못한 사진')}</figcaption>
          <span class="pe-ctl"><button type="button" class="pe-btn" data-pe-place="${esc(u.id)}" ${cur.mode || cur.busy ? 'disabled' : ''}>${icon('plus')}<span>넣을 자리 고르기</span></button></span></figure>`).join('')}</div></section>` : '';
    // 장 탭 — 책마다 원고의 장(document.sections 의 chapterNo · chapterTitle)으로 저절로 나뉜다. 고른 장의 문단만 보인다
    const chs = chapters(cur.doc);
    if (!chs.some((c) => c.no === cur.tab)) cur.tab = chs[0].no;
    const count = (no) => cur.info.server.filter((f) => f.ch === no).length;
    const tabs = `<div class="pe-tabs" role="tablist" aria-label="장 고르기">${chs.map((c) => {
      const on = c.no === cur.tab, n = count(c.no), from = cur.mode && cur.mode.kind === 'move' && cur.mode.fig.ch === c.no;
      return `<button type="button" role="tab" class="pe-tab${on ? ' is-on' : ''}${from ? ' is-from' : ''}" id="pe-tab-${c.no}" data-pe-tab="${c.no}" aria-selected="${on}" aria-controls="pe-panel" tabindex="${on ? 0 : -1}" title="${esc(c.title)}" aria-label="${c.no}장 ${esc(c.title)}${n ? ` · 그림 ${n}장` : ''}">`
        + `<span class="pe-tab-no">${c.no}장</span><span class="pe-tab-title">${esc(c.title)}</span>${n ? `<span class="pe-tab-n" aria-hidden="true">${n}</span>` : ''}</button>`;
    }).join('')}</div>`;
    const c = chs.find((x) => x.no === cur.tab);
    const body = `<section class="pe-ch" id="pe-panel" role="tabpanel" aria-labelledby="pe-tab-${c.no}"><h3><span>${c.no}장</span>${esc(c.title)}</h3>${c.paras.map((p) => paraHTML(c, p)).join('')}<div class="pe-end">${DONE}</div></section>`;
    const intro = `<div class="pe-intro"><span class="eyebrow">자서전 꾸미기</span><h2 class="pe-intro-title" tabindex="-1">사진 편집</h2><p class="pe-help">${HELP}</p></div>`;
    // 장 목록은 스크롤 칸 밖 — PC 왼쪽 목차 / 휴대폰 위 알약 탭 (장이 하나뿐이면 휴대폰은 탭을 숨긴다)
    $('.pe-tablist').innerHTML = tabs; $('.pe-tabbar').classList.toggle('is-single', chs.length < 2);
    $('.pe-body').innerHTML = intro + top + body;
    $('.pe-body').classList.toggle('is-choosing', !!cur.mode);
    const mb = $('.pe-movebar');
    mb.hidden = !cur.mode;
    if (cur.mode) undoBar('');
    if (cur.mode) $('.pe-movetext').textContent = cur.mode.kind === 'move'
      ? `「${spot(cur.mode.fig.ch, cur.mode.fig.para)}」의 ${figLabel(cur.mode.fig)}을 옮길 자리를 고르세요 · 다른 장은 ${isPhone() ? '위 탭' : '왼쪽 목차'}에서`
      : `넣지 못한 사진을 넣을 문단 아래 「여기에 넣기」를 누르세요 · 다른 장은 ${isPhone() ? '위 탭' : '왼쪽 목차'}에서`;
    dlg.querySelectorAll('.pe-done').forEach((b) => { b.disabled = !!cur.busy; });
    dlg.classList.toggle('is-busy', !!cur.busy);
    fillThumbs(dlg);
  }
  function fillThumbs(root) {
    const P = window.MemoirPostcardPhoto;
    root.querySelectorAll('[data-pe-src]').forEach((box) => {
      const img = box.querySelector('img'); const k = box.dataset.peSrc;
      if (thumbs.has(k)) { img.src = thumbs.get(k); return; }
      if (!P || !P.srcPath) return;
      P.srcPath(k).then((u) => { if (u) { thumbs.set(k, u); img.src = u; } else box.classList.add('is-empty'); });
    });
  }
  function banner(text, retry) {
    const b = $('.pe-banner');
    if (!text) { b.hidden = true; b.innerHTML = ''; return; }
    b.hidden = false; b.className = 'pe-banner' + (retry ? ' is-error' : '');
    b.innerHTML = `<span>${esc(text)}</span>${retry ? '<button type="button" class="button outline" data-pe="retry">다시 시도</button>' : ''}`;
    banner.retry = retry || null;
  }

  // ── 한 번의 서버 요청: 막고 → 보내고 → 다시 받고 → 그린다. 실패하면 그대로 두고 알린다 ──
  async function run(label, fn, done) {
    if (cur.busy) return false;
    undoBar('');   // 다른 일을 하면 앞선 「되돌리기」는 닫는다
    cur.busy = label; banner(`${label} 중…`); render();
    try {
      await fn();
    } catch (e) {
      cur.busy = null; cur.mode = null; render();
      banner(`${label}에 실패했어요. 화면은 그대로예요. ${errText(e)}`, () => run(label, fn, done));
      if (e && e.code === 'placement_not_found') void reload();
      return false;
    }
    try { await reload(); } catch (_) { /* 바꾼 것은 저장됐다 — 다음에 받을 때 맞춰진다 */ }
    cur.busy = null; cur.mode = null; banner(''); render();
    if (done) toast(done);
    return true;
  }
  async function reload() { await lib.refreshArrange(cur.id, cur.doc); cur.info = lib.arrangeInfo(cur.id); }

  // ── 열기 ──
  async function open(id, doc) {
    if (!id) { toast('자서전을 먼저 만들어 주세요.'); return; }
    if (!doc || doc.edited || !chapters(doc).length) { toast('이 기기에서 글을 고친 자서전은 문단 자리를 셀 수 없어 사진을 편집할 수 없어요.'); return; }
    cur = {id, doc, info: lib.arrangeInfo(id), mode: null, busy: null, tab: null};
    undoBar('');
    if (!cur.info.loaded) {
      try { await reload(); } catch (e) { toast(`사진을 불러오지 못했어요. ${errText(e)}`); cur = null; return; }
    }
    banner(''); render();
    dlg.showModal(); (isPhone() ? $('.pe-intro-title') : $('#pe-title')).focus();
  }

  // ── 추가: 고르기 → 미리보기 → 차례로 올리기 ──
  let addAt = null;
  function pickFiles(ch, para) {
    if (!validSpot(ch, para)) { banner('이 문단의 자리를 셀 수 없어 사진을 넣을 수 없어요. 다른 문단을 골라 주세요.', null); return; }
    addAt = {ch, para}; $('.pe-file').click();
  }
  function preview(files) {
    const here = cur.info.server.filter((f) => f.ch === addAt.ch && f.para === addAt.para && Number.isInteger(f.order));
    const base = here.length ? Math.max(...here.map((f) => f.order)) + 1 : 0;   // 이 문단 뒤 사진들 맨 끝부터
    // request_id: 같은 사진을 다시 보내도(응답이 끊겨 다시 시도) 한 장만 들어간다 · display_order: 다시 넣어도 고른 순서 자리에
    const list = files.slice(0, MAX_FILES).map((file, k) => ({file, n: k + 1, url: URL.createObjectURL(file), st: 'wait', err: '', rid: newRequestId(), order: base + k}));
    const over = files.length > MAX_FILES;
    const room = MAX_BOOK - cur.info.server.filter((f) => f.origin === 'manual').length;
    if (room <= 0) { banner(`책 한 권에 넣을 수 있는 사진은 ${MAX_BOOK}장까지예요. 다른 사진을 빼고 넣어 주세요.`, null); list.forEach((x) => URL.revokeObjectURL(x.url)); return; }
    if (list.length > room) { list.splice(room).forEach((x) => URL.revokeObjectURL(x.url)); toast(`책 한 권에 사진은 ${MAX_BOOK}장까지라 ${room}장만 골랐어요`); }
    let running = false;   // 한 장씩 올리는 동안 — 중간에 한 장이 실패해도 끝날 때까지 단추를 막는다
    const paint = () => {
      const up = running, doneAll = list.every((x) => x.st === 'ok'), tried = list.some((x) => x.st === 'ok' || x.st === 'bad');
      const bad = list.filter((x) => x.st === 'bad'), okN = list.filter((x) => x.st === 'ok').length;
      sheet.innerHTML = `<span class="eyebrow">사진 추가</span><h2 id="pe-sheet-title" tabindex="-1">「${esc(spot(addAt.ch, addAt.para))}」에 사진 ${list.length}장</h2>
        <p class="pe-sheet-lead">${tried ? (bad.length ? `${list.length}장 가운데 ${okN}장을 넣었어요. ${bad.length}장은 넣지 못했어요.` : `${okN}장을 모두 넣었어요.`) : '고른 순서대로 이 자리에 들어가요. 확인하고 「넣기」를 눌러 주세요.'}${over ? ` (한 번에 ${MAX_FILES}장까지라 처음 ${MAX_FILES}장만 골랐어요)` : ''}</p>
        <ol class="pe-pre">${list.map((x) => `<li class="is-${x.st}"><span class="pe-n">${x.n}</span><img src="${x.url}" alt="고른 사진 ${x.n}"><span class="pe-st">${x.st === 'up' ? '<span class="sp-spin"></span>올리는 중' : x.st === 'ok' ? '넣었어요' : x.st === 'bad' ? esc(x.err) : '기다리는 중'}</span></li>`).join('')}</ol>
        <div class="dialog-actions">${doneAll ? '<button type="button" class="button primary" data-ps="close">확인</button>'
          : bad.length && !up ? `<button type="button" class="button outline" data-ps="close">닫기</button><button type="button" class="button primary" data-ps="retry">못 넣은 ${bad.length}장 다시 넣기</button>`
          : `<button type="button" class="button outline" data-ps="close" ${up ? 'disabled' : ''}>취소</button><button type="button" class="button primary" data-ps="go" ${up ? 'disabled' : ''}>${up ? '넣는 중…' : '넣기'}</button>`}</div>`;
    };
    const go = async (only) => {
      if (cur.busy || running) return;
      running = true; cur.busy = '사진 넣기'; render();
      for (const x of list.filter((y) => !only || only.includes(y))) {   // 한 장씩 차례로 — 고른 순서가 화면 순서가 된다
        x.st = 'up'; x.err = ''; paint();
        try {
          if (!/^image\//.test(x.file.type)) throw Object.assign(new Error('not image'), {status: 400});
          if (x.file.size > MAX_MB * 1048576) throw Object.assign(new Error('too big'), {status: 413});
          await S.api.memoirPhotoAdd(cur.id, {file: x.file, chapterNo: addAt.ch, afterParagraph: addAt.para, displayOrder: x.order, requestId: x.rid});
          x.st = 'ok';
        } catch (e) { x.st = 'bad'; x.err = errText(e); }
        paint();
      }
      try { await reload(); } catch (_) {}
      running = false; cur.busy = null; render(); paint();
      const okN = list.filter((y) => y.st === 'ok').length, badN = list.filter((y) => y.st === 'bad').length;
      if (!badN) toast(`「${spot(addAt.ch, addAt.para)}」에 사진 ${okN}장을 넣었어요`);
    };
    sheet.onclick = (e) => {
      const b = e.target.closest('[data-ps]'); if (!b || b.disabled) return;
      if (b.dataset.ps === 'go') void go();
      else if (b.dataset.ps === 'retry') void go(list.filter((x) => x.st === 'bad'));
      else { sheet.close(); list.forEach((x) => URL.revokeObjectURL(x.url)); }
    };
    sheet.oncancel = (e) => { if (cur.busy) e.preventDefault(); };
    paint(); sheet.showModal(); sheet.querySelector('#pe-sheet-title').focus();
  }

  // ── 삭제: 확인 → DELETE ──
  function confirmDelete(f) {
    sheet.innerHTML = `<span class="eyebrow">사진 삭제</span><h2 id="pe-sheet-title" tabindex="-1">이 ${f.ai ? '그림' : '사진'}을 자서전에서 뺄까요?</h2>
      <div class="pe-del-pic"><span class="pe-thumb" data-pe-src="${esc(f.url)}"><img alt=""></span><span>「${esc(spot(f.ch, f.para))}」</span></div>
      <p class="pe-sheet-lead">${f.ai ? '이 자서전에서만 빠져요.' : '이 자서전에서만 빠지고, 엽서와 사진 원본은 그대로 남아요.'}</p>
      <div class="dialog-actions"><button type="button" class="button outline" data-ps="no">취소</button><button type="button" class="button primary pe-danger" data-ps="yes">${icon('close')}삭제</button></div>`;
    fillThumbs(sheet);
    sheet.onclick = (e) => {
      const b = e.target.closest('[data-ps]'); if (!b) return;
      sheet.close();
      if (b.dataset.ps === 'yes') void run('사진 삭제', () => S.api.memoirPhotoDelete(cur.id, f.id), `「${spot(f.ch, f.para)}」의 ${f.ai ? '그림' : '사진'}을 자서전에서 뺐어요`);
    };
    sheet.oncancel = null;
    sheet.showModal(); sheet.querySelector('[data-ps="no"]').focus();
  }

  // ── 누르기 ──
  dlg.addEventListener('click', (e) => {
    if (Date.now() < noClickUntil) return;
    const t = e.target, act = t.closest('[data-pe]');
    if (act) {
      const a = act.dataset.pe;
      if (a === 'close' && !cur.busy) dlg.close();
      else if (a === 'cancel-move') { cur.mode = null; render(); }
      else if (a === 'undo' && undoBar.fn && !cur.busy) { const f = undoBar.fn; undoBar(''); void f(); }
      else if (a === 'retry' && banner.retry) { const r = banner.retry; banner(''); void r(); }
      else if (a === 'why' && window.MemoirUnplaced) window.MemoirUnplaced.open(cur.id);
      return;
    }
    const tb = t.closest('[data-pe-tab]');
    if (tb && !cur.busy) { showTab(Number(tb.dataset.peTab), tb.classList.contains('pe-tab')); return; }
    const b = t.closest('button'); if (!b || b.disabled || cur.busy) return;
    const pos = (v) => v.split(':').map(Number);
    if (b.dataset.peAdd) { const [ch, p] = pos(b.dataset.peAdd); pickFiles(ch, p); return; }
    if (b.dataset.peMove) { const f = cur.info.server.find((x) => x.id === b.dataset.peMove); if (f) { cur.mode = {kind: 'move', fig: f}; banner(''); render(); } return; }
    if (b.dataset.peDel) { const f = cur.info.server.find((x) => x.id === b.dataset.peDel); if (f) confirmDelete(f); return; }
    if (b.dataset.pePlace) { const u = cur.info.unplaced.find((x) => x.id === b.dataset.pePlace); if (u) { cur.mode = {kind: 'place', u}; banner(''); render(); } return; }
    if (b.dataset.peTo) {
      const [ch, p] = pos(b.dataset.peTo); const f = cur.mode.fig;
      if (!validSpot(ch, p)) { banner('그 자리를 셀 수 없어 옮기지 않았어요.', null); return; }
      void run('사진 이동', () => S.api.memoirPhotoMove(cur.id, f.id, {chapterNo: ch, afterParagraph: p}), `${f.ai ? '그림' : '사진'}을 「${spot(ch, p)}」로 옮겼어요`);
      return;
    }
    if (b.dataset.pePut) {
      const [ch, p] = pos(b.dataset.pePut); const u = cur.mode.u;
      if (!validSpot(ch, p)) { banner('그 자리를 셀 수 없어 넣지 않았어요.', null); return; }
      const rid = newRequestId();   // 다시 시도해도 같은 번호 — 한 장만 들어간다
      void run('사진 넣기', () => S.api.memoirPhotoAdd(cur.id, {photoId: u.id, chapterNo: ch, afterParagraph: p, requestId: rid}), `넣지 못한 사진을 「${spot(ch, p)}」에 넣었어요`);
    }
  });
  function showTab(no, keepFocus) {
    if (cur.tab === no) return;
    cur.tab = no; render();
    $('.pe-body').scrollTop = 0;
    const tab = $(`#pe-tab-${no}`);
    if (tab) { tab.scrollIntoView({block: 'nearest', inline: 'nearest'}); if (keepFocus) tab.focus(); }
  }
  dlg.addEventListener('keydown', (e) => {
    if (!cur || !e.target.matches('.pe-tab') || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return;   // PC 세로 목차는 ↑↓ 도
    e.preventDefault();
    const nos = chapters(cur.doc).map((c) => c.no), k = nos.indexOf(Number(e.target.dataset.peTab));   // 포커스가 있는 탭 기준
    const to = e.key === 'Home' ? 0 : e.key === 'End' ? nos.length - 1 : Math.min(nos.length - 1, Math.max(0, k + (e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : -1)));
    if (!cur.busy) showTab(nos[to], true);
  });
  dlg.addEventListener('cancel', (e) => { if (cur && (cur.busy || cur.mode)) { e.preventDefault(); if (cur.mode && !cur.busy) { cur.mode = null; render(); } } });
  $('.pe-file').addEventListener('change', (e) => { const fs = [...e.target.files]; e.target.value = ''; if (fs.length && addAt) preview(fs); });

  // ── 끌어서 옮기기 (v1.21) ──
  // 한 문단의 사진 차례(서버 차례 그대로 · AI 그림 제외). 끄는 사진은 뺀다
  const paraPhotos = (ch, para, skip) => cur.info.server.filter((f) => f.ch === ch && f.para === para && !f.ai && f.id && f.id !== skip);
  const ordOf = (f, k) => (Number.isInteger(f.order) ? f.order : k);
  // k 번째(0부터)에 놓으려면: 앞뒤 사이에 빈 정수가 있으면 그 값 하나, 없으면 그 문단 차례를 0,1,2… 로 다시 매긴다
  function orderPlan(list, k) {
    const o = list.map(ordOf), prev = k > 0 ? o[k - 1] : null, next = k < o.length ? o[k] : null;
    if (next === null) return {v: o.length ? Math.max(...o) + 1 : 0, re: []};
    if (prev === null) return {v: Math.min(...o) - 1, re: []};
    if (next - prev >= 2) return {v: prev + 1, re: []};
    const re = [];
    list.forEach((f, i) => { const want = i < k ? i : i + 1; if (o[i] !== want) re.push({f, order: want}); });
    return {v: k, re};
  }
  function findDrop(x, y) {
    const el = document.elementFromPoint(x, y);
    if (!el || !dlg.contains(el)) return {tab: null, at: null};
    const tab = el.closest('[data-pe-tab]');
    if (tab) return {tab: Number(tab.dataset.peTab), at: null};
    const para = el.closest('[data-pe-para]');
    if (!para) return {tab: null, at: null};
    const [ch, p] = para.dataset.pePara.split(':').map(Number);
    const figs = [...para.querySelectorAll('.pe-fig[data-pe-fid]')].filter((f) => !(drag.kind === 'f' && f.dataset.peFid === drag.id));
    let k = figs.length;
    for (let i = 0; i < figs.length; i++) {   // 읽는 차례로: 이 사진보다 위 줄이거나, 같은 줄에서 왼쪽 절반이면 그 앞
      const r = figs[i].getBoundingClientRect();
      if (y < r.top || (y <= r.bottom && x < r.left + r.width / 2)) { k = i; break; }
    }
    return {tab: null, at: {ch, para: p, k}};
  }
  // 놓을 자리 표시 (v1.24): 내용 흐름에 끼워 넣지 않고 문단 위에 겹쳐 그린다 — 표시가 생기고 없어져도 글 · 사진이 움직이지 않아
  //   손가락 밑의 자리가 바뀌지 않는다(맨 아래까지 내린 상태에서 화면이 밀리던 문제). 사진 사이 = 노란 줄, 사진이 없으면 「+ 사진 추가」 칸 위에 상자
  function showMark(at) {
    dlg.querySelectorAll('.pe-drop-mark').forEach((m) => m.remove());
    dlg.querySelectorAll('.pe-para.is-drop').forEach((m) => m.classList.remove('is-drop'));
    if (!at) return;
    const para = dlg.querySelector(`[data-pe-para="${at.ch}:${at.para}"]`); if (!para) return;
    para.classList.add('is-drop');
    const mark = document.createElement('span'); mark.className = 'pe-drop-mark'; mark.setAttribute('aria-hidden', 'true');
    const same = isSame(at);
    mark.innerHTML = `<b>${same ? '지금 자리' : `여기에 놓기 · ${at.k + 1}번째`}</b>`;
    mark.classList.toggle('is-same', same);
    const figs = [...para.querySelectorAll('.pe-fig[data-pe-fid]')].filter((f) => !(drag.kind === 'f' && f.dataset.peFid === drag.id));
    const P = para.getBoundingClientRect(), box = (r) => ({l: r.left - P.left, t: r.top - P.top, w: r.width, h: r.height});
    const wide = (r) => r.width > P.width * 0.6;   // 휴대폰처럼 사진이 한 줄에 하나면 가로 줄, 여러 장이면 세로 줄
    let st;
    if (!figs.length) {
      const sl = box(para.querySelector('.pe-slot').getBoundingClientRect());
      mark.classList.add('is-box'); st = {left: sl.l, top: sl.t, width: sl.w, height: sl.h};
    } else {
      const ref = figs[Math.min(at.k, figs.length - 1)], r = box(ref.getBoundingClientRect()), before = at.k < figs.length;
      if (wide(ref.getBoundingClientRect())) { mark.classList.add('is-h'); st = {left: r.l, width: r.w, top: (before ? r.t : r.t + r.h) - 9, height: 6}; }
      else { mark.classList.add('is-v'); st = {top: r.t, height: r.h, left: (before ? r.l : r.l + r.w) - 10, width: 6}; }
    }
    Object.entries(st).forEach(([k, v]) => { mark.style[k] = v + 'px'; });
    para.append(mark);
  }
  function isSame(at) {
    if (drag.kind !== 'f') return false;
    const f = cur.info.server.find((x) => x.id === drag.id);
    if (!f || f.ch !== at.ch || f.para !== at.para) return false;
    return paraPhotos(at.ch, at.para).findIndex((x) => x.id === f.id) === at.k;
  }
  function endDrag(drop) {
    const d = drag; drag = null;
    clearTimeout(d.spring && d.spring.t); clearInterval(d.scroll);
    if (d.ghost) d.ghost.remove();
    dlg.classList.remove('is-dragging', 'is-overtab');
    try { dlg.releasePointerCapture(d.pid); } catch (_) {}
    if (!d.on) return;
    d.on = false;
    if (drop && d.at && !isSameFor(d, d.at)) { void dropAt(d, d.at); return; }
    if (drop && !d.at && Number.isInteger(d.overTab)) { dropOnTab(d, d.overTab); return; }
    render();
  }
  // 탭에 놓기 — 그 장 1번째 문단 아래 맨 앞
  function dropOnTab(d, no) {
    const c = chapters(cur.doc).find((x) => x.no === no);
    if (!c || !c.paras.length) { render(); return; }
    const at = {ch: no, para: c.paras[0].i, k: 0};
    if (isSameFor(d, at)) { cur.tab = no; render(); undoBar(`이미 「${no}장 1번째 문단 아래」 맨 앞이에요`); return; }
    void dropAt(d, at, {tab: true});
  }
  // 아래 띠: 알림 + (있으면) 되돌리기. 10초 뒤 저절로 닫힌다
  function undoBar(text, undo) {
    const u = $('.pe-undo'); clearTimeout(undoBar.t);
    if (!text) { u.hidden = true; undoBar.fn = null; return; }
    u.hidden = false; $('.pe-undotext').textContent = text;
    undoBar.fn = undo || null; u.querySelector('[data-pe="undo"]').hidden = !undo;
    undoBar.t = setTimeout(() => undoBar(''), 10000);
  }
  // 방금 옮긴 사진: 그 장을 열고 잠깐 노랗게, 보이는 곳으로
  function spotlight(ch, id) {
    cur.tab = ch; cur.just = {id, until: Date.now() + 2600}; render();
    const el = dlg.querySelector(`.pe-fig[data-pe-fid="${id}"]`);
    if (el) el.scrollIntoView({block: 'center'});
    setTimeout(() => { const e = dlg.querySelector(`.pe-fig[data-pe-fid="${id}"]`); if (e) e.classList.remove('is-just'); }, 2700);
  }
  const isSameFor = (d, at) => { const keep = drag; drag = d; const r = isSame(at); drag = keep; return r; };
  async function dropAt(d, at, opt = {}) {
    if (!validSpot(at.ch, at.para)) { render(); banner('그 자리를 셀 수 없어 옮기지 않았어요.', null); return; }
    const list = paraPhotos(at.ch, at.para, d.kind === 'f' ? d.id : null);
    const plan = orderPlan(list, at.k), where = opt.tab ? `「${at.ch}장 1번째 문단 아래」 맨 앞` : `「${spot(at.ch, at.para)}」 ${at.k + 1}번째`;
    if (d.kind === 'u') {
      const rid = newRequestId(); let pid = null;
      const ok = await run('사진 넣기', async () => {
        for (const r of plan.re) await S.api.memoirPhotoMove(cur.id, r.f.id, {chapterNo: at.ch, afterParagraph: at.para, displayOrder: r.order});
        const res = await S.api.memoirPhotoAdd(cur.id, {photoId: d.id, chapterNo: at.ch, afterParagraph: at.para, displayOrder: plan.v, requestId: rid});
        pid = res && res.placement && res.placement.placement_id;
      }, opt.tab ? null : `넣지 못한 사진을 ${where}에 넣었어요`);
      if (ok && opt.tab) {
        if (pid) spotlight(at.ch, String(pid)); else { cur.tab = at.ch; render(); }
        undoBar(`넣지 못한 사진을 ${where}에 넣었어요 · 자리가 다르면 끌거나 「이동」으로 옮겨 주세요`);
      }
      return;
    }
    const was = cur.info.server.find((f) => f.id === d.id);
    const back = was && {ch: was.ch, para: was.para, order: was.order};
    const ok = await run('사진 이동', async () => {
      for (const r of plan.re) await S.api.memoirPhotoMove(cur.id, r.f.id, {chapterNo: at.ch, afterParagraph: at.para, displayOrder: r.order});
      await S.api.memoirPhotoMove(cur.id, d.id, {chapterNo: at.ch, afterParagraph: at.para, displayOrder: plan.v});
    }, opt.tab ? null : `사진을 ${where}로 옮겼어요`);
    if (!ok || !opt.tab) return;
    spotlight(at.ch, d.id);
    // 되돌리기: 원래 장 · 문단 · 차례 값으로 (탭에 놓기는 다른 사진 차례를 바꾸지 않으므로 PATCH 한 번)
    undoBar(`사진을 ${where}으로 옮겼어요`, back && Number.isInteger(back.para) ? async () => {
      const ok2 = await run('되돌리기', () => S.api.memoirPhotoMove(cur.id, d.id, Object.assign({chapterNo: back.ch, afterParagraph: back.para}, Number.isInteger(back.order) ? {displayOrder: back.order} : {})), null);
      if (ok2) { spotlight(back.ch, d.id); undoBar(`사진을 원래 자리 「${spot(back.ch, back.para)}」로 되돌렸어요`); }
    } : null);
  }
  function dragMove(x, y) {
    const d = drag;
    d.x = x; d.y = y;
    const r = findDrop(x, y);
    d.overTab = r.tab;
    const onTab = Number.isInteger(r.tab), say = onTab ? (r.tab === cur.tab ? `놓으면 ${r.tab}장 맨 앞으로` : `놓으면 ${r.tab}장 맨 앞으로 · 기다리면 ${r.tab}장이 열려요`) : '';
    // 손가락이면 끄는 사진을 손가락 위로 띄운다 — 손가락 밑의 자리 표시가 가려지지 않게.
    // 휴대폰 탭 위에서는 손가락 아래로 내리고, 안내는 탭 줄 위 글줄에 (커진 탭 글자를 가리지 않게)
    const phoneTab = d.touch && onTab && isPhone();
    dlg.classList.toggle('is-overtab', phoneTab);
    $('.pe-tabbar').dataset.msg = phoneTab ? say : '장 위에 놓으면 그 장 맨 앞으로 옮겨져요';
    d.ghost.style.transform = `translate(${x - d.gw / 2}px, ${phoneTab ? y + 60 : d.touch ? y - d.gh - 28 : y - d.gh / 2}px)`;
    // 탭 위: 놓으면 그 장 맨 앞 · 기다리면 장이 열린다 — 끄는 사진 밑에 한 줄로 알려 준다
    const tip = d.ghost.querySelector('.pe-ghost-tip');
    tip.hidden = !onTab || phoneTab;
    if (!tip.hidden) tip.textContent = say;
    // 장 탭 · 「N장으로」에 잠깐(0.6초) 대고 있으면 그 장을 연다
    if (r.tab !== null && r.tab !== cur.tab) {
      if (!d.spring || d.spring.no !== r.tab) {
        clearTimeout(d.spring && d.spring.t);
        dlg.querySelectorAll('.pe-tab.is-spring').forEach((t) => t.classList.remove('is-spring'));
        const t = dlg.querySelector(`#pe-tab-${r.tab}`); if (t) t.classList.add('is-spring');
        d.spring = {no: r.tab, t: setTimeout(() => {
          if (drag !== d) return;
          d.at = null; showTab(r.tab);
          // 열린 장의 첫 문단이 바로 보이게 — 장 머리를 창 맨 위로
          const body = dlg.querySelector('.pe-body'), pn = dlg.querySelector('#pe-panel');
          if (pn) body.scrollTop += pn.getBoundingClientRect().top - body.getBoundingClientRect().top;
          d.calm = Date.now() + 900;   // 장이 바뀐 직후에는 저절로 밀지 않는다 — 손가락이 아직 탭 근처에 있다
        }, 600)};
      }
    } else if (d.spring) { clearTimeout(d.spring.t); d.spring = null; dlg.querySelectorAll('.pe-tab.is-spring').forEach((t) => t.classList.remove('is-spring')); }
    const key = r.at ? `${r.at.ch}:${r.at.para}:${r.at.k}` : '';
    if (key !== d.key || (r.at && !dlg.querySelector('.pe-drop-mark'))) { d.key = key; d.at = r.at; showMark(r.at); }
  }
  dlg.addEventListener('pointerdown', (e) => {
    const h = e.target.closest('[data-pe-drag]');
    if (!cur || !h || drag || !canDrag() || e.button > 0) return;
    const onGrip = !!e.target.closest('.pe-grip');
    if (e.pointerType !== 'mouse' && !onGrip) return;   // 손가락은 「끌기」 손잡이에서만 — 사진 위를 밀면 화면이 움직인다
    const [kind, ...rest] = h.dataset.peDrag.split(':');
    undoBar('');
    drag = {kind, id: rest.join(':'), pid: e.pointerId, touch: e.pointerType !== 'mouse', x0: e.clientX, y0: e.clientY, on: false, el: h.closest('.pe-fig')};
    try { dlg.setPointerCapture(e.pointerId); } catch (_) {}
    if (onGrip) e.preventDefault();
  });
  dlg.addEventListener('pointermove', (e) => {
    const d = drag; if (!d || e.pointerId !== d.pid) return;
    if (!d.on) {
      if (Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 6) return;
      d.on = true;
      const src = d.el.querySelector('.pe-thumb img'), r = d.el.querySelector('.pe-thumb').getBoundingClientRect();
      d.gw = Math.min(d.touch ? 120 : 160, r.width); d.gh = d.gw * 3 / 4;
      d.ghost = document.createElement('div'); d.ghost.className = 'pe-ghost';
      d.ghost.innerHTML = '<span class="pe-ghost-tip" hidden></span>';
      d.ghost.style.width = d.gw + 'px'; d.ghost.style.height = d.gh + 'px';
      if (src && src.src) d.ghost.style.backgroundImage = `url("${src.src}")`;
      $('.pe-tabbar').dataset.msg = '장 위에 놓으면 그 장 맨 앞으로 옮겨져요';
      dlg.append(d.ghost); dlg.classList.add('is-dragging');
      d.el.classList.add('is-dragging');
      // 창 위 · 아래 가장자리에 가면 저절로 밀어 올리고 내린다
      d.scroll = setInterval(() => {
        if (drag !== d) return;
        // 장 탭 줄(스크롤 칸 밖) 위에서는 밀지 않는다 — 탭에 대고 기다리는 중. 스크롤 칸 위 가장자리 띠에서 위로 민다
        const b = dlg.querySelector('.pe-body').getBoundingClientRect(), edge = 60, top = b.top;
        if (d.y < b.top) return;
        if (d.calm && Date.now() < d.calm) return;
        const v = d.y < top + edge ? -14 : d.y > b.bottom - edge ? 14 : 0;
        if (v) { dlg.querySelector('.pe-body').scrollTop += v; dragMove(d.x, d.y); }
      }, 30);
    }
    e.preventDefault();
    dragMove(e.clientX, e.clientY);
  });
  dlg.addEventListener('pointerup', (e) => { if (drag && e.pointerId === drag.pid) { if (drag.on) noClickUntil = Date.now() + 400; endDrag(true); } });
  dlg.addEventListener('pointercancel', (e) => { if (drag && e.pointerId === drag.pid) endDrag(false); });
  dlg.addEventListener('keydown', (e) => { if (drag && drag.on && e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); endDrag(false); } }, true);

  // ── 초안 화면: 「사진 편집」 ──
  const actions = document.querySelector('[data-screen="draft"] .draft-actions');
  if (actions) {
    const btn = document.createElement('button');
    btn.type = 'button'; btn.id = 'edit-photos'; btn.className = 'button outline';
    btn.innerHTML = `${icon('photo')}<span>사진 편집</span>`;
    const read = actions.querySelector('[data-go="reader"]');
    if (read) read.before(btn); else actions.append(btn);
    const note = document.createElement('p'); note.className = 'pe-draft-note small-copy'; note.hidden = true;
    btn.after(note);
    btn.addEventListener('click', () => open(state.savedMemoirId, state.document)); // eslint-disable-line no-undef
    const paint = () => {
      const id = typeof state !== 'undefined' ? state.savedMemoirId : null; // eslint-disable-line no-undef
      const ok = id && state.document && !state.document.edited; // eslint-disable-line no-undef
      btn.disabled = !ok;
      const info = ok ? lib.arrangeInfo(id) : null;
      if (!info || !info.loaded) { note.hidden = true; return; }
      const ph = info.server.filter((f) => !f.ai).length, ai = info.server.filter((f) => f.ai).length, un = info.unplaced.filter((u) => u.url).length;
      note.textContent = [`사진 ${ph}장`, ai ? `AI 그림 ${ai}장` : '', un ? `넣지 못한 사진 ${un}장` : ''].filter(Boolean).join(' · ');
      note.hidden = false;
    };
    window.addEventListener('memoir:figures', paint);
    window.addEventListener('memoir:screen', (e) => {
      if (e.detail.screen !== 'draft') return;
      paint();
      const id = state.savedMemoirId; // eslint-disable-line no-undef
      if (id && state.document && !state.document.edited && !lib.arrangeInfo(id).loaded) void lib.loadFigures(id, state.document).then(paint); // eslint-disable-line no-undef
    });
  }

  window.MemoirPhotoEdit = {open};
}());
