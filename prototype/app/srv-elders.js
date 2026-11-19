(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     srv-elders — 이야기 주인공 「이름 추가 · 수정하기」 창
       · 「초대 주소 만들기」의 「누구에게 보낼까요?」 옆 · 「누구의 기록을 볼까요?」 창에서 연다.
       · 맨 위: 이름 입력 + 추가하기 (같은 이름은 저장하지 않는다). 그 아래 이름 태그 — 누르면 맨 아래에 수정 바
         (예전 이름이 적힌 칸 + 수정하기 + 취소), 같은 태그를 다시 누르면 닫힌다.
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
    <span class="eyebrow">이야기 주인공</span><h2 id="elder-manage-title">이름 추가 · 수정하기</h2>
    <p class="small-copy em-lead">이름을 바꿔도 그분의 엽서와 자서전은 그대로 이어져요.</p>
    <div class="em-add"><label class="visually-hidden" for="em-add-input">추가할 이름</label>
      <input id="em-add-input" maxlength="30" autocomplete="off" placeholder="예: 어머니, 김순자">
      <button type="button" class="button primary compact" data-em="add">${icons('plus')}<span>추가하기</span></button></div>
    <p class="em-msg em-add-msg" role="status"></p>
    <div class="em-tags" role="group" aria-label="등록한 이름 — 누르면 고칠 수 있어요"></div>
    <div class="em-edit" hidden>
      <label class="em-edit-label" for="em-edit-input"></label>
      <div class="em-edit-row"><input id="em-edit-input" maxlength="30" autocomplete="off">
        <button type="button" class="button primary compact" data-em="save">수정하기</button>
        <button type="button" class="button outline compact" data-em="cancel">취소</button></div>
      <button type="button" class="text-button em-del" data-em="del">${icons('close')}<span>이 이름 지우기</span></button>
      <p class="em-msg em-edit-msg" role="status"></p>
    </div>`;
  document.body.append(dialog);
  const tags = dialog.querySelector('.em-tags'), edit = dialog.querySelector('.em-edit');
  const addInput = dialog.querySelector('#em-add-input'), editInput = dialog.querySelector('#em-edit-input');
  const addMsg = dialog.querySelector('.em-add-msg'), editMsg = dialog.querySelector('.em-edit-msg');
  const say = (el, t, bad) => { el.textContent = t || ''; el.classList.toggle('bad', !!bad); };
  const WHY = {
    unsupported: '서버가 아직 이 기능을 지원하지 않아요. 서버가 준비되면 바로 쓸 수 있어요.',
    duplicate_name: '이미 같은 이름이 있어요. 다른 이름으로 적어 주세요.',
    invalid_name: '이름을 적어 주세요.',
    self: '「나」는 내 이야기를 담는 자리라 쓸 수 없는 이름이에요.',
    elder_not_found: '이 이야기 주인공을 찾을 수 없어요. 창을 닫고 다시 열어 주세요.',
    has_records: '이분의 기록이 남아 있어 지울 수 없어요. 이름만 바꿀 수 있어요.',
    server: '지금은 처리하지 못했어요. 잠시 뒤 다시 해 주세요.',
  };
  let editing = null; // 고치는 중인 elder_id
  // 받침에 따라 은/는 · 을/를 (한글이 아니면 뒤엣것)
  const josa = (w, pair) => { const c = w.charCodeAt(w.length - 1) - 0xac00; return w + ((c >= 0 && c < 11172 && c % 28) ? pair[0] : pair[1]); };
  const q = (name, pair) => `「${name}」` + (josa(name, pair).slice(name.length));
  const dupMsg = (name) => `${q(name, '은는')} 이미 있는 이름이에요. 같은 이름은 저장할 수 없어요.`;
  const others = () => store.snapshot().elders.filter((e) => e.name !== SELF);
  const nameOf = (id) => store.snapshot().elders.find((e) => e.elder_id === id)?.name || '';
  // 같은 이름(앞뒤 빈칸 무시) — 「나」도 쓸 수 없다
  const taken = (name, exceptId) => name === SELF || store.snapshot().elders.some((e) => e.name === name && e.elder_id !== exceptId);

  function render() {
    const list = others();
    tags.innerHTML = list.length
      ? list.map((e) => `<button type="button" class="em-tag" data-tag="${escapeText(e.elder_id)}" aria-pressed="${e.elder_id === editing}">${escapeText(e.name)}</button>`).join('')
      : '<p class="em-empty">아직 등록한 이름이 없어요. 위 칸에 적고 「추가하기」를 눌러 주세요.</p>';
    if (editing && !list.some((e) => e.elder_id === editing)) closeEdit();
  }
  function openEdit(id) {
    editing = id;
    edit.querySelector('.em-edit-label').textContent = `「${nameOf(id)}」 이름 고치기`;
    editInput.value = nameOf(id);
    edit.querySelectorAll('.em-blocked').forEach((x) => x.remove());
    say(editMsg, '');
    edit.hidden = false;
    render();
    editInput.focus(); editInput.select();
  }
  function closeEdit() {
    editing = null; edit.hidden = true; say(editMsg, '');
    edit.querySelectorAll('.em-blocked').forEach((x) => x.remove());
    tags.querySelectorAll('[aria-pressed="true"]').forEach((t) => t.setAttribute('aria-pressed', 'false'));
  }
  function refreshScreens() {
    // 지금 화면을 다시 그린다 — 처음가기 「이야기 주인공」 줄 · 엽서 · 자서전 제목의 이름이 함께 바뀐다
    const here = location.hash.slice(1) || 'home';
    if (here !== 'interview') show(here);
    window.RolePreview?.renderIdentity?.();
  }
  function open() {
    if (!store.snapshot().user) { window.MemoirLogin.open(); return; }
    closeEdit(); addInput.value = ''; say(addMsg, '');
    render();
    if (!dialog.open) dialog.showModal();
    addInput.focus();
  }

  async function add() {
    const name = addInput.value.trim();
    if (!name) { say(addMsg, WHY.invalid_name, true); addInput.focus(); return; }
    if (taken(name)) { say(addMsg, name === SELF ? WHY.self : dupMsg(name), true); addInput.focus(); addInput.select(); return; }
    const btn = dialog.querySelector('[data-em="add"]'); btn.disabled = true; say(addMsg, '추가하는 중이에요…');
    const r = await store.addElder(name);
    btn.disabled = false;
    if (!r.ok) { say(addMsg, r.error === 'duplicate_name' ? dupMsg(name) : (WHY[r.error] || WHY.server), true); addInput.focus(); return; }
    addInput.value = '';
    say(addMsg, `${q(r.elder.name, '을를')} 추가했어요.`);
    window.MemoirElders.lastAdded = r.elder.elder_id; // 초대 화면이 이 이름을 골라 둔다
    render(); refreshScreens();
    addInput.focus();
  }

  async function save() {
    const id = editing; if (!id) return;
    const name = editInput.value.trim();
    if (!name) { say(editMsg, WHY.invalid_name, true); editInput.focus(); return; }
    if (name === nameOf(id)) { say(editMsg, '바뀐 이름이 없어요.'); return; }
    if (taken(name, id)) { say(editMsg, name === SELF ? WHY.self : dupMsg(name), true); editInput.focus(); editInput.select(); return; }
    const btn = edit.querySelector('[data-em="save"]'); btn.disabled = true; say(editMsg, '저장하는 중이에요…');
    const r = await store.renameElder(id, name);
    btn.disabled = false;
    if (!r.ok) { say(editMsg, WHY[r.error] || WHY.server, true); editInput.focus(); return; }
    closeEdit();
    say(addMsg, `이름을 바꿨어요 → 「${r.elder.name}」. 엽서와 자서전도 새 이름으로 보여요.`);
    render(); refreshScreens();
  }
  /** 지울 수 없을 때 — 수정 바 안에 상자로: 무엇이 남아 있는지 · 왜 못 지우는지 */
  function blocked(name, stats) {
    edit.querySelectorAll('.em-blocked').forEach((x) => x.remove());
    const box = document.createElement('div');
    box.className = 'em-blocked'; box.setAttribute('role', 'alert');
    box.innerHTML = `<div class="emb-head">${icons('book')}<strong>${escapeText(window.Srv.honor(name))}은 지울 수 없어요</strong></div>
      <p class="emb-sub">이분의 기록이 남아 있어요</p>
      <ul class="emb-stats">${stats.map(([ic, label, n, unit]) => `<li>${icons(ic)}<span>${label}</span><b>${n}${unit}</b></li>`).join('')}</ul>
      <p class="emb-why">기록을 잃지 않도록, 기록이 있는 분은 지우지 않고 <b>이름만 바꿀 수 있어요.</b></p>`;
    edit.append(box);
    box.scrollIntoView({block: 'nearest'});
  }
  async function remove() {
    const id = editing; if (!id) return;
    edit.querySelectorAll('.em-blocked').forEach((x) => x.remove());
    const name = nameOf(id);
    if (window.SrvInterview?.busy() && window.RolePreview?.currentElderId?.() === id) { say(editMsg, '이분과 인터뷰 중이에요. 인터뷰를 마친 뒤 지워 주세요.', true); return; }
    say(editMsg, '이분의 기록을 확인하고 있어요…');
    const n = await store.elderRecords(id);
    if (!n) { say(editMsg, WHY.server, true); return; }
    const stats = [['letter', '엽서', n.postcards, '장'], ['pen', '엽서 전 이야기', n.stories, '개'], ['book', '자서전', n.memoirs, '권'], ['share', '보낸 초대', n.links, '개']].filter((x) => x[2]);
    say(editMsg, '');
    if (stats.length) { blocked(name, stats); return; }
    dialog.close();
    const yes = await window.MemoirTrash.confirm({title: '이 이야기 주인공을 지울까요?', items: [name], desc: '아직 남긴 기록이 없는 분이에요. 지우면 목록에서 사라져요.', ok: '지우기', keep: '그대로 두기'});
    dialog.showModal();
    if (!yes) return;
    const r = await store.deleteElder(id);
    if (!r.ok) { say(editMsg, WHY[r.error] || WHY.server, true); return; }
    closeEdit();
    say(addMsg, `「${name}」 — 지웠어요.`);
    render(); refreshScreens();
    window.SrvRecords?.reload(); window.SrvLibrary?.reload();
  }

  dialog.addEventListener('click', (e) => {
    const t = e.target.closest('[data-tag]');
    // 태그를 누르면 아래에 수정 바, 같은 태그를 다시 누르면 닫힌다
    if (t) { if (editing === t.dataset.tag) { closeEdit(); t.focus(); } else openEdit(t.dataset.tag); return; }
    const b = e.target.closest('[data-em]');
    if (!b) return;
    if (b.dataset.em === 'add') void add();
    if (b.dataset.em === 'save') void save();
    if (b.dataset.em === 'cancel') { const id = editing; closeEdit(); tags.querySelector(`[data-tag="${CSS.escape(id || '')}"]`)?.focus(); }
    if (b.dataset.em === 'del') void remove();
  });
  dialog.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229) return;
    if (e.target === addInput) { e.preventDefault(); void add(); }
    if (e.target === editInput) { e.preventDefault(); void save(); }
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
    <button type="button" class="text-button ep-manage" data-role="manage-elders">${icons('pen')}<span>이름 추가 · 수정하기</span></button>`;
  document.body.append(picker);
  function openPicker() {
    const data = store.snapshot();
    if (!data.user) { window.MemoirLogin.open(); return; }
    const box = picker.querySelector('.ep-list');
    box.innerHTML = data.elders.length ? data.elders.map((e) => `<button type="button" class="button outline" data-pick="${escapeText(e.elder_id)}" aria-pressed="${e.elder_id === data.selectedElderId}">${escapeText(e.name === SELF ? '나 (내 이야기)' : e.name)}</button>`).join('')
      : '<p class="small-copy">아직 이야기 주인공이 없어요. 「이야기 시작하기」로 첫 이야기를 남겨 주세요.</p>';
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

  window.MemoirElders = Object.assign(window.MemoirElders || {}, {open, pick: openPicker});
}());
