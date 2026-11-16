(function () {
  'use strict';
  // 2. 자서전 — 책장에서 책을 꺼내 펼치는 연출.
  //    chochoong/memoir html-prototype 브랜치 prototype/bookshelf.html 「02 꺼내는 책」(makeFly · geometry · openBook · closeBook)을
  //    이 시안의 책장(.ml-cover)과 읽기 화면(#ebook-viewport)에 맞게 옮겼다. 책을 여는 동작 자체는 기존 MemoirLibrary.openBook 그대로.
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const screen = document.querySelector('[data-screen="library"]');
  if (!screen) return;
  let busy = false, lastOpened = null, prevScreen = null;
  const anim = (el, frames, opt) => el.animate(frames, {fill: 'forwards', ...opt}).finished;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const centerY = () => innerHeight * .46;
  const T = (x, y, sx, sy, extra = '') => `perspective(1600px) translate(${x}px, ${y}px) scale(${sx}, ${sy}) ${extra}`;

  function host() {
    const h = document.createElement('div');
    h.className = 'lp-host';
    document.body.append(h);
    return h;
  }
  function makeFly(h, cover, tone, w, ht) {
    const color = getComputedStyle(cover).getPropertyValue('--ml-cover-color').trim() || '#5f1d2c';
    const fly = document.createElement('div');
    fly.className = 'lp-fly';
    fly.style.cssText = `--c:${color};--th:${Math.round(w * .07)}px;width:${w}px;height:${ht}px;left:${(innerWidth - w) / 2}px;top:${centerY() - ht / 2}px`;
    fly.innerHTML = `<div class="lp-back"></div><div class="lp-edge"></div><div class="lp-pages"></div>
      <div class="lp-cover"><div class="lp-face lp-front lp-scope ${tone}"></div><div class="lp-face lp-inside"></div></div>`;
    const clone = cover.cloneNode(true);
    fly.querySelector('.lp-front').append(clone);
    h.append(fly);
    return fly;
  }
  function geometry(coverEl) {
    const r = coverEl.getBoundingClientRect();
    const w = Math.min(250, innerWidth * .6), h = w * r.height / r.width;
    const left = (innerWidth - w) / 2, cy = centerY();
    return {w, h, left, cy,
      shelf: T(r.left - left, r.top + r.height / 2 - cy, r.width / w, r.width / w),
      lifted: T(0, 0, 1, 1, 'rotateY(-12deg) rotateZ(-2deg)'),
      open: (() => { const s = Math.min(1, (innerWidth - 32) / (2 * w)); return T(w / 2, 0, s, s); })()};
  }
  function spreadTo(g, rect) {
    // 펼친 책(양쪽) 크기를 읽기 화면의 책 자리에 맞춘다
    const sx = rect.width / 2 / g.w, sy = rect.height / g.h;
    return T(rect.left + rect.width / 2 - g.left, rect.top + rect.height / 2 - g.cy, sx, sy);
  }
  function toneOf(btn) { return [...btn.classList].find((c) => c.startsWith('ml-tone-')) || 'ml-tone-0'; }

  async function open(btn) {
    if (busy) return;
    const id = btn.dataset.libraryBook;
    const coverEl = btn.querySelector('.ml-cover');
    if (reduce.matches || !coverEl) { window.MemoirLibrary.openBook(id); return; }
    busy = true; lastOpened = id;
    // 책을 꺼내는 동안 서버에서 본문을 받아 둔다 (GET /api/memoirs/saved/{id})
    const ready = window.SrvLibrary.ensure(id);
    const h = host();
    const g = geometry(coverEl);
    const fly = makeFly(h, coverEl, toneOf(btn), g.w, g.h);
    const cover = fly.querySelector('.lp-cover');
    const th = `translateZ(${Math.round(g.w * .07)}px)`;
    fly.style.transform = g.shelf;
    coverEl.style.visibility = 'hidden';
    h.classList.add('dim');
    // 1) 선반에서 앞으로 빼내어 가운데로
    await anim(fly, [
      {transform: g.shelf},
      {transform: T(0, -16, 1.04, 1.04, 'rotateY(-16deg) rotateZ(-3deg)'), offset: .72},
      {transform: g.lifted}
    ], {duration: 820, easing: 'cubic-bezier(.25,.8,.25,1)'});
    await wait(160);
    // 2) 표지를 넘겨 펼친다
    await Promise.all([
      anim(fly, [{transform: g.lifted}, {transform: g.open}], {duration: 900, easing: 'cubic-bezier(.45,.05,.25,1)'}),
      anim(cover, [{transform: `${th} rotateY(0deg)`}, {transform: `${th} rotateY(-180deg)`}], {duration: 900, easing: 'cubic-bezier(.45,.05,.25,1)'})
    ]);
    // 3) 읽기 화면을 연 뒤, 그 책 자리에 맞추고 바꿔 끼운다
    if (!(await ready)) { h.remove(); coverEl.style.visibility = ''; busy = false; lastOpened = null; return; }
    await window.MemoirLibrary.openBook(id);
    await wait(60);
    const target = document.getElementById('ebook-viewport') || document.getElementById('ebook-stage');
    const rect = target?.getBoundingClientRect();
    if (rect && rect.width > 40) await anim(fly, [{transform: g.open}, {transform: spreadTo(g, rect)}], {duration: 480, easing: 'cubic-bezier(.3,.7,.2,1)'});
    h.classList.remove('dim');
    await anim(fly, [{opacity: 1}, {opacity: 0}], {duration: 240});
    h.remove();
    coverEl.style.visibility = '';
    busy = false;
  }

  async function close(id) {
    if (busy || reduce.matches) return;
    const btn = screen.querySelector(`[data-library-book="${CSS.escape(id)}"]`);
    const coverEl = btn?.querySelector('.ml-cover');
    if (!coverEl) return;
    busy = true;
    const h = host();
    const g = geometry(coverEl);
    const fly = makeFly(h, coverEl, toneOf(btn), g.w, g.h);
    const cover = fly.querySelector('.lp-cover');
    const th = `translateZ(${Math.round(g.w * .07)}px)`;
    cover.style.transform = `${th} rotateY(-180deg)`;
    fly.style.transform = g.open;
    coverEl.style.visibility = 'hidden';
    h.classList.add('dim', 'instant');
    await Promise.all([
      anim(fly, [{transform: g.open}, {transform: g.lifted}], {duration: 760, easing: 'cubic-bezier(.45,.05,.25,1)'}),
      anim(cover, [{transform: `${th} rotateY(-180deg)`}, {transform: `${th} rotateY(0deg)`}], {duration: 760, easing: 'cubic-bezier(.45,.05,.25,1)'})
    ]);
    h.classList.remove('dim', 'instant');
    await anim(fly, [{transform: g.lifted}, {transform: g.shelf}], {duration: 680, easing: 'cubic-bezier(.5,0,.2,1)'});
    coverEl.style.visibility = '';
    h.remove();
    busy = false;
  }

  screen.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-library-book]');
    if (!btn) return;
    event.preventDefault(); event.stopImmediatePropagation();
    open(btn);
  }, true);
  // 읽기에서 책장으로 돌아오면 덮어서 제자리에 꽂는다
  window.addEventListener('memoir:screen', (event) => {
    const now = event.detail.screen;
    if (now === 'library' && prevScreen === 'reader' && lastOpened) {
      const id = lastOpened; lastOpened = null;
      requestAnimationFrame(() => close(id));
    }
    prevScreen = now;
  });
}());
