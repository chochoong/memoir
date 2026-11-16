(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     srv-elders — 이야기 주인공 이름 고치기 · 지우기 창
       · 「이야기 준비」 화면의 「이름 고치기 · 지우기」에서 연다.
       · 이름 바꾸기: PATCH /api/elders/{id}. 엽서 · 자서전은 elder_id 에 묶여 있어 그대로 따라온다.
       · 지우기: 엽서 · 엽서 전 이야기 · 자서전 · 아직 쓸 수 있는 초대가 하나라도 있으면 막는다(기록을 잃지 않게).
         아무 기록이 없을 때만 한 번 더 물은 뒤 DELETE /api/elders/{id}.
       · 「나」(내 이야기)는 바꾸거나 지울 수 없다. 진행 중인 인터뷰의 주인공도 지울 수 없다.
       · 서버에 아직 이 API 가 없으면 「서버 준비 중」으로 알린다 (README 「서버에 요청한 API」).
     ═══════════════════════════════════════════════════════════════ */
  const store = window.SrvStore;
  const SELF = '나';
  const dialog = document.createElement('dialog');
  dialog.className = 'review-dialog elder-manage-dialog';
  dialog.setAttribute('aria-labelledby', 'elder-manage-title');
  dialog.innerHTML = `<form method="dialog"><button class="dialog-close" aria-label="닫기">${icons('close')}</button></form>
    <span class="eyebrow">이야기 주인공</span><h2 id="elder-manage-title">이름 고치기 · 지우기</h2>
    <p class="small-copy em-lead">이름을 바꿔도 그분의 엽서와 자서전은 그대로 이어져요.</p>
    <ul class="em-list"></ul>
    <p class="em-msg" role="status"></p>`;
  document.body.append(dialog);
  const list = dialog.querySelector('.em-list'), msg = dialog.querySelector('.em-msg');
  const say = (t, bad) => { msg.textContent = t || ''; msg.classList.toggle('bad', !!bad); };
  const WHY = {
    unsupported: '서버가 아직 이 기능을 지원하지 않아요. 서버가 준비되면 바로 쓸 수 있어요.',
    duplicate_name: '이미 같은 이름의 이야기 주인공이 있어요.',
    invalid_name: '이름을 적어 주세요.',
    self: '「나」는 내 이야기를 담는 자리라 바꾸거나 지울 수 없어요.',
    elder_not_found: '이 이야기 주인공을 찾을 수 없어요. 창을 닫고 다시 열어 주세요.',
    has_records: '이분의 기록이 남아 있어 지울 수 없어요. 이름만 바꿀 수 있어요.',
    server: '지금은 처리하지 못했어요. 잠시 뒤 다시 해 주세요.',
  };

  function render() {
    const data = store.snapshot();
    list.innerHTML = data.elders.map((e) => {
      const self = e.name === SELF;
      return `<li class="em-row" data-elder="${escapeText(e.elder_id)}">
        <label class="em-name"><span class="visually-hidden">${escapeText(e.name)} 이름</span>
          <input value="${escapeText(e.name)}" maxlength="30" autocomplete="off" ${self ? 'disabled' : ''}></label>
        ${self ? '<span class="em-self">내 이야기</span>' : `<button type="button" class="button outline compact" data-em="save">이름 저장</button>
        <button type="button" class="text-button em-del" data-em="del">${icons('close')}<span>지우기</span></button>`}
      </li>`;
    }).join('') || '<li class="em-empty">등록한 이야기 주인공이 없어요.</li>';
  }
  function refreshScreens() {
    // 지금 화면을 다시 그린다 — 처음가기 「이야기 주인공」 줄 · 엽서 · 자서전 제목의 이름이 함께 바뀐다
    const here = location.hash.slice(1) || 'home';
    if (here !== 'interview') show(here);
    window.RolePreview?.renderIdentity?.();
  }
  function open() {
    if (!store.snapshot().user) { window.MemoirLogin.open(); return; }
    render(); say('');
    if (!dialog.open) dialog.showModal();
    list.querySelector('input:not([disabled])')?.focus();
  }

  async function save(row) {
    const id = row.dataset.elder, input = row.querySelector('input'), btn = row.querySelector('[data-em="save"]');
    btn.disabled = true; say('저장하는 중이에요…');
    const r = await store.renameElder(id, input.value);
    btn.disabled = false;
    if (!r.ok) {
      say(WHY[r.error] || WHY.server, true);
      // 서버에 저장되지 않은 이름이 저장된 것처럼 남지 않게 되돌린다 (빈칸 · 같은 이름은 고칠 수 있게 둔다)
      if (r.error === 'unsupported' || r.error === 'server' || r.error === 'self') input.value = store.snapshot().elders.find((e) => e.elder_id === id)?.name || input.value;
      input.focus(); return;
    }
    if (!r.changed) { say('바뀐 이름이 없어요.'); return; }
    say(`이름을 바꿨어요 → 「${r.elder.name}」. 엽서와 자서전도 새 이름으로 보여요.`);
    render(); refreshScreens();
  }
  /** 지울 수 없을 때 — 그 사람 줄 바로 아래에 상자로: 무엇이 남아 있는지 · 왜 못 지우는지 · 대신 할 수 있는 것 */
  function blocked(row, name, stats) {
    list.querySelectorAll('.em-blocked').forEach((x) => x.remove());
    const box = document.createElement('div');
    box.className = 'em-blocked'; box.setAttribute('role', 'alert');
    box.innerHTML = `<div class="emb-head">${icons('book')}<strong>${escapeText(window.Srv.honor(name))}은 지울 수 없어요</strong></div>
      <p class="emb-sub">이분의 기록이 남아 있어요</p>
      <ul class="emb-stats">${stats.map(([ic, label, n, unit]) => `<li>${icons(ic)}<span>${label}</span><b>${n}${unit}</b></li>`).join('')}</ul>
      <p class="emb-why">기록을 잃지 않도록, 기록이 있는 분은 지우지 않고 <b>이름만 바꿀 수 있어요.</b></p>
      <div class="emb-actions"><button type="button" class="button outline compact" data-emb="rename">${icons('pen')}<span>이름 바꾸기</span></button><button type="button" class="text-button" data-emb="close">닫기</button></div>`;
    row.after(box);
    box.querySelector('[data-emb="rename"]').addEventListener('click', () => { box.remove(); const i = row.querySelector('input'); i.focus(); i.select(); });
    box.querySelector('[data-emb="close"]').addEventListener('click', () => { box.remove(); row.querySelector('[data-em="del"]')?.focus(); });
    box.scrollIntoView({block: 'nearest'});
  }
  async function remove(row) {
    list.querySelectorAll('.em-blocked').forEach((x) => x.remove());
    const id = row.dataset.elder, name = store.snapshot().elders.find((e) => e.elder_id === id)?.name || '';
    if (window.SrvInterview?.busy() && window.RolePreview?.currentElderId?.() === id) { say('이분과 인터뷰 중이에요. 인터뷰를 마친 뒤 지워 주세요.', true); return; }
    say('이분의 기록을 확인하고 있어요…');
    const n = await store.elderRecords(id);
    if (!n) { say(WHY.server, true); return; }
    const stats = [['letter', '엽서', n.postcards, '장'], ['pen', '엽서 전 이야기', n.stories, '개'], ['book', '자서전', n.memoirs, '권'], ['share', '보낸 초대', n.links, '개']].filter((x) => x[2]);
    say('');
    if (stats.length) { blocked(row, name, stats); return; }
    dialog.close();
    const yes = await window.MemoirTrash.confirm({title: '이 이야기 주인공을 지울까요?', items: [name], desc: '아직 남긴 기록이 없는 분이에요. 지우면 목록에서 사라져요.', ok: '지우기', keep: '그대로 두기'});
    dialog.showModal();
    if (!yes) return;
    const r = await store.deleteElder(id);
    if (!r.ok) { say(WHY[r.error] || WHY.server, true); return; }
    say(`이야기 주인공 「${name}」 — 지웠어요.`);
    render(); refreshScreens();
    window.SrvRecords?.reload(); window.SrvLibrary?.reload();
  }

  dialog.addEventListener('click', (e) => {
    const b = e.target.closest('[data-em]');
    if (!b) return;
    const row = b.closest('.em-row');
    if (b.dataset.em === 'save') void save(row);
    if (b.dataset.em === 'del') void remove(row);
  });
  dialog.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.matches('.em-name input') && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); void save(e.target.closest('.em-row')); }
  });
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-role="manage-elders"]')) { e.preventDefault(); open(); }
  });
  /* ── 「누구의 기록을 볼까요?」 — 엽서보기 · 자서전 보기 제목 옆 「변경」 ──
       기록 · 자서전은 이야기 주인공마다 따로 모인다. 「나」(내 이야기)도 여기서 고른다. */
  const picker = document.createElement('dialog');
  picker.className = 'review-dialog elder-pick-dialog';
  picker.setAttribute('aria-labelledby', 'elder-pick-title');
  picker.innerHTML = `<form method="dialog"><button class="dialog-close" aria-label="닫기">${icons('close')}</button></form>
    <span class="eyebrow">이야기 주인공</span><h2 id="elder-pick-title">누구의 기록을 볼까요?</h2>
    <div class="ep-list" role="group" aria-label="이야기 주인공"></div>
    <button type="button" class="text-button ep-manage" data-role="manage-elders">${icons('pen')}<span>이름 고치기 · 지우기</span></button>`;
  document.body.append(picker);
  function openPicker() {
    const data = store.snapshot();
    if (!data.user) { window.MemoirLogin.open(); return; }
    const box = picker.querySelector('.ep-list');
    box.innerHTML = data.elders.length ? data.elders.map((e) => `<button type="button" class="button outline" data-pick="${escapeText(e.elder_id)}" aria-pressed="${e.elder_id === data.selectedElderId}">${escapeText(e.name === SELF ? '나 (내 이야기)' : e.name)}</button>`).join('')
      : '<p class="small-copy">아직 이야기 주인공이 없어요. 「이야기 시작하기」로 첫 이야기를 남겨 주세요.</p>';
    picker.querySelector('.ep-manage').hidden = !data.elders.some((e) => e.name !== SELF);
    if (!picker.open) picker.showModal();
    box.querySelector('[aria-pressed="true"]')?.focus();
  }
  picker.addEventListener('click', (e) => {
    const b = e.target.closest('[data-pick]');
    if (b) { if (window.RolePreview?.selectElder?.(b.dataset.pick) !== false) picker.close(); return; }
    if (e.target.closest('[data-role="manage-elders"]')) picker.close();
  });
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-role="pick-elder"]')) { e.preventDefault(); e.stopImmediatePropagation(); openPicker(); }
  }, true);
  // 이름을 고치거나 지운 뒤에는 고르던 창도 새 목록으로
  dialog.addEventListener('close', () => { if (location.hash === '#records' || location.hash === '#library') window.RolePreview?.renderIdentity?.(); });

  window.MemoirElders = {open, pick: openPicker};
}());
