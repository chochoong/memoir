(function () {
  'use strict';
  // 자서전 나누기 — 책을 다른 사람이 읽을 수 있게 링크로 공유한다.
  //  · 처음에는 링크가 없다. 「공유 링크 만들기」에서 기간(7일 · 30일 · 기한 없이)과 PDF 내려받기 허용을 고른 뒤 만든다.
  //  · 받는 분은 읽기만 할 수 있다(고치기 · 지우기 · 책갈피 없음). 언제든 「공유 그만하기」로 링크를 끈다.
  //  · 책장 · 읽기 화면 독서 메뉴 두 곳에서 연다. 공유 중인 책에는 「공유 중」 표시.
  const lib = window.MemoirLibrary, share = window.MemoirShare;
  const shelf = document.querySelector('[data-screen="library"]');
  if (!lib || !share || !shelf) return;
  // 서버 연결 (014): POST /api/shares {book_id, book} → {share_id, url} · GET /api/shares · POST /api/shares/{id}/revoke
  //  · 링크 주소(토큰)는 만들 때 한 번만 온다 → 이 브라우저에 기억해 둔다 (localStorage 'memoir.shares', v0.54 와 같은 자리).
  //  · 서버 공유에는 기간 · PDF 허용 설정이 없다 — 끌 때까지 열리고, 받는 분은 읽기만 한다.
  const {api, call} = window.Srv;
  const shares = new Map(); // 책 id → {ids: [share_id…], link}
  const URLS = 'memoir.shares';
  const urlMap = () => { try { return JSON.parse(localStorage.getItem(URLS) || '{}') || {}; } catch { return {}; } };
  const urlKeep = (id, url) => { try { const m = urlMap(); m[id] = url; localStorage.setItem(URLS, JSON.stringify(m)); } catch {} };
  async function loadShares() {
    try {
      const r = await call('/shares?limit=100');
      const m = urlMap();
      shares.clear();
      ((r && r.shares) || []).filter((x) => x.live && x.book_id).forEach((x) => {
        const s = shares.get(x.book_id) || {ids: [], link: ''};
        s.ids.push(x.share_id);
        if (!s.link && m[x.share_id]) s.link = m[x.share_id];
        shares.set(x.book_id, s);
      });
      mark();
    } catch (_) { /* 표시만 못 한다 */ }
  }
  /** 책 → 공유할 책 모양 {title, chapters:[{title, paras:[[문장…]…]}]} */
  function bookBody(book) {
    const doc = book.document, secs = (doc && doc.sections) || [];
    const chapters = [];
    if (secs.some((x) => x.chapterTitle)) {
      secs.forEach((x) => {
        let ch = chapters[chapters.length - 1];
        if (!ch || ch.no !== x.chapterNo) { ch = {no: x.chapterNo, title: x.chapterTitle || '', paras: []}; chapters.push(ch); }
        ch.paras.push((x.sentences || [{text: x.text}]).map((t) => t.text).filter(Boolean));
      });
    } else chapters.push({title: book.title, paras: (doc ? doc.body : book.body).map((t) => [t])});
    return {title: book.title, made: book.date || '', chapters: chapters.map(({title, paras}) => ({title, paras}))};
  }
  const elderName = () => { try { return window.RolePreview.store.snapshot().elders.find((e) => e.elder_id === currentElderId())?.name || '나'; } catch { return '나'; } };

  function coverArt(id) {
    const li = shelf.querySelector(`[data-library-book="${CSS.escape(id)}"]`);
    const c = li ? getComputedStyle(li.querySelector('.ml-cover')).getPropertyValue('--ml-cover-color').trim() : '#5f1d2c';
    return `<span class="share-mini-cover" style="--c:${c || '#5f1d2c'}"></span>`;
  }
  function opts(id) {
    const book = lib.getBook(id), s = shares.get(id), who = elderName();
    const mine = who === '나';
    return {
      kind: 'book', eyebrow: '자서전 나누기', title: book.title,
      card: {kicker: '내말싸미 · 자서전', title: `${mine ? '' : window.Srv.honor(who) + '의 '}「${book.title}」`, sub: `이야기 ${book.body.length}편 · 링크를 누르면 바로 읽어요`, art: coverArt(id)},
      message: mine ? `제 이야기를 엮은 자서전 「${book.title}」을 나눠요. 링크를 누르면 휴대폰이나 컴퓨터에서 바로 읽을 수 있어요.`
        : `${window.Srv.honor(who)}의 이야기를 엮은 자서전 「${book.title}」을 나눠요. 링크를 누르면 휴대폰이나 컴퓨터에서 바로 읽을 수 있어요.`,
      link: s.link,
      status: '공유 중 · 읽기만 · 「공유 그만하기」를 누를 때까지 열려요',
      note: '책에는 가족 이야기와 이름이 담겨 있어요. 믿을 수 있는 분에게만 보내 주세요.',
      extras: [
        {label: '받는 분이 보는 화면 미리보기', icon: 'book', onClick: () => preview(id)},
        {label: 'PDF 파일로 보내기', icon: 'download', onClick: () => { share.close(); window.MemoirPdf?.open(window.MemoirPdf.bookFrom(book.title, book.document?.body || book.body, book.document?.sections, book.date)); }},
        {label: '공유 그만하기', icon: 'close', className: 'share-stop', onClick: () => stop(id)},
      ],
    };
  }
  function setupStep(id, again) {
    return () => {
      const box = document.createElement('div');
      box.className = 'share-setup-box';
      box.innerHTML = `<p class="share-setup-lead">${again ? '이 책은 이미 공유 중이에요. 링크 주소는 만들 때 한 번만 보여 드려서, 이 기기에서는 다시 볼 수 없어요. 새 링크를 만들거나 공유를 그만할 수 있어요.' : '링크를 받은 분은 이 책을 <b>읽기만</b> 할 수 있어요. 고치거나 지울 수 없고, 언제든 공유를 그만할 수 있어요.'}</p>
        <button type="button" class="button primary share-create">${icons('arrow')}<span>${again ? '새 공유 링크 만들기' : '공유 링크 만들기'}</span></button>
        ${again ? `<button type="button" class="text-button share-stop-old">${icons('close')}<span>공유 그만하기</span></button>` : ''}
        <p class="share-note">책에는 가족 이야기와 이름이 담겨 있어요. 믿을 수 있는 분에게만 보내 주세요.</p>
        <button type="button" class="text-button share-pdf-only">${icons('download')}<span>링크 없이 PDF 파일로만 저장하기</span></button>`;
      box.querySelector('.share-pdf-only').addEventListener('click', () => { const book = lib.getBook(id); share.close(); window.MemoirPdf?.open(window.MemoirPdf.bookFrom(book.title, book.document?.body || book.body, book.document?.sections, book.date)); });
      box.querySelector('.share-stop-old')?.addEventListener('click', () => stop(id));
      const make = box.querySelector('.share-create');
      make.addEventListener('click', async () => {
        if (make.disabled) return;
        make.disabled = true; make.querySelector('span').textContent = '링크를 만드는 중…';
        try {
          const book = await window.SrvLibrary.ensure(id);
          if (!book) throw new Error('no book');
          const r = await call('/shares', {method: 'POST', body: JSON.stringify({book_id: id, book: bookBody(book)})});
          urlKeep(r.share_id, r.url);
          const s = shares.get(id) || {ids: [], link: ''};
          s.ids.push(r.share_id); s.link = r.url;
          shares.set(id, s);
          mark();
          share.refill(opts(id));
          share.setStatus('공유 링크를 만들었어요. 아래에서 보낼 방법을 골라 주세요.');
        } catch (e) {
          make.disabled = false; make.querySelector('span').textContent = again ? '새 공유 링크 만들기' : '공유 링크 만들기';
          share.setStatus(e && e.status === 400 ? '책이 너무 크거나 모양이 맞지 않아 공유하지 못했어요.' : '공유 링크를 만들지 못했어요. 잠시 뒤 다시 눌러 주세요.');
        }
      });
      return box;
    };
  }
  async function openFor(id) {
    const book = await window.SrvLibrary.ensure(id);
    if (!book) return;
    if (shares.has(id) && shares.get(id).link) share.open(opts(id));
    else share.open({kind: 'book', eyebrow: '자서전 나누기', title: book.title, card: {kicker: '', title: '', sub: ''}, message: '', setup: setupStep(id, shares.has(id))});
  }
  async function stop(id) {
    const title = lib.getBook(id)?.title || '';
    share.close();
    const ok = await window.MemoirTrash.confirm({title: '공유를 그만할까요?', items: [title], desc: '이미 보낸 링크도 더 이상 열리지 않아요. 나중에 다시 공유하면 새 링크가 만들어져요. 책은 그대로 남아요.', ok: '공유 그만하기'});
    if (!ok) { openFor(id); return; }
    const s = shares.get(id);
    let failed = 0;
    for (const sid of (s ? s.ids : [])) { try { await call(`/shares/${encodeURIComponent(sid)}/revoke`, {method: 'POST'}); } catch (e) { if (e.status !== 404) failed++; } }
    if (failed) { toast('공유를 끄지 못했어요. 잠시 뒤 다시 해 주세요.'); return; }
    shares.delete(id); mark();
    toast('공유를 그만했어요. 보낸 링크는 이제 열리지 않아요.');
  }

  // ── 책장: 책마다 「공유」 + 공유 중 표시 ──
  function mark() {
    shelf.querySelectorAll('.ml-books > li').forEach((li) => {
      const id = li.querySelector('[data-library-book]')?.dataset.libraryBook;
      if (!id) return;
      let row = li.querySelector('.ml-actions');
      if (!row) { row = document.createElement('div'); row.className = 'ml-actions'; li.append(row); }
      if (!row.querySelector('.ml-share')) {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'text-button ml-share'; b.dataset.bookShare = id;
        b.innerHTML = `${icons('share')}<span>공유</span>`;
        b.setAttribute('aria-label', `「${lib.getBook(id)?.title || ''}」 공유`);
        row.prepend(b);
      }
      const label = li.querySelector('.ml-volume-label');
      const chip = label?.querySelector('.ms-on');
      if (shares.has(id) && label && !chip) label.insertAdjacentHTML('beforeend', '<span class="ms-on">공유 중</span>');
      if (!shares.has(id)) chip?.remove();
    });
  }
  new MutationObserver(mark).observe(shelf, {childList: true, subtree: true});
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-book-share]');
    if (!b || !shelf.contains(b) || shelf.classList.contains('ml-selecting')) return;
    e.preventDefault(); e.stopImmediatePropagation();
    openFor(b.dataset.bookShare);
  }, true);

  // 책을 지우면 공유도 끝난다(되돌리면 다시 이어진다)
  const removeBooks = lib.removeBooks, restoreBooks = lib.restoreBooks;
  // 책을 지우면 공유도 끈다 — 서버에서 지울 때(되돌리기 시간이 지난 뒤) 같이 끈다
  lib.removeBooks = (ids) => { const r = removeBooks(ids); r.forEach((x) => { x.share = shares.get(x.book.id); shares.delete(x.book.id); }); return r; };
  const removeSaved = window.SrvLibrary.removeSaved;
  window.SrvLibrary.removeSaved = async (books) => {
    const failed = await removeSaved(books);
    for (const b of books) if (!failed.includes(b)) {
      try { const r = await call('/shares?limit=100'); for (const x of ((r && r.shares) || []).filter((y) => y.live && y.book_id === b.id)) await call(`/shares/${encodeURIComponent(x.share_id)}/revoke`, {method: 'POST'}).catch(() => {}); } catch (_) {}
    }
    return failed;
  };
  lib.restoreBooks = (r) => { r.forEach((x) => { if (x.share) shares.set(x.book.id, x.share); }); restoreBooks(r); mark(); };

  // ── 읽기 화면: 독서 메뉴에 「공유」 ──
  const toolbar = document.querySelector('#ebook-bottom-bar .ebook-toolbar');
  let readerBtn = null;
  if (toolbar) {
    readerBtn = document.createElement('button');
    readerBtn.id = 'ebook-share-book'; readerBtn.type = 'button';
    readerBtn.innerHTML = `${icons('share')}<span>공유</span>`;
    const pdf = toolbar.querySelector('#ebook-save-pdf');
    if (pdf) pdf.before(readerBtn); else toolbar.append(readerBtn);
    toolbar.classList.add('has-share');
    readerBtn.addEventListener('click', () => { const id = lib.findOpen(); if (id) openFor(id); });
  }

  // ── 받는 분이 보는 화면 미리보기 ──
  const banner = document.createElement('div');
  banner.className = 'share-guest-banner'; banner.hidden = true;
  banner.innerHTML = `<span><b>받는 분에게 보이는 모습</b> · <span class="sgb-who"></span> 나눠 준 자서전 · 읽기만 할 수 있어요</span><button type="button">미리보기 끝내기</button>`;
  document.body.append(banner);
  function preview(id) {
    share.close();
    const s = shares.get(id);
    document.body.classList.add('share-guest-view');
    document.body.classList.toggle('share-guest-nopdf', false);
    banner.querySelector('.sgb-who').textContent = elderName() === '나' ? '「나」님이' : `${window.Srv.honor(elderName())}의 가족이`;
    banner.hidden = false;
    if (location.hash === '#reader' && lib.findOpen() === id) return;
    lib.openBook(id);
  }
  function endPreview() {
    document.body.classList.remove('share-guest-view', 'share-guest-nopdf');
    banner.hidden = true;
  }
  banner.querySelector('button').addEventListener('click', () => { endPreview(); document.getElementById('ebook-exit')?.click(); });
  window.addEventListener('memoir:screen', (e) => {
    if (e.detail.screen !== 'reader') endPreview();
    if (readerBtn && e.detail.screen === 'reader') readerBtn.hidden = !lib.findOpen();
  });

  mark();
  window.addEventListener('memoir:screen', (e) => { if (e.detail.screen === 'library') void loadShares(); });
  window.MemoirBookShare = {open: openFor, isShared: (id) => shares.has(id)};
}());
