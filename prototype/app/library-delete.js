(function () {
  'use strict';
  // 자서전(책장)에서도 엽서와 같은 규칙으로 지운다:
  //  · 책마다 「책 지우기」  · 「여러 권 지우기」로 골라서 한 번에  · 늘 한 번 더 묻고, 지운 뒤 잠시 「되돌리기」
  //  책을 지워도 그 책을 만든 엽서는 그대로 남는다.
  const shelf = document.querySelector('[data-screen="library"]');
  if (!shelf) return;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const DESC = '책장에서 사라지고 다시 읽을 수 없어요. 이 책을 만든 엽서는 그대로 남아 있어서, 같은 엽서로 다시 엮을 수 있어요.';
  let selecting = false;
  const picked = new Set();
  let bar = null;

  const titleOf = (id) => window.MemoirLibrary.getBook(id)?.title || '이 책';
  const liOf = (id) => shelf.querySelector(`[data-library-book="${CSS.escape(id)}"]`)?.closest('li');

  function decorate() {
    const heading = shelf.querySelector('.ml-shelf-heading');
    if (heading && !heading.querySelector('.ml-select-toggle')) {
      const t = document.createElement('button');
      t.type = 'button'; t.className = 'button outline compact ml-select-toggle';
      t.innerHTML = `${icons('check')}<span>여러 권 지우기</span>`;
      t.addEventListener('click', () => setSelecting(!selecting));
      heading.append(t);
    }
    shelf.querySelectorAll('.ml-books > li').forEach((li) => {
      const id = li.querySelector('[data-library-book]')?.dataset.libraryBook;
      if (!id || li.querySelector('.ml-remove')) return;
      let row = li.querySelector('.ml-actions');
      if (!row) { row = document.createElement('div'); row.className = 'ml-actions'; li.append(row); }
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'text-button ml-remove'; b.dataset.bookRemove = id;
      b.innerHTML = `${icons('close')}<span>책 지우기</span>`;
      b.setAttribute('aria-label', `「${titleOf(id)}」 책 지우기`);
      row.append(b);
    });
    sync();
  }
  new MutationObserver(decorate).observe(shelf, {childList: true, subtree: true});

  function sync() {
    const ids = window.MemoirLibrary?.bookIds?.() || [];
    [...picked].forEach((id) => { if (!ids.includes(id)) picked.delete(id); });
    shelf.classList.toggle('ml-selecting', selecting);
    const t = shelf.querySelector('.ml-select-toggle');
    if (t) { t.hidden = !ids.length; t.setAttribute('aria-pressed', String(selecting)); }
    shelf.querySelectorAll('[data-library-book]').forEach((card) => {
      const on = picked.has(card.dataset.libraryBook);
      card.closest('li')?.classList.toggle('is-picked', on);
      if (selecting) card.setAttribute('aria-pressed', String(on)); else card.removeAttribute('aria-pressed');
    });
    if (selecting) ensureBar().update(picked.size, ids.length);
  }
  function ensureBar() {
    if (bar) return bar;
    bar = window.MemoirTrash.selectBar({unit: '책', counter: '권', empty: '지울 책을 눌러 골라 주세요',
      onAll: () => { const ids = window.MemoirLibrary.bookIds(); const all = ids.every((id) => picked.has(id)); ids.forEach((id) => all ? picked.delete(id) : picked.add(id)); sync(); },
      onCancel: () => setSelecting(false),
      onDelete: removePicked});
    return bar;
  }
  function setSelecting(on) {
    selecting = on; picked.clear();
    if (on) { ensureBar().show(); window.MemoirTrash.clearUndo(); } else bar?.hide();
    sync();
    if (on) shelf.querySelector('[data-library-book]')?.focus({preventScroll: true});
  }

  // 책장에서 빼내 치우는 연출 — 책이 위로 빠졌다가 옅어진다
  async function liftOut(ids) {
    if (reduce.matches) return;
    await Promise.all(ids.map((id, i) => {
      const cover = liOf(id)?.querySelector('.ml-cover');
      const copy = liOf(id)?.querySelector('.ml-book-copy');
      copy?.animate([{opacity: 1}, {opacity: 0}], {duration: 260, delay: i * 80, fill: 'forwards'});
      return cover ? cover.animate([
        {transform: 'none', opacity: 1},
        {transform: 'translateY(-34px) rotate(-3deg)', opacity: 1, offset: .4},
        {transform: 'translate(40px, -60px) rotate(9deg) scale(.8)', opacity: 0}
      ], {duration: 520, delay: i * 80, easing: 'cubic-bezier(.4,0,.7,.4)', fill: 'forwards'}).finished : null;
    }));
  }
  function commit(ids) {
    const removed = window.MemoirLibrary.removeBooks(ids);
    if (!removed.length) return;
    shelf.querySelector('.ml-shelf-heading h2')?.setAttribute('tabindex', '-1');
    shelf.querySelector('.ml-shelf-heading h2')?.focus({preventScroll: true});
    const msg = removed.length === 1 ? `「${removed[0].book.title}」 책을 지웠어요.` : `책 ${removed.length}권을 지웠어요.`;
    // 서버에서 지우기(DELETE /api/memoirs/saved/{id})는 되돌리기 시간이 지난 뒤 — 실패한 책은 다시 꽂는다
    const commitServer = async () => {
      const failed = await window.SrvLibrary.removeSaved(removed.map((x) => x.book));
      if (!failed.length) return;
      window.MemoirLibrary.restoreBooks(removed.filter((x) => failed.includes(x.book)));
      toast(failed.length === 1 ? '책을 지우지 못했어요. 잠시 뒤 다시 해 주세요.' : `책 ${failed.length}권을 지우지 못했어요. 잠시 뒤 다시 해 주세요.`);
    };
    window.MemoirTrash.undo(msg, () => {
      window.MemoirLibrary.restoreBooks(removed);
      const back = removed.map(({book}) => liOf(book.id)).filter(Boolean);
      if (!reduce.matches) back.forEach((li, i) => li.querySelector('.ml-cover')?.animate([{transform: 'translateY(-40px)', opacity: 0}, {transform: 'none', opacity: 1}], {duration: 380, delay: i * 70, easing: 'ease-out', fill: 'backwards'}));
      back[0]?.querySelector('[data-library-book]')?.focus({preventScroll: true});
      toast(removed.length === 1 ? '책을 책장에 다시 꽂았어요.' : `책 ${removed.length}권을 책장에 다시 꽂았어요.`);
    }, commitServer);
  }
  async function removeOne(id) {
    const ok = await window.MemoirTrash.confirm({title: '이 책을 지울까요?', items: [titleOf(id)], desc: DESC, ok: '지우기'});
    if (!ok) { shelf.querySelector(`[data-book-remove="${CSS.escape(id)}"]`)?.focus(); return; }
    await liftOut([id]);
    commit([id]);
  }
  async function removePicked() {
    const ids = [...picked];
    if (!ids.length) return;
    const ok = await window.MemoirTrash.confirm({title: `책 ${ids.length}권을 지울까요?`, items: ids.map(titleOf), desc: DESC, ok: `${ids.length}권 지우기`});
    if (!ok) return;
    bar?.hide();
    await liftOut(ids);
    selecting = false; picked.clear();
    commit(ids);
    sync();
  }

  // 고르는 중에는 책을 눌러도 펼치지 않고 고른다(책 꺼내기 연출보다 먼저 받는다)
  document.addEventListener('click', (e) => {
    const rm = e.target.closest('[data-book-remove]');
    if (rm && shelf.contains(rm)) { e.preventDefault(); e.stopImmediatePropagation(); if (!selecting) removeOne(rm.dataset.bookRemove); return; }
    if (!selecting) return;
    const card = e.target.closest('[data-library-book]');
    if (!card || !shelf.contains(card)) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const id = card.dataset.libraryBook;
    if (picked.has(id)) picked.delete(id); else picked.add(id);
    sync();
  }, true);
  window.addEventListener('memoir:screen', (e) => { if (selecting && e.detail.screen !== 'library') setSelecting(false); });
  document.addEventListener('keydown', (e) => { if (selecting && e.key === 'Escape' && !document.querySelector('dialog[open]')) setSelecting(false); });

  // ── 읽기 화면의 독서 메뉴에도 「책 지우기」 ──
  //    지우면 책을 덮어 책장에 돌려놓은 뒤(꺼내기 연출의 반대), 책장에서 빼내 치운다. 초안을 미리 읽는 중에는 보이지 않는다.
  const toolbar = document.querySelector('#ebook-bottom-bar .ebook-toolbar');
  let readerBtn = null;
  if (toolbar) {
    readerBtn = document.createElement('button');
    readerBtn.id = 'ebook-remove-book'; readerBtn.type = 'button';
    readerBtn.innerHTML = `${icons('close')}<span>책 지우기</span>`;
    toolbar.append(readerBtn);
    toolbar.classList.add('has-remove');
    readerBtn.addEventListener('click', removeFromReader);
  }
  window.addEventListener('memoir:screen', (e) => { if (readerBtn && e.detail.screen === 'reader') readerBtn.hidden = !window.MemoirLibrary.findOpen(); });
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  async function removeFromReader() {
    const id = window.MemoirLibrary.findOpen();
    if (!id) return;
    const ok = await window.MemoirTrash.confirm({title: '이 책을 지울까요?', items: [titleOf(id)], desc: DESC, ok: '지우기'});
    if (!ok) { readerBtn.focus(); return; }
    document.getElementById('ebook-exit')?.click();
    // 책이 덮여 책장에 돌아갈 때까지 기다린다
    for (let t = 0; t < 40; t++) { await wait(100); if (location.hash === '#library' && !document.querySelector('.lp-host')) break; if (t === 8 && location.hash !== '#library') navigate('library'); }
    await wait(150);
    await liftOut([id]);
    commit([id]);
  }
  decorate();
}());
