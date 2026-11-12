(function () {
  'use strict';
  // 이북 쪽 넘기기를 화살표로 분명하게 — 「책 가장자리를 누르면 넘어감 / 가운데를 누르면 메뉴」처럼 보이지 않는 구역을 없앴다.
  //  · 넓은 화면: 책 양옆 책상 위에 큰 ‹ › 단추(아래에 「이전 쪽 · 다음 쪽」)
  //  · 좁은 PC 창: 책 아래에 「‹ 이전 · 2 / 4쪽 · 다음 ›」 막대 / 휴대폰(760px 이하)은 화살표 없이 예전처럼 책 가장자리를 눌러 넘김
  //  · 첫 쪽 · 마지막 쪽에서는 그쪽 단추를 흐리게. 밀어서 넘기기 · 키보드 화살표는 그대로.
  const prev = document.getElementById('ebook-page-previous'), next = document.getElementById('ebook-page-next');
  const label = document.getElementById('ebook-page-label');
  const stage = document.getElementById('ebook-stage');
  if (!prev || !next || !stage) return;

  const side = document.createElement('div');
  side.className = 'ra-side'; side.setAttribute('aria-hidden', 'true');
  side.innerHTML = `<button type="button" class="ra-btn ra-prev" tabindex="-1">${icons('chevron', 'flip')}<span>이전 쪽</span></button>
    <button type="button" class="ra-btn ra-next" tabindex="-1">${icons('chevron')}<span>다음 쪽</span></button>`;
  const pill = document.createElement('div');
  pill.className = 'ra-pill';
  pill.innerHTML = `<button type="button" class="ra-pbtn ra-prev" aria-label="이전 쪽">${icons('chevron', 'flip')}<span>이전</span></button>
    <span class="ra-count" aria-live="polite"></span>
    <button type="button" class="ra-pbtn ra-next" aria-label="다음 쪽"><span>다음</span>${icons('chevron')}</button>`;
  document.querySelector('.ebook-reader')?.append(side, pill);

  const go = (d) => (d < 0 ? prev : next).click();
  [side, pill].forEach((box) => {
    // 마우스 · 손가락으로 누를 때는 단추에 초점을 두지 않는다(그래야 키보드 ← → 도 계속 먹는다)
    box.addEventListener('pointerdown', (e) => { if (e.target.closest('button')) e.preventDefault(); });
    box.querySelector('.ra-prev').addEventListener('click', (e) => { e.stopPropagation(); if (!box.querySelector('.ra-prev').classList.contains('is-end')) go(-1); });
    box.querySelector('.ra-next').addEventListener('click', (e) => { e.stopPropagation(); if (!box.querySelector('.ra-next').classList.contains('is-end')) go(1); });
  });

  function update() {
    const paged = document.body.classList.contains('ebook-paged') && document.body.classList.contains('ebook-mode');
    const m = /^(\d+)(?:–(\d+))?\s*\/\s*(\d+)/.exec(label?.textContent || '');
    const start = m ? Number(m[1]) : 1, end = m ? Number(m[2] || m[1]) : 1, total = m ? Number(m[3]) : 1;
    const atStart = start <= 1, atEnd = end >= total;
    document.querySelectorAll('.ra-prev').forEach((b) => { b.classList.toggle('is-end', atStart); b.setAttribute('aria-disabled', String(atStart)); });
    document.querySelectorAll('.ra-next').forEach((b) => { b.classList.toggle('is-end', atEnd); b.setAttribute('aria-disabled', String(atEnd)); });
    pill.querySelector('.ra-count').textContent = m ? `${m[2] ? `${start}–${end}` : start} / ${total}쪽` : '';
    // 휴대폰은 예전처럼 책을 눌러 넘기므로 화살표를 두지 않는다
    if (!paged || innerWidth <= 760) { side.hidden = true; pill.hidden = true; return; }
    const r = stage.getBoundingClientRect();
    const room = r.left; // 책 왼쪽 책상 폭
    const wide = room >= 120;
    side.hidden = !wide; pill.hidden = wide;
    if (wide) {
      const cy = r.top + r.height / 2;
      const gap = Math.min(40, (room - 84) / 2);
      side.style.setProperty('--ra-y', `${cy}px`);
      side.style.setProperty('--ra-left', `${Math.max(8, r.left - 18 - gap - 84)}px`);
      side.style.setProperty('--ra-right', `${Math.max(8, innerWidth - r.right - 18 - gap - 84)}px`);
    } else {
      // 메뉴가 떠 있으면 아래 막대 바로 위로, 숨어 있으면 책 아래 책상 위로
      const bar = document.getElementById('ebook-bottom-bar');
      const chromeHidden = document.body.classList.contains('ebook-chrome-hidden');
      const barH = !chromeHidden && bar ? bar.getBoundingClientRect().height : 0;
      let bottom = chromeHidden ? Math.max(10, (innerHeight - r.bottom - 56) / 2) : barH + 10;
      // 「독서 메뉴 보기」 단추와 겹치지 않게 그 위로
      const tools = document.getElementById('ebook-show-tools');
      if (chromeHidden && tools && !tools.hidden) { const t = tools.getBoundingClientRect(); if (t.height) bottom = Math.max(bottom, innerHeight - t.top + 12); }
      pill.style.bottom = `${bottom}px`;
    }
  }
  if (label) new MutationObserver(update).observe(label, {childList: true, characterData: true, subtree: true});
  new MutationObserver(update).observe(document.body, {attributes: true, attributeFilter: ['class']});
  window.addEventListener('resize', () => requestAnimationFrame(update));
  window.addEventListener('memoir:screen', () => requestAnimationFrame(() => requestAnimationFrame(update)));
  update();
}());
