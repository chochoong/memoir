(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     drag-order — 「엽서 정리 · 책 정리」 중에 엽서 · 책을 끌어 순서를 바꾼다 (보드 · 책장이 함께 쓰는 부품).
       · 마우스: 눌러서 조금(6px) 움직이면 바로 끈다.
       · 손가락: 잠깐(0.35초) 꾹 누르고 있으면 들려서 끌 수 있다. 바로 밀면 화면이 평소처럼 내려간다.
       · 끄는 동안 다른 항목 위로 가면 그 자리로 들어가고, 나머지는 부드럽게 비켜 준다.
       · 화면 위 · 아래 끝으로 가져가면 저절로 내려가거나 올라간다.
       · 끌었다 놓은 뒤의 「누름」은 버린다(고르기가 함께 눌리지 않게). 그냥 누르면 지금처럼 고르기.
       · Esc 를 누르면 끌던 것을 제자리로 돌린다.
     MemoirDrag.attach({root, item, idOf, enabled, onDrop})
       root    — 항목들이 든 상자 (엽서 보드 · 책장)
       item    — 끌 수 있는 항목의 선택자
       idOf(el) — 그 항목의 id
       enabled — 지금 끌 수 있는지 (정리 중 · 전체 보기일 때만)
       onDrop(ids) — 놓았을 때, 새 순서의 id 들
     ═══════════════════════════════════════════════════════════════ */
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const HOLD_MS = 350, MOVE_PX = 6, TOUCH_SLOP = 8, EDGE = 90;

  function attach({root, item, idOf, enabled, onDrop}) {
    let pending = null, drag = null, swallowClick = false;
    const items = () => [...root.querySelectorAll(item)];

    root.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || drag || !enabled()) return;
      const el = e.target.closest(item);
      if (!el || !root.contains(el)) return;
      pending = {el, x: e.clientX, y: e.clientY, id: e.pointerId, touch: e.pointerType !== 'mouse', timer: 0};
      if (pending.touch) pending.timer = setTimeout(() => { if (pending) begin(pending.x, pending.y); }, HOLD_MS);
    });
    window.addEventListener('pointermove', (e) => {
      if (drag) { e.preventDefault(); move(e.clientX, e.clientY); return; }
      if (!pending || e.pointerId !== pending.id) return;
      const d = Math.hypot(e.clientX - pending.x, e.clientY - pending.y);
      if (pending.touch) { if (d > TOUCH_SLOP) cancelPending(); else { pending.x = e.clientX; pending.y = e.clientY; } }
      else if (d > MOVE_PX) begin(e.clientX, e.clientY);
    }, {passive: false});
    // 손가락으로 들었을 때는 화면이 함께 내려가지 않게 막는다 (pointermove 만으로는 막히지 않는 브라우저가 있다)
    window.addEventListener('touchmove', (e) => { if (drag) e.preventDefault(); }, {passive: false});
    window.addEventListener('pointerup', () => { if (drag) end(true); else cancelPending(); });
    window.addEventListener('pointercancel', () => { if (drag) end(false); else cancelPending(); });
    root.addEventListener('contextmenu', (e) => { if (drag || pending?.touch) e.preventDefault(); });
    document.addEventListener('keydown', (e) => { if (drag && e.key === 'Escape') { e.stopImmediatePropagation(); end(false); } }, true);
    // 끌었다 놓은 직후의 누름은 고르기로 받지 않는다 — 다른 click 처리보다 먼저 받는다
    window.addEventListener('click', (e) => { if (swallowClick) { e.preventDefault(); e.stopImmediatePropagation(); swallowClick = false; } }, true);

    function copyLook(src, dst) {
      const cs = getComputedStyle(src);
      for (let i = 0; i < cs.length; i++) dst.style.setProperty(cs[i], cs.getPropertyValue(cs[i]));
      // 가상 요소(압정 · 테이프 · 고르기 동그라미)는 옮겨 그릴 수 없어 빠진다 — 끄는 동안만이라 괜찮다
      const a = src.children, b = dst.children;
      for (let i = 0; i < a.length; i++) if (b[i]) copyLook(a[i], b[i]);
    }

    function cancelPending() { if (pending) clearTimeout(pending.timer); pending = null; }

    function begin(x, y) {
      const el = pending.el; cancelPending();
      const r = el.getBoundingClientRect();
      // 손에 든 모양 — 보드 · 책장 안에서만 먹는 꾸밈(몇 번째 칸인지에 따른 색 · 기울기)을 그대로 옮겨 그린다
      const copy = el.cloneNode(true);
      copyLook(el, copy);
      copy.removeAttribute('id');
      copy.querySelectorAll('[id]').forEach((n) => n.removeAttribute('id'));
      Object.assign(copy.style, {position: 'static', margin: '0', width: r.width + 'px', height: r.height + 'px', transition: 'none', animation: 'none'});
      const ghost = document.createElement('div');
      ghost.className = 'drag-ghost'; ghost.setAttribute('aria-hidden', 'true');
      Object.assign(ghost.style, {width: r.width + 'px', height: r.height + 'px', left: r.left + 'px', top: r.top + 'px'});
      ghost.append(copy);
      document.body.append(ghost);
      el.classList.add('drag-source');
      document.body.classList.add('drag-ordering');
      const order = items().map(idOf);
      drag = {el, ghost, dx: x - r.left, dy: y - r.top, x, y, start: order, raf: 0};
      if (navigator.vibrate) { try { navigator.vibrate(15); } catch (_) {} }
      scrollLoop();
    }

    function move(x, y) {
      drag.x = x; drag.y = y;
      drag.ghost.style.transform = `translate(${x - drag.dx - parseFloat(drag.ghost.style.left)}px, ${y - drag.dy - parseFloat(drag.ghost.style.top)}px) rotate(-2deg) scale(1.04)`;
      const under = document.elementFromPoint(x, y)?.closest(item);
      if (!under || under === drag.el || !root.contains(under)) return;
      const list = items();
      const from = list.indexOf(drag.el), to = list.indexOf(under);
      if (from < 0 || to < 0) return;
      const before = flipFirst(list);
      if (from < to) under.after(drag.el); else under.before(drag.el);
      flipPlay(list, before);
    }

    // 비켜 주는 움직임 (FLIP — 옮기기 전 자리를 재고, 옮긴 뒤 그 차이만큼 되돌렸다가 풀어 준다)
    function flipFirst(list) { return reduce.matches ? null : new Map(list.map((el) => [el, el.getBoundingClientRect()])); }
    function flipPlay(list, before) {
      if (!before) return;
      list.forEach((el) => {
        if (el === drag.el) return;
        const a = before.get(el), b = el.getBoundingClientRect();
        const dx = a.left - b.left, dy = a.top - b.top;
        if (dx || dy) el.animate([{transform: `translate(${dx}px, ${dy}px)`}, {transform: 'none'}], {duration: 180, easing: 'ease-out'});
      });
    }

    // 화면 끝으로 가져가면 저절로 스크롤
    function scrollLoop() {
      if (!drag) return;
      const h = innerHeight;
      const v = drag.y < EDGE ? -(EDGE - drag.y) / 5 : drag.y > h - EDGE ? (drag.y - (h - EDGE)) / 5 : 0;
      if (v) { scrollBy(0, Math.round(v)); move(drag.x, drag.y); }
      drag.raf = requestAnimationFrame(scrollLoop);
    }

    function end(keep) {
      const {el, ghost, start, raf} = drag;
      cancelAnimationFrame(raf);
      drag = null;
      ghost.remove();
      el.classList.remove('drag-source');
      document.body.classList.remove('drag-ordering');
      swallowClick = true; setTimeout(() => { swallowClick = false; }, 400);
      const now = items().map(idOf);
      if (!keep) { restore(start); return; }
      if (now.join('\u0001') !== start.join('\u0001')) onDrop(now);
    }
    function restore(order) {
      const map = new Map(items().map((el) => [idOf(el), el]));
      const list = items();
      // 같은 부모 안에서만 되돌린다 (책장은 칸마다 부모가 달라, 다시 그리기로 되돌린다)
      if (list.every((el) => el.parentElement === list[0].parentElement)) order.forEach((id) => list[0].parentElement.append(map.get(id)));
      else onDrop(order);
    }
    return {busy: () => !!drag};
  }

  window.MemoirDrag = {attach};
}());
