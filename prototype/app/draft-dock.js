(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     draft-dock — 자서전 초안을 읽어 내려가는 동안 「작은 책으로 보관하기」 · 「책으로 미리 읽기」가 따라온다
       · 넓은 화면(글 옆에 버튼 칸): 버튼 묶음이 화면 위쪽에 붙어 함께 내려온다 (CSS sticky)
       · 좁은 화면(버튼이 글 맨 아래): 버튼이 화면에 안 보이는 동안 아래 메뉴 바로 위에 작은 버튼 줄을 띄운다
         원래 버튼이 화면에 들어오면 줄은 숨는다. 글을 고치는 중에는 띄우지 않는다(고친 글을 적용하기 전에 보관되지 않게).
     ═══════════════════════════════════════════════════════════════ */
  const screen = document.querySelector('[data-screen="draft"]');
  const aside = screen?.querySelector('.draft-aside');
  const actions = aside?.querySelector('.draft-actions');
  if (!actions) return;

  // 넓은 화면: 버튼 묶음과 아래 안내 글을 한 덩어리로 묶어 함께 따라오게
  const follow = document.createElement('div');
  follow.className = 'draft-follow';
  actions.before(follow);
  follow.append(actions);
  const note = aside.querySelector(':scope > .small-copy');
  if (note) follow.append(note);

  // 좁은 화면: 아래에 뜨는 버튼 줄
  const dock = document.createElement('div');
  dock.className = 'draft-dock'; dock.hidden = true;
  dock.setAttribute('role', 'group'); dock.setAttribute('aria-label', '초안 바로 가기');
  dock.innerHTML = `<button type="button" class="button outline" data-dock="read">책으로 미리 읽기</button>
    <button type="button" class="button primary" data-dock="keep"><svg class="icon" aria-hidden="true"><use href="#i-book"/></svg>작은 책으로 보관하기</button>`;
  document.body.append(dock);
  dock.addEventListener('click', (e) => {
    const b = e.target.closest('[data-dock]'); if (!b) return;
    const real = b.dataset.dock === 'keep' ? document.getElementById('save-volume') : actions.querySelector('[data-go="reader"]');
    real?.click();
  });

  const wide = matchMedia('(min-width: 1021px)');
  let seen = true;
  new IntersectionObserver((es) => { seen = es[es.length - 1].isIntersecting; paint(); }, {threshold: 0.15}).observe(actions);

  /** 화면 위에 고정된 머리(PC 메뉴)의 아래 끝 — 화면 맨 위 가운데에 있는 고정 요소를 찾는다 */
  function fixedTop() {
    let el = document.elementFromPoint(innerWidth / 2, 2), bottom = 0;
    for (; el && el !== document.body; el = el.parentElement) {
      if (getComputedStyle(el).position === 'fixed') bottom = Math.max(bottom, el.getBoundingClientRect().bottom);
    }
    return bottom;
  }
  /** 화면 아래에 고정된 것(휴대폰 아래 메뉴 · 예시 화면 띠) 중 가장 위 */
  function fixedBottom() {
    let top = innerHeight;
    document.querySelectorAll('.mobile-nav, .demo-badge').forEach((el) => {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || el.hidden || cs.position !== 'fixed') return;
      const r = el.getBoundingClientRect();
      if (r.height && r.top > innerHeight / 2) top = Math.min(top, r.top);
    });
    return innerHeight - top;
  }
  function place() {
    document.documentElement.style.setProperty('--draft-follow-top', `${Math.max(16, Math.round(fixedTop()) + 18)}px`);
    const up = Math.round(fixedBottom());
    dock.style.bottom = up ? `${up + 8}px` : 'calc(10px + env(safe-area-inset-bottom))';
    // 안내(토스트)는 버튼 줄 위로
    document.documentElement.style.setProperty('--draft-dock-space', `${(up || 10) + 8 + (dock.offsetHeight || 70) + 10}px`);
  }
  function paint() {
    const editing = !document.getElementById('draft-editor')?.hidden;
    const on = !screen.hidden && !wide.matches && !seen && !editing && !document.body.classList.contains('ebook-mode');
    dock.hidden = !on;
    if (on) place();
    document.body.classList.toggle('draft-dock-on', on);
  }
  window.addEventListener('memoir:screen', () => requestAnimationFrame(paint));
  window.addEventListener('hashchange', () => requestAnimationFrame(paint));
  window.addEventListener('resize', () => { place(); paint(); });
  wide.addEventListener('change', paint);
  // 「글 수정하기」를 열고 닫을 때
  new MutationObserver(paint).observe(document.getElementById('draft-editor'), {attributes: true, attributeFilter: ['hidden']});
  place(); paint();
  window.addEventListener('memoir:screen', () => requestAnimationFrame(place));
}());
