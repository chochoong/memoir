(function () {
  'use strict';

  // Review-only bookshelf. Memoir text lives in this tab's memory, never storage.
  const screen = document.querySelector('[data-screen="library"]');
  if (!screen) return;
  const model = window.MemoirReaderState;
  const contract = window.MemoirServiceContract;

  // 책은 서버(GET /api/memoirs/saved)에서 온다 — srv-memoir 가 setBooks 로 채운다
  const books = [];
  function currentBooks(){return books.filter(book=>book.elder_id===currentElderId());}
  let nextId = 4;
  const narrow = window.matchMedia('(max-width: 360px)');
  const mobile = window.matchMedia('(max-width: 760px)');
  const wide = window.matchMedia('(min-width: 1360px)');

  function shelfColumns() {
    return narrow.matches ? 1 : mobile.matches ? 2 : wide.matches ? 4 : 3;
  }

  function readingLabel(book) {
    if (!book.body || !book.body.length) return '읽기';
    try {
      const sections = book.body.filter((paragraph) => paragraph.trim());
      const saved = JSON.parse(localStorage.getItem(model.progressPrefix + model.bookKey(book.title, sections)));
      return model.hasResumableProgress(saved, sections) ? '이어 읽기' : '읽기';
    } catch {
      return '읽기';
    }
  }

  // 표지 색은 문체를 따른다 — 소설체 · 문학체 · 수필체가 늘 같은 색이라 책장만 봐도 어떤 책인지 안다.
  // 같은 문체 책이 이어지면 두 번째마다 조금 밝은 색(…b)으로 — 같은 색이 나란히 붙어 단조롭지 않게.
  // 색 자체는 library-view.css · library-pull.css 의 .ml-tone-* 에 있다.
  const STYLE_TONE = {novel: 0, literary: 1, essay: 2};
  function toneOf(book, index, list) {
    const base = STYLE_TONE[book.style];
    if (base === undefined) return String(index % 3); // 예전 문체(구어체 등) — 순서대로
    const nth = list.slice(0, index).filter((b) => b.style === book.style).length;
    return nth % 2 ? `${base}b` : String(base);
  }
  function bookMarkup(book, index, list) {
    return `<li><button type="button" class="ml-book-card ml-tone-${toneOf(book, index, list)}" data-library-book="${escapeText(book.id)}">
      <span class="ml-cover-bay" aria-hidden="true"><span class="ml-cover"><span class="ml-cover-title">${escapeText(book.title)}</span><span class="ml-cover-rule"></span><span class="ml-cover-volume">${String(index + 1).padStart(2, '0')}</span></span></span>
      <span class="ml-book-copy"><span class="ml-volume-label">작은 책 ${String(index + 1).padStart(2, '0')}</span><strong>${escapeText(book.title)}</strong><span class="ml-book-meta">이야기 ${book.count || book.body.length}개 · ${escapeText(book.date)}</span><span class="ml-read-label">${readingLabel(book)} <span aria-hidden="true">→</span></span></span>
    </button></li>`;
  }

  function shelfMarkup() {
    const visibleBooks=currentBooks();
    const columns = shelfColumns();
    let rows = '';
    for (let start = 0; start < visibleBooks.length; start += columns) {
      rows += `<div class="ml-shelf-row"><ul class="ml-books" aria-label="책장 ${Math.floor(start / columns) + 1}번째 칸">${visibleBooks.slice(start, start + columns).map((book, index) => bookMarkup(book, start + index, visibleBooks)).join('')}</ul><span class="ml-shelf-plank" aria-hidden="true"></span></div>`;
    }
    return `<div class="ml-shelves ml-columns-${columns}" role="group" aria-label="나의 자서전 책장">${rows}</div>`;
  }

  function bodyCopy(value) {
    return Array.isArray(value) ? value.map((paragraph) => String(paragraph)).filter(paragraph=>paragraph.trim()) : [];
  }

  function render() {
    const focusedId = document.activeElement?.closest('[data-library-book]')?.dataset.libraryBook;
    let content = screen.querySelector('.memoir-library-content');
    if (!content) {
      content = document.createElement('div');
      content.className = 'memoir-library-content';
      screen.append(content);
    }
    content.innerHTML = `
      <div class="ml-shelf-heading"><h2>모아둔 작은 책 <span>${currentBooks().length}권</span></h2><p>${currentBooks().length?'이야기를 담은 작은 책이 모이는 곳이에요.':'아직 엮은 책이 없어요. 엽서보기에서 엽서를 골라 첫 책을 만들어 보세요.'}</p></div>
      ${shelfMarkup()}
      <p class="ml-collection-note">얇은 책이 쌓이면, 언젠가 두툼한 한 권의 이야기로.</p>`;
    if (focusedId) screen.querySelector(`[data-library-book="${focusedId}"]`)?.focus({preventScroll:true});
  }

  async function openBook(id) {
    const book = await window.SrvLibrary.ensure(id);
    if (!book||book.elder_id!==currentElderId()||!book.document||!book.document.canRead) return;
    state.savedMemoirId = book.id; state.draftKept = true;
    state.document=contract.editMemoir(book.document,{title:book.title,body:book.document.body});
    state.title = state.document.title;
    state.body = [...state.document.body];
    state.style = book.style;
    state.draftElderId=book.elder_id;
    state.spread = 0;
    navigate('reader');
  }

  // 「작은 책으로 보관하기」 — 서버는 만들 때 이미 보관했다(memoir_id). 여기서는 책장에 꽂는다
  function saveDraft() {
    const id = state.savedMemoirId;
    if (!id) { toast('서버에 보관된 자서전이 아니에요. 다시 만들어 주세요.'); return; }
    if ((state.draftElderId||currentElderId()) !== currentElderId()) { toast('이 초안의 이야기 주인공을 다시 선택해 주세요.'); return; }
    const title = String(state.title || '').trim(), body = bodyCopy(state.body);
    if (!title || !body.length) { toast('제목과 이야기를 적은 뒤 모아주세요.'); return; }
    state.draftKept = true;
    if (state.document && state.document.edited) window.SrvLibrary.writeEdit(id, {title, body});
    const existing = books.find((book) => book.id === id);
    if (existing) { existing.document = state.document; existing.title = title; existing.body = [...body]; existing.style = state.style; }
    else {
      const d = new Date();
      books.push({id, elder_id: currentElderId(), title, body: [...body], document: state.document, style: state.style, server: true,
        count: (state.document?.sourceResult?.run?.session_ids || []).length || body.length, date: `${d.getFullYear()}. ${d.getMonth() + 1}. ${d.getDate()}.`});
    }
    render();
    navigate('library');
    toast(state.document && state.document.edited ? '책장에 꽂았어요. 고친 글은 이 기기에서만 보여요.' : '책장에 꽂았어요.');
  }

  screen.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.libraryBook) openBook(button.dataset.libraryBook);
  });
  window.addEventListener('memoir:screen', (event) => {
    if (event.detail.screen === 'library') render();
  });
  [narrow, mobile, wide].forEach((query) => query.addEventListener('change', render));

  // 책 지우기(되돌리기용으로 지운 자리를 함께 돌려준다)
  function removeBooks(ids) {
    const removed = [];
    ids.forEach((id) => { const index = books.findIndex((book) => book.id === id && book.elder_id === currentElderId()); if (index >= 0) removed.push({index, book: books[index]}); });
    removed.sort((a, b) => b.index - a.index).forEach(({index}) => books.splice(index, 1));
    render();
    return removed;
  }
  function restoreBooks(removed) {
    [...removed].sort((a, b) => a.index - b.index).forEach(({index, book}) => books.splice(Math.min(index, books.length), 0, book));
    render();
  }
  function setBooks(list) { books.splice(0, books.length, ...list); if (location.hash === '#library') render(); }
  window.MemoirLibrary = {render, saveDraft, setBooks, openBook, getBook:(id)=>currentBooks().find((book)=>book.id===id), removeBooks, restoreBooks, bookIds:()=>currentBooks().map((book)=>book.id),
    // 지금 읽기 화면에 펼친 책이 책장의 어느 책인지(초안을 미리 읽는 중이면 없음)
    findOpen:()=>{const list=currentBooks().filter((book)=>book.title===state.title);return (list.find((book)=>JSON.stringify(book.document?.body||book.body)===JSON.stringify(state.body))||list[0])?.id||null;}};
  if (location.hash === '#library') render();
}());
