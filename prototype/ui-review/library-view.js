(function () {
  'use strict';

  // Review-only bookshelf. Memoir text lives in this tab's memory, never storage.
  const screen = document.querySelector('[data-screen="library"]');
  if (!screen) return;
  const model = window.MemoirReaderState;
  const contract = window.MemoirServiceContract;

  const books = [
    {id:'volume-1', title:'그 시절의 골목, 오래 남은 마음', date:'2026. 10. 28.', style:'plain', body:[...initialBody], sample:true},
    {id:'volume-2', title:'우리 집 밥상에 모인 마음', date:'2026. 10. 25.', style:'essay', sample:true, body:[
      '일요일 아침이면 아버지는 식탁에 수저를 놓고, 어머니는 마지막 국그릇을 들고 오셨다. 나는 창가 자리에 앉아 김이 오르는 밥을 바라보았다. 별다른 반찬이 없는 날에도 네 사람이 둘러앉으면 식탁은 가득 찬 것 같았다.',
      '동생이 먼 곳으로 이사를 가기 전날, 우리는 평소보다 오래 저녁을 먹었다. 어머니는 잘 지내라는 말 대신 좋아하던 반찬을 한 번 더 건네셨다. 지금도 그 반찬을 만들면 말없이 서로를 챙기던 작은 식탁이 떠오른다.'
    ]},
    {id:'volume-3', title:'작은 가게의 첫 아침', date:'2026. 10. 21.', style:'plain', sample:true, body:[
      '가게 문을 처음 열던 날, 나는 셔터를 반쯤 올렸다가 다시 내렸다. 유리문에 남은 손자국이 마음에 걸려서였다. 깨끗한 행주로 문을 닦고 간판 불을 켜니, 그제야 이 작은 자리가 내 일터라는 실감이 났다.',
      '첫 손님은 길 건너 꽃집 아주머니였다. 천천히 하면 된다는 말과 함께 작은 화분 하나를 놓고 가셨다. 장사가 서툰 날에는 그 화분에 물을 주며 숨을 골랐다. 일을 배운다는 것은 물건을 파는 법뿐 아니라 사람을 맞이하는 마음도 배우는 일이었다.'
    ]}
  ];
  books.forEach(book=>{
    book.elder_id='preview-self';
    book.document=contract.memoirView({status:'ready',title:book.title,body:book.body.join('\n'),style:'spoken',sources:[],verification:{state:'not_run'}},
      {elder_id:book.elder_id,uiStyle:book.style,preview:true});
  });
  function currentBooks(){return books.filter(book=>book.elder_id===currentElderId());}
  let nextId = 4;
  const narrow = window.matchMedia('(max-width: 360px)');
  const mobile = window.matchMedia('(max-width: 760px)');
  const wide = window.matchMedia('(min-width: 1360px)');

  function shelfColumns() {
    return narrow.matches ? 1 : mobile.matches ? 2 : wide.matches ? 4 : 3;
  }

  function readingLabel(book) {
    try {
      const sections = book.body.filter((paragraph) => paragraph.trim());
      const saved = JSON.parse(localStorage.getItem(model.progressPrefix + model.bookKey(book.title, sections)));
      return model.hasResumableProgress(saved, sections) ? '이어 읽기' : '읽기';
    } catch {
      return '읽기';
    }
  }

  function bookMarkup(book, index) {
    return `<li><button type="button" class="ml-book-card ml-tone-${index % 3}" data-library-book="${escapeText(book.id)}">
      <span class="ml-cover-bay" aria-hidden="true"><span class="ml-cover"><span class="ml-cover-title">${escapeText(book.title)}</span><span class="ml-cover-rule"></span><span class="ml-cover-volume">${String(index + 1).padStart(2, '0')}</span></span></span>
      <span class="ml-book-copy"><span class="ml-volume-label">작은 책 ${String(index + 1).padStart(2, '0')}${book.sample ? '<span class="ml-sample-label">가상 예시</span>' : '<span class="ml-sample-label">미리보기</span>'}</span><strong>${escapeText(book.title)}</strong><span class="ml-book-meta">이야기 ${book.body.length}개 · ${escapeText(book.date)}</span><span class="ml-read-label">${readingLabel(book)} <span aria-hidden="true">→</span></span></span>
    </button></li>`;
  }

  function shelfMarkup() {
    const visibleBooks=currentBooks();
    const columns = shelfColumns();
    let rows = '';
    for (let start = 0; start < visibleBooks.length; start += columns) {
      rows += `<div class="ml-shelf-row"><ul class="ml-books" aria-label="책장 ${Math.floor(start / columns) + 1}번째 칸">${visibleBooks.slice(start, start + columns).map((book, index) => bookMarkup(book, start + index)).join('')}</ul><span class="ml-shelf-plank" aria-hidden="true"></span></div>`;
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
      <div class="ml-shelf-heading"><h2>모아둔 작은 책 <span>${currentBooks().length}권</span></h2><p>${currentElderId()==='preview-self'?'처음 3권은 화면 확인을 위한 가상 예시예요.':'이분의 이야기를 담은 작은 책이 모이는 곳이에요.'}</p></div>
      ${shelfMarkup()}
      <p class="ml-collection-note">얇은 책이 쌓이면, 언젠가 두툼한 한 권의 이야기로.</p>
      <p class="ml-memory-note">이번 미리보기에서 모은 책은 새로고침하면 초기화돼요.</p>`;
    if (focusedId) screen.querySelector(`[data-library-book="${focusedId}"]`)?.focus({preventScroll:true});
  }

  function openBook(id) {
    const book = books.find((item) => item.id === id);
    if (!book||book.elder_id!==currentElderId()||!book.document.canRead) return;
    state.document=contract.editMemoir(book.document,{title:book.title,body:book.document.body});
    state.title = state.document.title;
    state.body = [...state.document.body];
    state.style = book.style;
    state.draftElderId=book.elder_id;
    state.spread = 0;
    navigate('reader');
  }

  function saveDraft() {
    const title = String(state.title || '').trim();
    const body = bodyCopy(state.body);
    if (!title || !body.length) { toast('제목과 이야기를 적은 뒤 모아주세요.'); return; }
    const elderId=state.draftElderId||currentElderId();
    if(elderId!==currentElderId()||(state.document&&state.document.elder_id!==elderId)){
      toast('이 초안의 이야기 주인공을 다시 선택해 주세요.');return;
    }
    const original=state.document||contract.memoirView({status:'ready',title,body:body.join('\n'),style:'spoken',sources:[]},
      {elder_id:elderId,uiStyle:state.style,preview:true});
    if(!original.canRead){toast('아직 책으로 열 수 없는 결과예요.');return;}
    const document=contract.editMemoir(original,{title,body});
    document.uiStyle=state.style;
    const existing = books.find((book) => book.elder_id===elderId && book.title === title && JSON.stringify(book.body) === JSON.stringify(body));
    if (existing) {
      existing.style = state.style;
      existing.document=document;
    } else {
      books.push({id:`volume-${nextId++}`, elder_id:elderId, title, body, document, style:state.style, date:'오늘', sample:false});
    }
    render();
    navigate('library');
    toast('이번 미리보기의 책장에 모았어요. 서버에는 저장되지 않아요.');
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

  window.MemoirLibrary = {render, saveDraft, openBook};
  if (location.hash === '#library') render();
}());
