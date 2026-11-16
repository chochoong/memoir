(function () {
  'use strict';
  // 3. 코르크 보드의 엽서를 뽑아(압정 · 테이프 · 포스트잇) 손에 들고 본다. 놓으면 제자리에 다시 붙는다.
  //    엽서 내용은 기존 recordData · postcardBody(app.js)를 그대로 쓴다.
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const list = document.getElementById('record-list');
  if (!list) return;
  let holding = null;
  const anim = (el, frames, opt) => el.animate(frames, {fill: 'forwards', ...opt}).finished;

  function kindOf(card) {
    const i = [...list.children].indexOf(card.parentElement) + 1;
    if (i % 4 === 0) return 'postit';
    if (i % 3 === 2) return 'tape';
    return 'pin';
  }

  async function pull(card) {
    if (holding) return;
    const id = Number(card.dataset.postcard);
    const record = recordData.find((item) => item.id === id);
    if (!record) return;
    const kind = kindOf(card);
    const r = card.getBoundingClientRect();
    const tilt = getComputedStyle(card).getPropertyValue('--tilt').trim() || '0deg';

    // 손에 든 엽서
    const hold = document.createElement('div');
    hold.className = 'pc-hold';
    hold.setAttribute('role', 'dialog'); hold.setAttribute('aria-modal', 'true'); hold.setAttribute('aria-labelledby', 'pc-held-title');
    if (window.SrvRecords && record.body === undefined) { card.setAttribute('aria-busy', 'true'); await window.SrvRecords.loadBody(record); card.removeAttribute('aria-busy'); if (holding) return; }
    const body = postcardBody(record).split(/\n\s*\n/).map((p) => `<p>${escapeText(p)}</p>`).join('');
    hold.innerHTML = `<div class="pc-hold-dim"></div><article class="pc-held ${kind === 'postit' ? 'postit' : ''}" tabindex="-1">
      <span class="pc-stamp" aria-hidden="true">${icons(record.icon)}</span>
      <div class="pc-meta">${escapeText(categories[record.category])} · ${escapeText(record.date)}</div>
      <h2 id="pc-held-title">${escapeText(record.title)}</h2><div class="pc-body">${body}</div>
      <p class="pc-note">보드에 다시 꽂으면 제자리로 돌아가요.</p>
      <div class="pc-confirm" role="alertdialog" aria-labelledby="pc-confirm-title" aria-describedby="pc-confirm-desc" hidden>
        <strong id="pc-confirm-title">이 엽서를 지울까요?</strong>
        <p id="pc-confirm-desc">지운 엽서는 보드에서 사라지고, 앞으로 만드는 자서전에도 들어가지 않아요. 이미 만든 책은 그대로예요.</p>
        <div><button type="button" class="button outline compact pc-confirm-delete" data-pc-confirm>지우기</button><button type="button" class="button primary compact" data-pc-keep>그대로 두기</button></div></div>
      <div class="pc-actions"><button type="button" class="text-button pc-trash" data-pc-delete>${icons('close')}<span>엽서 지우기</span></button><span class="pc-actions-right"><button type="button" class="button outline compact pc-share" data-pc-share>${icons('share')}<span>엽서 공유</span></button><button type="button" class="button outline compact" data-pc-close>${kind === 'pin' ? '보드에 다시 꽂기' : '보드에 다시 붙이기'}</button></span></div></article>`;
    document.body.append(hold);
    const held = hold.querySelector('.pc-held');
    holding = {card, hold, held, kind, tilt, opener: card};

    if (!reduce.matches) {
      // 1) 핀을 뽑는다 / 테이프를 뗀다
      const fly = card.cloneNode(true);
      fly.className = `postcard-card pc-fly${kind === 'postit' ? ' pc-fly-postit' : ''}`;
      fly.removeAttribute('data-postcard');
      Object.assign(fly.style, {left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px', transform: `rotate(${tilt})`});
      fly.style.setProperty('--tilt', tilt);
      // 보드 위 엽서의 모양(nth-child 규칙)을 그대로 옮긴다
      const cs = getComputedStyle(card);
      fly.style.background = cs.backgroundImage !== 'none' ? cs.backgroundImage : cs.backgroundColor;
      fly.style.boxShadow = cs.boxShadow; fly.style.padding = cs.padding; fly.style.borderRadius = cs.borderRadius;
      fly.style.display = 'flex'; fly.style.flexDirection = 'column'; fly.style.gap = '10px';
      document.body.append(fly);
      card.dataset.pulled = '';
      held.style.opacity = '0';
      if (kind === 'pin') {
        const pin = document.createElement('span');
        pin.className = 'pc-pin';
        Object.assign(pin.style, {left: (r.left + r.width / 2 - 10) + 'px', top: (r.top - 9) + 'px'});
        document.body.append(pin);
        anim(pin, [{transform: 'none', opacity: 1}, {transform: 'translate(10px,-46px) rotate(40deg) scale(1.1)', opacity: 1, offset: .45}, {transform: 'translate(18px,-20px) rotate(70deg) scale(.9)', opacity: 0}], {duration: 520, easing: 'cubic-bezier(.2,.7,.4,1)'}).then(() => pin.remove());
      }
      // 살짝 들어 올렸다가(뜯기는 느낌) …
      await anim(fly, [
        {transform: `rotate(${tilt})`},
        {transform: `translateY(-10px) rotate(calc(${tilt} * -1.6)) scale(1.03)`, offset: .55},
        {transform: `translateY(-14px) rotate(0deg) scale(1.04)`}
      ], {duration: kind === 'pin' ? 360 : 300, easing: 'cubic-bezier(.3,.7,.3,1)'});
      // 2) 손으로 가져온다 — 가운데로 오며 커지고, 엽서를 들어 보듯 살짝 기울었다 바로 선다
      hold.classList.add('on');
      const hr = held.getBoundingClientRect();
      const dx = hr.left + hr.width / 2 - (r.left + r.width / 2), dy = hr.top + hr.height / 2 - (r.top + r.height / 2);
      const s = hr.width / r.width;
      await anim(fly, [
        {transform: 'translateY(-14px) scale(1.04)', opacity: 1},
        {transform: `translate(${dx * .6}px, ${dy * .6 - 30}px) rotate(-6deg) rotateX(14deg) scale(${1 + (s - 1) * .7})`, offset: .6, opacity: 1},
        {transform: `translate(${dx}px, ${dy}px) rotate(0deg) scale(${s}, ${hr.height / r.height})`, opacity: 0}
      ], {duration: 620, easing: 'cubic-bezier(.4,.1,.2,1)'});
      fly.remove();
      held.style.opacity = '';
      await anim(held, [{transform: 'scale(.98) rotate(-1deg)'}, {transform: 'none'}], {duration: 220, easing: 'ease-out'});
      held.getAnimations().forEach((a) => a.cancel());
    } else {
      card.dataset.pulled = '';
      hold.classList.add('on');
    }
    held.focus({preventScroll: true});
    hold.querySelector('[data-pc-close]').addEventListener('click', putBack);
    hold.querySelector('[data-pc-share]').addEventListener('click', () => sharePostcard(record));
    hold.querySelector('[data-pc-delete]').addEventListener('click', () => askDelete(true));
    hold.querySelector('[data-pc-keep]').addEventListener('click', () => askDelete(false));
    hold.querySelector('[data-pc-confirm]').addEventListener('click', () => removeHeld(id));
    hold.querySelector('.pc-hold-dim').addEventListener('click', putBack);
    hold.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); if (!hold.querySelector('.pc-confirm').hidden) askDelete(false); else putBack(); } if (e.key === 'Tab') { e.preventDefault(); const bs = [...hold.querySelectorAll('button')].filter((b) => b.offsetParent); const i = bs.indexOf(document.activeElement); bs[(i + (e.shiftKey ? -1 : 1) + bs.length) % bs.length]?.focus(); } });
    // 손에 든 느낌 — 포인터를 따라 아주 조금 기운다
    if (!reduce.matches) hold.addEventListener('pointermove', (e) => {
      const b = held.getBoundingClientRect();
      const x = (e.clientX - (b.left + b.width / 2)) / b.width, y = (e.clientY - (b.top + b.height / 2)) / b.height;
      held.style.transform = `rotateY(${(x * 7).toFixed(2)}deg) rotateX(${(-y * 6).toFixed(2)}deg)`;
    });
  }

  async function putBack() {
    if (!holding || holding.closing) return;
    holding.closing = true;
    const {card, hold, held, kind, tilt} = holding;
    if (!reduce.matches) {
      const r = card.getBoundingClientRect(), hr = held.getBoundingClientRect();
      const fly = document.createElement('div');
      fly.className = 'pc-fly';
      Object.assign(fly.style, {left: hr.left + 'px', top: hr.top + 'px', width: hr.width + 'px', height: hr.height + 'px', background: getComputedStyle(held).backgroundImage, borderRadius: '4px', boxShadow: '0 30px 60px -18px #1b0f0599', transformOrigin: '0 0'});
      held.style.visibility = 'hidden';
      document.body.append(fly);
      hold.classList.remove('on');
      await anim(fly, [
        {transform: 'none'},
        {transform: `translate(${r.left - hr.left}px, ${r.top - hr.top - 14}px) scale(${r.width / hr.width}, ${r.height / hr.height}) rotate(${tilt})`}
      ], {duration: 520, easing: 'cubic-bezier(.5,0,.2,1)'});
      delete card.dataset.pulled;
      fly.remove();
      await anim(card, [{transform: `translateY(-14px) rotate(calc(${tilt} * -1)) scale(1.03)`}, {transform: 'translateY(2px)', offset: .7}, {transform: 'none'}], {duration: 300, easing: 'ease-out'});
      card.getAnimations().forEach((a) => a.cancel());
      if (kind === 'pin') {
        const r2 = card.getBoundingClientRect();
        const pin = document.createElement('span'); pin.className = 'pc-pin';
        Object.assign(pin.style, {left: (r2.left + r2.width / 2 - 10) + 'px', top: (r2.top - 9) + 'px'});
        document.body.append(pin);
        await anim(pin, [{transform: 'translateY(-30px) scale(1.25)', opacity: 0}, {transform: 'none', opacity: 1}], {duration: 220, easing: 'cubic-bezier(.5,0,.7,1)'});
        pin.remove();
      }
    } else {
      delete card.dataset.pulled;
    }
    hold.remove();
    card.focus({preventScroll: true});
    holding = null;
  }

  // 엽서 공유 — 엽서 글을 그대로 보낸다 (카카오톡 · 문자 · 이메일 · 복사). 엽서만 따로 여는 공유 주소는 아직 서버에 없어서,
  // 링크 칸에는 내말싸미 첫 화면을 둔다
  /** 엽서 나누기 — 엽서를 그림 한 장으로 그려 보낸다 (postcard-image.js). 받는 분은 보드 위 엽서 모습 그대로 받는다 */
  function sharePostcard(record) {
    const elders = window.Srv?.AUTH?.elders || [], me = elders.find((e) => e.elder_id === record.elder_id);
    const who = me && me.name !== '나' ? window.Srv.honor(me.name) : '';
    const text = postcardBody(record).replace(/\n\s*\n/g, '\n\n').trim();
    const idx = recordData.filter((r) => r.elder_id === record.elder_id).findIndex((r) => r.id === record.id);
    const o = {
      kind: 'postcard', eyebrow: '엽서 나누기', title: record.title,
      card: {kicker: '', title: '', sub: ''},
      message: `${who ? `${who}의 이야기` : '제 이야기'}를 엽서로 나눠요. 「${record.title}」\n— 내말싸미에서 남긴 엽서`,
      link: '',
      status: '',
      note: '엽서가 그림 한 장으로 보내져요. 가족 이야기가 담겨 있으니 믿을 수 있는 분에게만 보내 주세요.',
      extras: [],
      image: {
        name: window.MemoirPostcardImage.fileName(record.title),
        make: async () => {
          const r = await window.MemoirPostcardImage.render({title: record.title, body: text, date: record.date, category: (typeof categories !== 'undefined' && categories[record.category]) || '', icon: record.icon, who, yellow: idx % 4 === 3});
          // 그림에 다 담지 못한 긴 엽서는 함께 보내는 글에 전체를 붙인다
          if (r.clipped) { const box = document.getElementById('share-msg'); if (box && box.value === o.message) box.value = o.message = `${o.message}\n\n「${record.title}」\n${text}`; }
          return r;
        },
      },
    };
    window.MemoirShare.open(o);
  }

  // 6. 엽서 지우기 — 손에 든 엽서 · 보드 위 × · 여러 장 골라 지우기. 늘 한 번 더 묻고, 지운 뒤 잠시 「되돌리기」를 둔다.
  function askDelete(show) {
    if (!holding) return;
    const box = holding.hold.querySelector('.pc-confirm');
    box.hidden = !show;
    holding.held.querySelector('.pc-actions').hidden = show;
    holding.held.classList.toggle('confirming', show);
    (show ? box.querySelector('[data-pc-keep]') : holding.held.querySelector('[data-pc-delete]')).focus();
  }
  async function removeHeld(id) {
    if (!holding || holding.closing) return;
    holding.closing = true;
    const {hold, held, card} = holding;
    if (!reduce.matches) {
      hold.classList.remove('on');
      // 엽서를 반으로 접어 아래로 치운다
      await anim(held, [
        {transform: 'none', opacity: 1},
        {transform: 'perspective(900px) rotateX(-58deg) scale(.82)', opacity: 1, offset: .45},
        {transform: 'perspective(900px) translateY(55vh) rotateX(-70deg) rotate(8deg) scale(.35)', opacity: 0}
      ], {duration: 620, easing: 'cubic-bezier(.5,0,.75,0)'});
      await anim(card.parentElement, [{opacity: 0}, {opacity: 0, transform: 'scale(.6)'}], {duration: 160});
    }
    hold.remove();
    holding = null;
    commitDelete([id]);
  }

  // ── 지우기 공통: 기록에서 빼고, 다시 그리고, 「되돌리기」를 띄운다 ──
  function commitDelete(ids) {
    const removed = [];
    ids.forEach((id) => {
      const index = recordData.findIndex((r) => r.id === id);
      if (index >= 0) removed.push({index, record: recordData[index], picked: state.selected.has(id)});
    });
    removed.sort((a, b) => b.index - a.index).forEach(({index, record}) => { recordData.splice(index, 1); state.selected.delete(record.id); });
    renderRecent(); renderRecords();
    if (typeof updateSelection === 'function') updateSelection();
    document.getElementById('records-heading')?.focus({preventScroll: true});
    const msg = removed.length === 1 ? `「${removed[0].record.title}」 엽서를 지웠어요.` : `엽서 ${removed.length}장을 지웠어요.`;
    const putBack = (list) => { list.sort((a, b) => a.index - b.index).forEach(({index, record, picked}) => { recordData.splice(Math.min(index, recordData.length), 0, record); if (picked) state.selected.add(record.id); }); renderRecent(); renderRecords(); };
    // 서버에서 지우기(DELETE /api/sessions/{id})는 되돌리기 시간이 끝난 뒤에 — 실패한 엽서는 보드에 다시 붙인다
    const commit = async () => {
      if (!window.SrvRecords) return;
      const {failed} = await window.SrvRecords.remove(removed.map((x) => x.record));
      if (!failed.length) return;
      putBack(removed.filter((x) => failed.includes(x.record)));
      toast(failed.length === 1 ? '엽서를 지우지 못했어요. 잠시 뒤 다시 해 주세요.' : `엽서 ${failed.length}장을 지우지 못했어요. 잠시 뒤 다시 해 주세요.`);
    };
    window.MemoirTrash.undo(msg, () => {
      putBack(removed);
      const back = removed.map(({record}) => list.querySelector(`[data-postcard="${record.id}"]`)?.parentElement).filter(Boolean);
      if (!reduce.matches) back.forEach((slot, i) => slot.animate([{opacity: 0, transform: `translateY(-26px) rotate(var(--tilt))`}, {opacity: 1, transform: 'rotate(var(--tilt))'}], {duration: 380, delay: i * 70, easing: 'ease-out', fill: 'backwards'}));
      back[0]?.querySelector('.postcard-card')?.focus({preventScroll: true});
      toast(removed.length === 1 ? '엽서를 보드에 다시 붙였어요.' : `엽서 ${removed.length}장을 보드에 다시 붙였어요.`);
    }, commit);
  }

  // 보드에서 떼어 치우는 연출 — 압정이 빠지고 엽서가 떨어지며 사라진다
  async function dropSlots(slots) {
    if (reduce.matches) return;
    await Promise.all(slots.map((slot, i) => anim(slot, [
      {transform: 'rotate(var(--tilt))', opacity: 1},
      {transform: 'translateY(-12px) rotate(calc(var(--tilt) * -2))', opacity: 1, offset: .3},
      {transform: 'translateY(120px) rotate(14deg) scale(.7)', opacity: 0}
    ], {duration: 520, delay: i * 80, easing: 'cubic-bezier(.5,0,.8,.4)'})));
  }

  // ── 보드 위 엽서를 칸(slot)으로 감싼다 — 고르기 표시 · 떼어 내는 연출의 자리. (엽서마다 붙던 × 는 너저분해서 뺐다)
  function wrap() {
    const cards = [...list.children].filter((el) => el.classList.contains('postcard-card'));
    if (!cards.length) { syncSelectUi(); return; }
    cards.forEach((card) => {
      const slot = document.createElement('div');
      slot.className = 'pc-slot';
      card.replaceWith(slot);
      slot.append(card);
    });
    syncSelectUi();
  }
  new MutationObserver(wrap).observe(list, {childList: true});

  async function removeOne(id) {
    const record = recordData.find((r) => r.id === id);
    if (!record) return;
    const ok = await window.MemoirTrash.confirm({title: '이 엽서를 지울까요?', items: [record.title], desc: '지운 엽서는 보드에서 사라지고, 앞으로 만드는 자서전에도 들어가지 않아요. 이미 만든 책은 그대로예요.', ok: '지우기'});
    if (!ok) { list.querySelector(`[data-pc-remove="${id}"]`)?.focus(); return; }
    await dropSlots([list.querySelector(`[data-postcard="${id}"]`)?.parentElement].filter(Boolean));
    commitDelete([id]);
  }

  // ── 엽서 골라 지우기 (한 장도 여러 장도) ──
  let selecting = false;
  const picked = new Set();
  const toolbar = document.querySelector('[data-screen="records"] .records-toolbar');
  const toggle = document.createElement('button');
  // 「엽서 N장 | 엽서 지우기」 — 개수 옆의 작은 버튼. 켰을 때만 엽서를 골라 지운다 (책장의 「N권 | 책 지우기」와 같은 모양)
  toggle.type = 'button'; toggle.className = 'srv-mini-btn pc-select-toggle';
  toggle.innerHTML = `${icons('check')}<span>엽서 지우기</span>`;
  document.getElementById('selection-count')?.after(toggle);
  void toolbar;
  const visibleIds = () => [...list.querySelectorAll('.pc-slot > .postcard-card')].map((c) => Number(c.dataset.postcard));
  let selectBar = null;
  function ensureBar() {
    if (selectBar) return selectBar;
    selectBar = window.MemoirTrash.selectBar({unit: '엽서', counter: '장', empty: '지울 엽서를 눌러 골라 주세요',
      onAll: () => { const ids = visibleIds(); const all = ids.every((id) => picked.has(id)); ids.forEach((id) => all ? picked.delete(id) : picked.add(id)); syncSelectUi(); },
      onCancel: () => setSelecting(false),
      onDelete: removePicked});
    return selectBar;
  }
  function setSelecting(on) {
    selecting = on; picked.clear();
    list.classList.toggle('pc-selecting', on);
    toggle.setAttribute('aria-pressed', String(on));
    if (on) { ensureBar().show(); window.MemoirTrash.clearUndo(); } else selectBar?.hide();
    syncSelectUi();
    if (on) list.querySelector('.postcard-card')?.focus({preventScroll: true});
  }
  function syncSelectUi() {
    const hasBoard = !!list.querySelector('.pc-slot');
    // 검색 · 분류로 보이는 엽서가 없을 때는 자리만 남기고 숨긴다 — 버튼이 빠지면 검색칸이 옆으로 밀려 다닌다
    const hasAny = (window.currentRecords ? currentRecords().length : 0) > 0 || !!(state.query || state.filter !== 'all');
    toggle.hidden = !hasBoard && !selecting && !hasAny;
    toggle.classList.toggle('pc-toggle-ghost', !hasBoard && !selecting && hasAny);
    if (selecting && !hasBoard && !state.query && state.filter === 'all') { setSelecting(false); return; }
    list.querySelectorAll('.pc-slot').forEach((slot) => {
      const card = slot.querySelector('.postcard-card');
      const on = picked.has(Number(card.dataset.postcard));
      slot.classList.toggle('is-picked', on);
      if (selecting) card.setAttribute('aria-pressed', String(on)); else card.removeAttribute('aria-pressed');
    });
    if (selecting) ensureBar().update(picked.size, visibleIds().length);
  }
  async function removePicked() {
    const ids = [...picked].filter((id) => recordData.some((r) => r.id === id));
    if (!ids.length) return;
    const titles = ids.map((id) => recordData.find((r) => r.id === id).title);
    const ok = await window.MemoirTrash.confirm({title: `엽서 ${ids.length}장을 지울까요?`, items: titles, desc: '지운 엽서는 보드에서 사라지고, 앞으로 만드는 자서전에도 들어가지 않아요. 이미 만든 책은 그대로예요.', ok: `${ids.length}장 지우기`});
    if (!ok) return;
    const slots = ids.map((id) => list.querySelector(`[data-postcard="${id}"]`)?.parentElement).filter(Boolean);
    selectBar?.hide();
    await dropSlots(slots);
    selecting = false; picked.clear(); list.classList.remove('pc-selecting'); toggle.setAttribute('aria-pressed', 'false');
    commitDelete(ids);
  }
  toggle.addEventListener('click', () => setSelecting(!selecting));
  window.addEventListener('memoir:screen', (e) => { if (selecting && e.detail.screen !== 'records') setSelecting(false); });
  document.addEventListener('keydown', (e) => { if (selecting && e.key === 'Escape' && !document.querySelector('dialog[open]')) setSelecting(false); });

  // 원래 엽서 창(dialog) 대신 손에 드는 연출로 연다 — 보드의 엽서만. 홈의 「최근 나눈 이야기」는 그대로.
  list.addEventListener('click', (event) => {
    const x = event.target.closest('#record-list .pc-x');
    if (x) { event.preventDefault(); event.stopImmediatePropagation(); if (!selecting) removeOne(Number(x.dataset.pcRemove)); return; }
    const card = event.target.closest('#record-list .pc-slot > .postcard-card');
    if (!card) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (selecting) { const id = Number(card.dataset.postcard); if (picked.has(id)) picked.delete(id); else picked.add(id); syncSelectUi(); return; }
    pull(card);
  }, true);
  wrap();

  /* ── 검색하며 글자를 칠 때 검색칸이 위아래로 튀지 않게 ──
       결과가 줄면 보드가 짧아져 페이지 끝이 올라오고, 브라우저가 스크롤을 끌어올려 검색칸이 움직인다.
       그때 모자라는 만큼만 보드 높이를 붙잡고 스크롤을 제자리로 돌린다. 검색어를 지우면 놓는다. */
  let keepY = null;
  document.addEventListener('input', (e) => { if (e.target.id === 'record-search') keepY = scrollY; }, true);
  document.addEventListener('input', (e) => {
    if (e.target.id !== 'record-search' || keepY === null) return;
    const y = keepY; keepY = null;
    if (!e.target.value.trim()) { list.style.minHeight = ''; return; }
    const lack = y + innerHeight - document.documentElement.scrollHeight;
    if (lack > 0) list.style.minHeight = `${list.offsetHeight + lack}px`;
    if (Math.abs(scrollY - y) > 1) scrollTo({top: y, behavior: 'instant'});
  });
  window.addEventListener('memoir:screen', (e) => { if (e.detail.screen !== 'records') list.style.minHeight = ''; });
}());
