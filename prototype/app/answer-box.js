(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     answer-box — 인터뷰 「글로 쓰기」 칸
       · 한 번에 1만 자까지(index.html maxlength="10000"). 서버(/speech)에는 글자 수 상한이 없다.
       · 글이 길어지면 칸이 조금씩 커지다가, 일정 높이부터는 칸 안에서 스크롤해 앞에 쓴 글(오타)을 다시 볼 수 있다.
       · 칸 아래에 「지금 글자 수 / 10,000자」를 보여 준다. 다 차면 더 쓸 수 없다고 알려 준다.
     ═══════════════════════════════════════════════════════════════ */
  const box = () => document.getElementById('answer-text');
  const fmt = (n) => n.toLocaleString('ko-KR');

  function counter(ta) {
    let c = document.getElementById('answer-count');
    if (!c) {
      c = document.createElement('p');
      c.id = 'answer-count'; c.className = 'answer-count'; c.setAttribute('aria-live', 'polite');
      ta.insertAdjacentElement('afterend', c);
    }
    return c;
  }
  /** 칸 높이를 글에 맞춘다 — CSS max-height 를 넘으면 그 높이에 멈추고 칸 안에서 스크롤 */
  function fit(ta) {
    const max = parseFloat(getComputedStyle(ta).maxHeight) || Infinity;
    const atEnd = ta.selectionEnd === ta.value.length;
    ta.style.height = 'auto';
    const want = ta.scrollHeight + (ta.offsetHeight - ta.clientHeight);
    ta.style.height = `${Math.min(want, max)}px`;
    ta.classList.toggle('answer-scrolls', want > max);
    if (atEnd && document.activeElement === ta) ta.scrollTop = ta.scrollHeight;   // 끝에서 쓰는 중이면 끝이 보이게
  }
  function update() {
    const ta = box(); if (!ta) return;
    const max = Number(ta.getAttribute('maxlength')) || 10000, n = ta.value.length;
    const c = counter(ta);
    c.hidden = n === 0;
    c.classList.toggle('near', n >= max * 0.95);
    c.textContent = n >= max ? `${fmt(max)}자까지 적을 수 있어요. 나머지는 보낸 뒤 이어서 적어 주세요.` : `${fmt(n)} / ${fmt(max)}자`;
    fit(ta);
  }

  document.addEventListener('input', (e) => { if (e.target.id === 'answer-text') update(); });
  // 보낸 뒤 칸을 비우는 곳(srv-interview · app.js)이 여러 곳이라, 값을 바꾸는 순간을 한곳에서 잡는다
  const desc = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
  Object.defineProperty(HTMLTextAreaElement.prototype, 'value', {
    configurable: true, enumerable: desc.enumerable, get: desc.get,
    set(v) { desc.set.call(this, v); if (this.id === 'answer-text') queueMicrotask(update); },
  });
  // 「글로 쓰기」로 바꿀 때 · 창 크기가 바뀔 때 높이를 다시 잰다
  document.addEventListener('click', (e) => { if (e.target.closest?.('#toggle-answer')) requestAnimationFrame(update); });
  window.addEventListener('resize', () => requestAnimationFrame(update));
  update();
}());
