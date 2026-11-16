(function () {
  'use strict';
  // 펼친 책처럼 보이는 이북 — 책상 위에 펼쳐 둔 책.
  //  · 그 책의 표지 색으로 표지 판(가장자리)을 두르고, 위에는 책 제목 · 아래 바깥쪽 모서리에 쪽 번호를 단다.
  //  · 글자 칸의 크기 · 여백은 건드리지 않는다(쪽 나눔이 바뀌지 않게). 꾸밈은 그림자 · 배경 · 덧붙인 글자뿐이다.
  const left = document.getElementById('ebook-content'), right = document.getElementById('ebook-right-content');
  const label = document.getElementById('ebook-page-label');
  if (!left) return;

  function coverColor() {
    const id = window.MemoirLibrary?.findOpen?.();
    const btn = id && document.querySelector(`[data-library-book="${CSS.escape(id)}"]`);
    const c = btn ? getComputedStyle(btn.querySelector('.ml-cover')).getPropertyValue('--ml-cover-color').trim() : '';
    return c || '#5f1d2c';
  }
  function setBook() {
    document.body.style.setProperty('--book-cover', coverColor());
    const title = (typeof state !== 'undefined' && state.title) || '';
    document.body.style.setProperty('--book-running', JSON.stringify(title));
  }
  function folios() {
    const m = /^(\d+)(?:–(\d+))?\s*\/\s*(\d+)/.exec(label?.textContent || '');
    if (!m) { left.removeAttribute('data-folio'); right?.removeAttribute('data-folio'); return; }
    const a = Number(m[1]), b = m[2] ? Number(m[2]) : null;
    // 표지(1쪽)에는 쪽 번호 · 머리글을 달지 않는다
    left.dataset.folio = a > 1 ? String(a) : '';
    left.classList.toggle('rb-cover-page', a === 1);
    if (right) { right.dataset.folio = b ? String(b) : ''; right.classList.toggle('rb-cover-page', false); }
  }
  if (label) new MutationObserver(folios).observe(label, {childList: true, characterData: true, subtree: true});
  window.addEventListener('memoir:screen', (e) => { if (e.detail.screen === 'reader') { setBook(); requestAnimationFrame(folios); } });
  if (location.hash === '#reader') { setBook(); folios(); }
}());
