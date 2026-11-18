(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     reader-font — 자서전 본문 글꼴 (외부 피드백 11-17: 실제 출판 도서 서체 「부크크 명조」)
       · 기본: 부크크 명조(fonts/bookk-font.css). 「보기 설정 → 본문 글꼴」에서 기본 명조와 바꿔 비교할 수 있다.
       · 쓰는 곳: 읽기 화면(이북) 본문 · 자서전 초안 본문. 사이트 전체 글꼴은 그대로.
       · 글꼴이 늦게 도착하면 쪽 나눔이 달라지므로, 도착한 뒤 · 바꾼 뒤 쪽을 다시 나눈다(resize 신호).
     ═══════════════════════════════════════════════════════════════ */
  const KEY = 'memoir.readerFont';
  const FONTS = [{key: 'bookk', label: '부크크 명조'}, {key: 'basic', label: '기본 명조'}];
  const get = () => { try { return localStorage.getItem(KEY) === 'basic' ? 'basic' : 'bookk'; } catch (_) { return 'bookk'; } };
  const relayout = () => window.dispatchEvent(new Event('resize'));
  function apply(k) {
    document.documentElement.classList.toggle('reader-font-basic', k === 'basic');
    document.querySelectorAll('[data-book-font]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.bookFont === k)));
  }
  // 「보기 설정」에 글꼴 고르기 — 글자 크기 바로 아래
  const size = document.getElementById('ebook-font-size')?.closest('.ebook-setting-group');
  if (size) {
    size.insertAdjacentHTML('afterend', `<section class="ebook-setting-group ebook-font-family-group"><h3>본문 글꼴</h3>
      <div class="ebook-segmented" role="group" aria-label="본문 글꼴">${FONTS.map((f) => `<button type="button" data-book-font="${f.key}" aria-pressed="false" class="rf-${f.key}">${f.label}</button>`).join('')}</div></section>`);
    size.parentElement.addEventListener('click', (e) => {
      const b = e.target.closest('[data-book-font]'); if (!b) return;
      try { localStorage.setItem(KEY, b.dataset.bookFont); } catch (_) {}
      apply(b.dataset.bookFont); relayout();
    });
  }
  apply(get());
  if (document.fonts?.load) document.fonts.load('300 24px "Bookk Myungjo"', '가나다').then((list) => { if (list.length) relayout(); }).catch(() => {});
  window.MemoirReaderFont = {get, apply};
}());
