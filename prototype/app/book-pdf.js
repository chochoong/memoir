(function () {
  'use strict';
  // 4. 자서전 PDF 저장 — 읽기 화면(아래 독서 메뉴) · 초안 화면에서 연다.
  //    시안에서는 인쇄용 책 모양을 만들어 브라우저 인쇄 창을 띄우고, 거기서 「PDF로 저장」을 고르게 한다.
  //    실제 서비스에서는 서버가 같은 모양의 PDF 파일을 만들어 바로 내려받게 하는 것을 전제로 한다.
  const model = window.MemoirReaderState;
  let current = null; // {title, sections:[{title, number, text}], elder, date}

  function elderName() {
    try { return window.RolePreview.store.snapshot().elders.find((e) => e.elder_id === currentElderId())?.name || '나'; } catch { return '나'; }
  }
  function bookFrom(title, paragraphs, docSections, date) {
    const texts = paragraphs.map(String).filter((p) => p.trim());
    const sections = [];
    texts.forEach((text, i) => {
      const h = model.chapterHeading(docSections?.[i], i);
      if (h.show || !sections.length) sections.push({title: h.title, number: h.number, paras: [text]});
      else sections[sections.length - 1].paras.push(text);
    });
    return {title, sections, elder: elderName(), date: date || new Date().toLocaleDateString('ko-KR')};
  }

  // ── 고르는 창 ──
  const dialog = document.createElement('dialog');
  dialog.className = 'review-dialog pdf-dialog';
  dialog.setAttribute('aria-labelledby', 'pdf-title');
  dialog.innerHTML = `<form method="dialog"><button class="dialog-close" aria-label="닫기">${icons('close')}</button></form>
    <span class="eyebrow">자서전 PDF로 저장</span><h2 id="pdf-title"></h2>
    <div class="pdf-preview" aria-hidden="true"><div class="pdf-sheet pdf-cover"><b></b><i></i></div><div class="pdf-sheet pdf-toc"><s></s><s></s><s></s></div><div class="pdf-sheet pdf-text"><u></u><s></s><s></s><s></s><s></s></div></div>
    <form class="pdf-options">
      <fieldset><legend>종이 크기</legend><div class="pdf-seg">
        <label><input type="radio" name="size" value="A5" checked><span><b>책 크기</b><small>A5 · 손에 드는 책</small></span></label>
        <label><input type="radio" name="size" value="A4"><span><b>큰 종이</b><small>A4 · 집에서 인쇄</small></span></label></div></fieldset>
      <fieldset><legend>글자 크기</legend><div class="pdf-seg">
        <label><input type="radio" name="font" value="normal" checked><span><b>보통</b></span></label>
        <label><input type="radio" name="font" value="large"><span><b>크게</b><small>어르신께 드릴 때</small></span></label></div></fieldset>
      <label class="pdf-check"><input type="checkbox" name="toc" checked>차례 넣기</label>
      <p class="pdf-pages"></p>
      <button type="submit" class="button primary pdf-make">${icons('download')}<span>PDF 만들기</span></button>
      <p class="pdf-help">인쇄 창이 열리면 <b>대상(프린터)</b>에서 <b>「PDF로 저장」</b>을 고른 뒤 저장을 눌러 주세요.<br><small>휴대폰에서는 「공유」나 「인쇄」에서 PDF로 저장할 수 있어요.</small></p>
    </form>`;
  document.body.append(dialog);
  const opts = dialog.querySelector('.pdf-options');

  function estimate() {
    const big = opts.size.value === 'A4', large = opts.font.value === 'large';
    const chars = current.sections.reduce((n, s) => n + s.paras.join('').length, 0);
    const perPage = (big ? 1100 : 520) * (large ? 0.7 : 1);
    const body = current.sections.reduce((n, s) => n + Math.max(1, Math.ceil(s.paras.join('').length / perPage)), 0);
    const pages = 1 + (opts.toc.checked ? 1 : 0) + body + 1;
    dialog.querySelector('.pdf-pages').textContent = `이야기 ${current.sections.length}편 · 약 ${pages}쪽 (표지 · ${opts.toc.checked ? '차례 · ' : ''}맺음 쪽 포함, 글 ${chars.toLocaleString()}자)`;
  }
  opts.addEventListener('change', estimate);

  function open(book) {
    current = book;
    dialog.querySelector('#pdf-title').textContent = book.title;
    dialog.querySelector('.pdf-cover b').textContent = book.title;
    estimate();
    dialog.showModal();
  }

  // ── 인쇄용 책 ──
  const printRoot = document.createElement('div');
  printRoot.id = 'print-book';
  printRoot.setAttribute('aria-hidden', 'true');
  document.body.append(printRoot);
  const pageStyle = document.createElement('style');
  document.head.append(pageStyle);

  function build() {
    const b = current, big = opts.size.value === 'A4', large = opts.font.value === 'large';
    pageStyle.textContent = `@page { size: ${big ? 'A4' : 'A5'}; margin: ${big ? '24mm 22mm 26mm' : '18mm 16mm 20mm'}; @bottom-center { content: counter(page); font-size: 9pt; color: #9a8a76; } }
      @page :first { @bottom-center { content: none; } }`;
    printRoot.className = `pb-${big ? 'a4' : 'a5'} ${large ? 'pb-large' : ''}`;
    const toc = opts.toc.checked ? `<section class="pb-toc"><h2>차례</h2><ol>${b.sections.map((s) => `<li><span>${String(s.number).padStart(2, '0')}</span>${escapeText(s.title)}</li>`).join('')}</ol></section>` : '';
    printRoot.innerHTML = `<section class="pb-cover"><span class="pb-kicker">${escapeText(window.Srv.honor(b.elder))}의 작은 자서전</span><h1>${escapeText(b.title)}</h1><span class="pb-rule"></span><p class="pb-by">이야기 · ${escapeText(b.elder)}　　엮음 · 내말싸미</p><p class="pb-date">${escapeText(b.date)}</p></section>
      ${toc}
      ${b.sections.map((s) => `<section class="pb-chapter"><span class="pb-num">${String(s.number).padStart(2, '0')}</span><h2>${escapeText(s.title)}</h2>${s.paras.map((p) => `<p>${escapeText(p)}</p>`).join('')}</section>`).join('')}
      <section class="pb-end"><span>✧</span><p>당신의 이야기는 계속됩니다.</p><small>이 책은 ${escapeText(b.elder === '나' ? '제가' : window.Srv.honor(b.elder) + '이')} 들려준 이야기를 바탕으로 내말싸미에서 엮었습니다.<br>${escapeText(b.date)}</small></section>`;
  }

  opts.addEventListener('submit', (e) => {
    e.preventDefault();
    build();
    dialog.close();
    document.body.classList.add('printing-book');
    // 저장할 때 파일 이름이 책 제목으로 잡히도록
    savedTitle = document.title; document.title = `${current.title} - ${window.Srv.honor(current.elder)}의 자서전`;
    // 창이 닫힌 뒤 인쇄 창을 띄운다
    requestAnimationFrame(() => setTimeout(() => { window.print(); }, 60));
  });
  let savedTitle = null;
  window.addEventListener('afterprint', () => { document.body.classList.remove('printing-book'); if (savedTitle) { document.title = savedTitle; savedTitle = null; } });

  // 책장 카드에는 버튼을 두지 않는다 — 책을 펼친 뒤 독서 메뉴의 「PDF 저장」에서 (책장이 너저분해서)
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-book-pdf]');
    if (!btn) return;
    window.SrvLibrary.ensure(btn.dataset.bookPdf).then((book) => { if (book) open(bookFrom(book.title, book.document?.body || book.body, book.document?.sections, book.date)); });
  });

  // ── 읽기 화면: 아래 독서 메뉴(목차 · 책갈피 · 보기 설정) 옆에 넣는다 — 위쪽 막대는 제목 자리를 지킨다 ──
  const toolbar = document.querySelector('#ebook-bottom-bar .ebook-toolbar');
  if (toolbar) {
    const btn = document.createElement('button');
    btn.id = 'ebook-save-pdf'; btn.type = 'button';
    btn.innerHTML = `${icons('download')}<span>PDF 저장</span>`;
    toolbar.append(btn);
    toolbar.classList.add('has-pdf');
    btn.addEventListener('click', () => open(bookFrom(state.title, state.document?.body || state.body, state.document?.sections)));
  }

  // ── 초안 화면: 「글 파일(.txt)로 내려받기」 대신 PDF — txt 는 휴대폰 · PC 에서 따로 열 앱이 있어야 편하게 읽힌다 ──
  const dl = document.getElementById('download-draft');
  if (dl) {
    const pdfBtn = dl.cloneNode(false); // 시안의 txt 내려받기 연결을 떼어 낸다
    pdfBtn.innerHTML = `${icons('download')}<span>PDF로 저장하기</span>`;
    dl.replaceWith(pdfBtn);
    // 고친 글(state.body)을 그대로 담는다 — 장 제목은 서버가 준 sections 를 쓴다
    pdfBtn.addEventListener('click', () => open(bookFrom(state.title, state.body, state.document?.sections)));
  }

  window.MemoirPdf = {open, bookFrom};
}());
