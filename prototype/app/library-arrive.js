(function () {
  'use strict';
  // 새 자서전을 책장에 꽂는 연출 — 「책장에 모으기」로 새 책이 생기면:
  //  1) 화면이 살짝 어두워지고, 새 책이 아래에서 올라와 앞표지를 보여 준다(「새 책이 엮였어요」)
  //  2) 표지에 빛이 한 번 지나간다
  //  3) 책이 작아지며 책장 자리 위로 날아가, 위에서 쏙 꽂힌다. 옆 책들이 살짝 밀렸다 돌아온다
  //  4) 꽂힌 자리에 작은 반짝임, 책 아래에 「새 책」 표시. 화면을 누르면 바로 끝까지 건너뛴다.
  const lib = window.MemoirLibrary;
  const shelf = document.querySelector('[data-screen="library"]');
  if (!lib || !shelf) return;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const nextFrame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  let pending = null, running = null;

  const original = lib.saveDraft;
  lib.saveDraft = function () {
    const before = new Set(lib.bookIds());
    const result = original.apply(this, arguments);
    const added = lib.bookIds().find((id) => !before.has(id));
    if (added) {
      pending = added;
      if (location.hash === '#library') nextFrame().then(run);
    }
    return result;
  };
  window.addEventListener('memoir:screen', (e) => { if (e.detail.screen === 'library' && pending) nextFrame().then(run); });

  function liOf(id) { return shelf.querySelector(`[data-library-book="${CSS.escape(id)}"]`)?.closest('li'); }
  function badge(li) {
    const label = li.querySelector('.ml-volume-label');
    if (label && !label.querySelector('.la-new')) label.insertAdjacentHTML('afterbegin', '<span class="la-new">새 책</span>');
  }

  async function run() {
    const id = pending; pending = null;
    if (!id || running) return;
    const li = liOf(id);
    const btn = li?.querySelector('[data-library-book]');
    const cover = btn?.querySelector('.ml-cover');
    if (!cover) return;
    li.scrollIntoView({block: 'center', behavior: 'instant'});
    await nextFrame();
    if (reduce.matches) { badge(li); btn.focus({preventScroll: true}); return; }

    const title = window.MemoirLibrary.getBook(id)?.title || '';
    const tone = [...btn.classList].find((c) => c.startsWith('ml-tone-')) || 'ml-tone-0';
    const target = cover.getBoundingClientRect();
    const W = Math.min(250, innerWidth * .58), H = W * target.height / target.width;
    const cx = innerWidth / 2, cy = innerHeight * .44;

    // 무대
    const host = document.createElement('div');
    host.className = 'la-host';
    host.innerHTML = `<div class="la-dim"></div>
      <p class="la-caption" role="status"><span>새 책이 엮였어요</span><strong></strong><small>화면을 누르면 바로 책장에 꽂아요</small></p>
      <div class="la-fly"><div class="la-book lp-scope ${tone}"></div><span class="la-shine"></span></div>`;
    host.querySelector('.la-caption strong').textContent = title;
    const fly = host.querySelector('.la-fly');
    fly.querySelector('.la-book').append(cover.cloneNode(true));
    Object.assign(fly.style, {width: W + 'px', height: H + 'px', left: (cx - W / 2) + 'px', top: (cy - H / 2) + 'px'});
    host.querySelector('.la-caption').style.top = (cy + H / 2 + 22) + 'px';
    document.body.append(host);
    // 「책장에 모았어요」 안내는 연출이 끝난 뒤 다시 띄운다
    const toastEl = document.getElementById('toast');
    const toastText = toastEl && !toastEl.hidden ? toastEl.textContent : '';
    if (toastEl) toastEl.hidden = true;
    cover.style.visibility = 'hidden';
    const copy = li.querySelector('.ml-book-copy');
    if (copy) copy.style.opacity = '0';

    const anims = [];
    let skipped = false;
    const play = (el, frames, opt) => { const a = el.animate(frames, {fill: 'forwards', ...opt}); anims.push(a); if (skipped) a.finish(); return a.finished; };
    const skip = () => { skipped = true; anims.forEach((a) => { try { a.finish(); } catch { /* 끝난 것 */ } }); };
    host.addEventListener('click', skip);
    const onKey = (e) => { if (e.key === 'Escape' || e.key === 'Enter' || e.key === ' ') { e.preventDefault(); skip(); } };
    document.addEventListener('keydown', onKey, true);
    running = true;

    try {
      // 1) 아래에서 올라와 앞표지를 보여 준다
      play(host.querySelector('.la-dim'), [{opacity: 0}, {opacity: 1}], {duration: 420});
      play(host.querySelector('.la-caption'), [{opacity: 0, transform: 'translate(-50%, 16px)'}, {opacity: 1, transform: 'translate(-50%, 0)'}], {duration: 520, delay: 380, easing: 'ease-out'});
      await play(fly, [
        {transform: `translateY(${innerHeight * .55}px) rotateX(28deg) scale(.82)`, opacity: 0},
        {transform: 'translateY(-14px) rotateX(-4deg) rotateY(-10deg) scale(1.02)', opacity: 1, offset: .7},
        {transform: 'rotateY(-6deg)', opacity: 1}
      ], {duration: 820, easing: 'cubic-bezier(.2,.8,.3,1)'});
      // 2) 빛이 한 번 지나간다 — 잠깐 머문다
      await play(fly.querySelector('.la-shine'), [{transform: 'translateX(-130%) skewX(-18deg)', opacity: 0}, {opacity: .9, offset: .3}, {transform: 'translateX(230%) skewX(-18deg)', opacity: 0}], {duration: 900, easing: 'ease-in-out'});
      if (!skipped) await play(fly, [{transform: 'rotateY(-6deg)'}, {transform: 'rotateY(4deg)'}], {duration: 380, easing: 'ease-in-out'});

      // 3) 책장 자리 위로 날아가 꽂힌다
      const tr = cover.getBoundingClientRect(); // 스크롤 뒤 실제 자리
      const s = tr.width / W;
      const dx = tr.left + tr.width / 2 - cx, dy = tr.top + tr.height / 2 - cy;
      play(host.querySelector('.la-caption'), [{opacity: 1}, {opacity: 0}], {duration: 300});
      play(host.querySelector('.la-dim'), [{opacity: 1}, {opacity: 0}], {duration: 700, delay: 250});
      await play(fly, [
        {transform: 'rotateY(4deg)'},
        {transform: `translate(${dx * .55}px, ${dy * .45 - 90}px) rotate(-7deg) scale(${(1 + s) / 2})`, offset: .55},
        {transform: `translate(${dx}px, ${dy - tr.height * .55}px) rotate(-3deg) scale(${s})`}
      ], {duration: 760, easing: 'cubic-bezier(.45,.05,.3,1)'});
      await play(fly, [
        {transform: `translate(${dx}px, ${dy - tr.height * .55}px) rotate(-3deg) scale(${s})`},
        {transform: `translate(${dx}px, ${dy + 4}px) rotate(0deg) scale(${s})`, offset: .8},
        {transform: `translate(${dx}px, ${dy}px) scale(${s})`}
      ], {duration: 300, easing: 'cubic-bezier(.6,0,.9,.5)'});
    } finally {
      document.removeEventListener('keydown', onKey, true);
      cover.style.visibility = '';
      host.remove();
      running = false;
    }

    // 4) 꽂힌 뒤: 옆 책이 살짝 밀렸다 돌아오고, 반짝임과 「새 책」 표시
    const row = [...li.parentElement.children];
    const i = row.indexOf(li);
    [[row[i - 1], -6], [row[i + 1], 6]].forEach(([n, x]) => n?.querySelector('.ml-cover')?.animate([{transform: 'none'}, {transform: `translateX(${x}px) rotate(${x / 3}deg)`}, {transform: 'none'}], {duration: 420, easing: 'ease-out'}));
    cover.animate([{transform: 'translateY(-6px)'}, {transform: 'translateY(1px)'}, {transform: 'none'}], {duration: 320, easing: 'ease-out'});
    if (copy) { copy.style.opacity = ''; copy.animate([{opacity: 0, transform: 'translateY(6px)'}, {opacity: 1, transform: 'none'}], {duration: 420, easing: 'ease-out'}); }
    sparkle(cover.getBoundingClientRect());
    badge(li);
    btn.focus({preventScroll: true});
    if (toastText) toast(toastText);
  }

  function sparkle(r) {
    const layer = document.createElement('div');
    layer.className = 'la-sparkles';
    document.body.append(layer);
    const n = 10;
    for (let k = 0; k < n; k++) {
      const a = (k / n) * Math.PI * 2 + Math.random() * .4;
      const sx = r.left + r.width / 2 + Math.cos(a) * r.width * .45, sy = r.top + r.height * .45 + Math.sin(a) * r.height * .45;
      const star = document.createElement('span');
      star.textContent = k % 3 ? '✦' : '✧';
      Object.assign(star.style, {left: sx + 'px', top: sy + 'px', fontSize: (10 + Math.random() * 10) + 'px'});
      layer.append(star);
      star.animate([{transform: 'translate(-50%,-50%) scale(.2)', opacity: 0}, {transform: `translate(calc(-50% + ${Math.cos(a) * 26}px), calc(-50% + ${Math.sin(a) * 26}px)) scale(1)`, opacity: 1, offset: .4}, {transform: `translate(calc(-50% + ${Math.cos(a) * 42}px), calc(-50% + ${Math.sin(a) * 42}px)) scale(.6)`, opacity: 0}], {duration: 900, delay: k * 25, easing: 'ease-out', fill: 'forwards'});
    }
    setTimeout(() => layer.remove(), 1300);
  }

  window.MemoirArrive = {play: (id) => { pending = id; return nextFrame().then(run); }};
}());
