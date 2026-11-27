(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     book-unplaced — 「책에 넣지 못한 사진」 안내 (v1.14)
       · 서버(develop 95b5cd9)가 GET /api/memoirs/saved/{id}/illustrations 의 unplaced_photos 로
         「이야기에 붙였지만 책의 어느 장에도 놓지 못한 사진」과 그 까닭을 알려 준다. srv-memoir 의 SrvLibrary.unplaced(id).
       · 읽기 화면: 독서 메뉴에 「넣지 못한 사진 N」 단추, 그 책을 처음 펼칠 때 한 번 짧은 알림.
       · 단추를 누르면 창: 사진(받을 수 있으면) · 쉬운 말로 된 까닭 · 어떻게 하면 되는지 · 사진 저장.
       · 서버 문구(detail)는 개발용이라 쓰지 않는다. 모르는 까닭은 일반 문구로.
       · 받는 분이 보는 화면 미리보기(share-guest-view)에서는 보이지 않는다 — 책 주인에게만 의미가 있다.
     ═══════════════════════════════════════════════════════════════ */
  const lib = window.SrvLibrary;
  const toolbar = document.querySelector('#ebook-bottom-bar .ebook-toolbar');
  if (!lib || !lib.unplaced || !toolbar) return;

  const REASON = {
    session_not_cited: {
      title: '이 이야기가 책 글에 쓰이지 않았어요',
      text: '사진을 붙인 이야기가 책의 어느 장에도 들어가지 않아서, 사진을 놓을 자리를 찾지 못했어요.',
      tip: '그 이야기를 조금 더 들려주신 뒤 책을 다시 만들면 함께 들어갈 수 있어요.',
    },
    photo_not_stored: {
      title: '사진이 끝까지 올라가지 않았어요',
      text: '사진을 올리는 도중에 끊겨서 책에 넣을 수 없었어요.',
      tip: '새 이야기를 시작할 때 사진을 다시 넣어 주세요.',
    },
    photo_missing: {
      title: '사진을 찾을 수 없어요',
      text: '사진이 지워졌거나 연결이 끊겨서 책에 넣을 수 없었어요.',
      tip: '새 이야기를 시작할 때 사진을 다시 넣어 주세요.',
    },
    photo_not_owned: {
      title: '이 계정의 사진이 아니에요',
      text: '다른 계정에서 올린 사진이라 이 책에는 넣지 않았어요.',
      tip: '이 계정으로 사진을 다시 넣어 주세요.',
    },
  };
  const OTHER = {title: '사진을 넣지 못했어요', text: '이 사진은 책에 놓을 자리를 찾지 못했어요.', tip: '책을 다시 만들면 들어갈 수 있어요.'};
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const toast = (m) => { const t = document.getElementById('toast'); if (!t) return; t.textContent = m; t.hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, 4200); };
  // 지금 펼친 책 — 책장에서 펼친 책(MemoirLibrary.findOpen) · 막 만든 책의 「책으로 미리 읽기」(app.js 의 state.savedMemoirId)
  const openId = () => {
    const L = window.MemoirLibrary;
    return (L && L.findOpen && L.findOpen()) || (typeof state !== 'undefined' && state && state.savedMemoirId) || null; // eslint-disable-line no-undef
  };

  // ── 독서 메뉴 단추 ──
  const btn = document.createElement('button');
  btn.type = 'button'; btn.id = 'ebook-unplaced'; btn.hidden = true; btn.className = 'ebook-unplaced-btn';
  btn.innerHTML = '<svg class="icon"><use href="#i-photo"/></svg><span>사진<span class="bu-word"> 편집</span><b class="bu-count"></b></span>';
  toolbar.append(btn);

  // ── 창 ──
  const dlg = document.createElement('dialog');
  dlg.id = 'unplaced-dialog'; dlg.className = 'review-dialog unplaced-dialog';
  dlg.setAttribute('aria-labelledby', 'unplaced-heading');
  dlg.innerHTML = `<form method="dialog"><button class="dialog-close" aria-label="창 닫기"><svg class="icon"><use href="#i-close"/></svg></button></form>
    <span class="eyebrow">이 책에 넣지 못한 사진</span>
    <h2 id="unplaced-heading" tabindex="-1"></h2>
    <p class="bu-lead">이야기에 붙인 사진 가운데 책에 들어가지 못한 사진이에요. 사진은 지워지지 않았어요.</p>
    <ul class="bu-list"></ul>
    <form method="dialog" class="dialog-actions"><button class="button primary">확인</button></form>`;
  document.body.append(dlg);

  function itemHTML(u, i) {
    const r = REASON[u.reason] || OTHER;
    const pic = u.url
      ? `<span class="bu-thumb" data-bu-src="${esc(u.url)}"><img alt="넣지 못한 사진 ${i + 1}"></span>`
      : `<span class="bu-thumb is-empty" aria-hidden="true"><svg class="icon"><use href="#i-photo"/></svg></span>`;
    const save = u.url ? `<button type="button" class="button outline compact bu-save" data-bu-save="${esc(u.url)}" data-bu-n="${i + 1}"><svg class="icon"><use href="#i-download"/></svg><span>사진 저장</span></button>` : '';
    return `<li class="bu-item">${pic}<div class="bu-text"><strong>${esc(r.title)}</strong><p>${esc(r.text)}</p><p class="bu-tip">${esc(r.tip)}</p>${save}</div></li>`;
  }
  function fillThumbs() {
    const P = window.MemoirPostcardPhoto;
    dlg.querySelectorAll('[data-bu-src]').forEach((box) => {
      const img = box.querySelector('img');
      if (!P || !P.srcPath) { box.classList.add('is-empty'); return; }
      P.srcPath(box.dataset.buSrc).then((url) => { if (url) img.src = url; else { img.remove(); box.classList.add('is-empty'); box.innerHTML = '<svg class="icon"><use href="#i-photo"/></svg>'; } });
    });
  }
  function openDialog(forId) {
    const list = lib.unplaced(typeof forId === 'string' ? forId : openId());
    if (!list.length) return;
    dlg.querySelector('#unplaced-heading').textContent = `사진 ${list.length}장을 책에 넣지 못했어요`;
    dlg.querySelector('.bu-list').innerHTML = list.map(itemHTML).join('');
    fillThumbs();
    dlg.showModal();
    dlg.querySelector('#unplaced-heading').focus();
  }
  // v1.16: 단추는 「사진 편집」(photo-edit.js)을 연다 (넣지 못한 사진도 그 안에서 넣는다). 까닭 창은 편집 창의 「넣지 못한 까닭 보기」로
  const docOf = (id) => { const b = window.MemoirLibrary && window.MemoirLibrary.getBook(id); return (b && b.document) || (typeof state !== 'undefined' && state.savedMemoirId === id ? state.document : null); }; // eslint-disable-line no-undef
  btn.addEventListener('click', () => { const id = openId(); if (window.MemoirPhotoEdit) window.MemoirPhotoEdit.open(id, docOf(id)); else openDialog(); });
  dlg.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-bu-save]'); if (!b) return;
    const P = window.MemoirPostcardPhoto;
    const url = P && P.srcPath ? await P.srcPath(b.dataset.buSave) : null;
    if (!url) { toast('사진을 받지 못했어요. 잠시 뒤 다시 눌러 주세요.'); return; }
    const a = document.createElement('a'); a.href = url; a.download = `넣지_못한_사진_${b.dataset.buN}.jpg`; a.click();
  });

  // ── 읽기 화면을 열 때 · 그림을 새로 받았을 때 ──
  const told = new Set(); // 이 책은 알림을 이미 띄웠다 (이번 방문 동안)
  function update() {
    const id = location.hash === '#reader' ? openId() : null;
    const list = id ? lib.unplaced(id) : [];
    const doc = id ? docOf(id) : null;
    const can = !!(doc && !doc.edited && (doc.sections || []).some((x) => Number.isInteger(x.chapterNo)));
    btn.hidden = !can;
    toolbar.classList.toggle('has-unplaced', !!list.length);
    const actionable = list.filter((u) => u.url).length; // 받을 수 있어 책에 넣을 수 있는 사진만 숫자로
    btn.querySelector('.bu-count').textContent = actionable ? String(actionable) : '';
    btn.setAttribute('aria-label', actionable ? `사진 편집 · 책에 넣지 못한 사진 ${actionable}장` : '사진 편집');
    if (list.length && !told.has(id) && !document.body.classList.contains('share-guest-view')) {
      told.add(id);
      setTimeout(() => { if (location.hash === '#reader') toast(`이 책에 넣지 못한 사진이 ${list.length}장 있어요 · 아래 「사진 편집」에서 책에 넣을 수 있어요`); }, 900);
    }
  }
  window.addEventListener('memoir:figures', update);
  window.addEventListener('memoir:screen', () => setTimeout(update, 0));
  window.addEventListener('hashchange', () => setTimeout(update, 0));

  window.MemoirUnplaced = {open: openDialog, update, REASON};
}());
