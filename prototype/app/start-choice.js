(function () {
  'use strict';
  // 1. 「내 이야기 녹음」과 「초대 주소 만들기」를 처음부터 나눈다(B안으로 결정).
  //    「내 이야기 시작하기」를 누르면 둘 중 하나를 고르는 화면(start)이 나온다.
  //    초대는 「초대 주소 만들기」 화면(invite-setup)으로 간다. 주소 발급 · 목록은 기존 RolePreview 그대로.
  const topics = ['어린 시절', '가족', '삶과 일'];
  const main = document.querySelector('main');
  let pendingInvite = false;

  function addScreen(name, title) {
    const s = document.createElement('section');
    s.className = 'screen sc-screen'; s.dataset.screen = name; s.hidden = true;
    s.innerHTML = `<h1 id="${name}-heading" tabindex="-1">${title}</h1><div class="sc-content"></div>`;
    main.append(s); return s;
  }
  const invite = addScreen('invite-setup', '초대 주소 만들기');
  const start = addScreen('start', '어떻게 시작할까요?');
  const self = addScreen('start-self', '어떤 이야기를 들려주실까요?');

  // ── 처음가기 시작 카드 ──
  const hero = document.querySelector('[data-screen="home"] .hero-copy');
  const cta = hero?.querySelector('.hero-cta');
  if (cta) cta.dataset.go = 'start';

  function renderStart() {
    start.querySelector('.sc-content').innerHTML = `<p class="sc-intro">누구의 이야기를 담을지에 따라 길이 달라요. 나중에 언제든 다른 쪽도 할 수 있어요.</p>
      <div class="sc-choices">
        <button type="button" class="sc-choice" data-start="self"><span class="sc-choice-icon">${icons('mic')}</span>
          <strong>제가 직접 들려줄게요</strong><span>이 기기에서 바로 이야기를 녹음해요. 질문에 답하듯 편하게 말씀하시면 돼요.</span>
          <em>녹음 시작하기 ${icons('arrow')}</em></button>
        <button type="button" class="sc-choice" data-start="invite"><span class="sc-choice-icon">${icons('letter')}</span>
          <strong>다른 분의 이야기를 담을게요</strong><span>부모님 · 가족에게 초대 주소를 보내요. 받은 분이 휴대폰으로 이야기를 들려주세요.</span>
          <em>초대 주소 만들기 ${icons('arrow')}</em></button>
      </div>
      <button type="button" class="text-button sc-back" data-go="home">${icons('arrow', 'flip')} 처음가기로</button>`;
  }

  // 내 이야기 녹음 — 초대 만들기처럼 이야기 주제를 먼저 고른다
  let selfTopic = topics[0];
  function renderSelf() {
    self.querySelector('.sc-content').innerHTML = `<p class="sc-intro">오늘 들려주실 이야기의 주제를 골라 주세요. 주제에 맞춰 첫 질문을 드려요.<br><b>「나」의 이야기</b>로 저장돼요. 다른 분의 이야기는 「초대 주소 만들기」로 담아 주세요.</p>
      <form class="panel sc-invite-form sc-self-form" novalidate>
        <fieldset><legend>이야기 주제</legend>
          <div class="sc-chips" role="group" aria-label="주제">${topics.map((t) => `<label class="sc-chip"><input type="radio" name="topic" value="${t}" ${t === selfTopic ? 'checked' : ''}><span>${t}</span></label>`).join('')}</div></fieldset>
        <button type="submit" class="button primary sc-make">${icons('mic')}<span>녹음 시작하기</span></button>
        <p class="sc-fine">${window.MemoirGate?.isLoggedIn() ? '버튼을 누르면 마이크를 써도 되는지 여쭤봐요.' : '녹음은 로그인한 뒤에 할 수 있어요. 버튼을 누르면 로그인 창이 먼저 열려요.'}</p>
      </form>
      <div class="sc-links"><button type="button" class="text-button" data-go="start">${icons('arrow', 'flip')} 돌아가기</button></div>`;
    const form = self.querySelector('form');
    form.addEventListener('change', () => { selfTopic = form.querySelector('input[name="topic"]:checked')?.value || topics[0]; });
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      selfTopic = form.querySelector('input[name="topic"]:checked')?.value || topics[0];
      window.RolePreview.beginSelf(selfTopic);
    });
  }

  function renderInvite() {
    const data = window.RolePreview.store.snapshot();
    const others = data.elders.filter((e) => e.name !== '나');
    invite.querySelector('.sc-content').innerHTML = `<p class="sc-intro">이야기를 들려주실 분에게 보낼 주소를 만들어요. 주소를 받은 분은 휴대폰에서 바로 이야기를 시작할 수 있어요.</p>
      <form class="panel sc-invite-form" novalidate>
        <fieldset><legend><span class="sc-step">1</span>누구에게 보낼까요?</legend>
          ${others.length ? `<div class="sc-chips" role="group" aria-label="등록한 분">${others.map((e, i) => `<label class="sc-chip"><input type="radio" name="who" value="${escapeText(e.elder_id)}" ${i === 0 ? 'checked' : ''}><span>${escapeText(e.name)}</span></label>`).join('')}<label class="sc-chip"><input type="radio" name="who" value="__new" ${others.length ? '' : 'checked'}><span>새로 적기</span></label></div>` : '<input type="hidden" name="who" value="__new">'}
          <label class="sc-name" ${others.length ? 'hidden' : ''}><span>부르는 이름</span><input name="name" maxlength="30" autocomplete="off" placeholder="예: 어머니, 김순자"></label>
          ${others.length ? `<button type="button" class="text-button sc-manage" data-role="manage-elders">${icons('pen')}<span>이름 고치기 · 지우기</span></button>` : ''}
          <p class="sc-error" role="status"></p></fieldset>
        <fieldset><legend><span class="sc-step">2</span>어떤 이야기를 여쭤볼까요?</legend>
          <div class="sc-chips" role="group" aria-label="주제">${topics.map((t, i) => `<label class="sc-chip"><input type="radio" name="topic" value="${t}" ${i === 0 ? 'checked' : ''}><span>${t}</span></label>`).join('')}</div></fieldset>
        <button type="submit" class="button primary sc-make">${icons('letter')}<span>초대 주소 만들기</span></button>
        <p class="sc-fine">${window.MemoirGate?.isLoggedIn() ? '' : '초대 주소는 로그인한 뒤에 만들 수 있어요. 버튼을 누르면 로그인 창이 먼저 열려요.'}</p>
      </form>
      <div class="sc-links"><button type="button" class="text-button" data-go="invitations">이미 보낸 초대 보기 ${icons('chevron')}</button>
        <button type="button" class="text-button" data-go="start">${icons('arrow', 'flip')} 돌아가기</button></div>`;
    const form = invite.querySelector('form');
    form.addEventListener('change', () => {
      const who = form.querySelector('input[name="who"]:checked')?.value || form.who?.value;
      form.querySelector('.sc-name').hidden = who !== '__new';
    });
    form.addEventListener('submit', (e) => { e.preventDefault(); make(form); });
  }

  async function make(form) {
    if (!window.MemoirGate?.isLoggedIn()) { pendingInvite = true; window.MemoirLogin.open(); toast('로그인한 뒤 초대 주소를 만들어 주세요.'); return; }
    const err = form.querySelector('.sc-error');
    const who = form.querySelector('input[name="who"]:checked')?.value || form.querySelector('input[name="who"]')?.value;
    const topic = form.querySelector('input[name="topic"]:checked')?.value || topics[0];
    let elderId = who;
    if (who === '__new') {
      const name = form.querySelector('input[name="name"]').value.trim();
      if (!name) { err.textContent = '부르는 이름을 적어 주세요.'; form.querySelector('input[name="name"]').focus(); return; }
      if (name === '나') { err.textContent = '내 이야기는 「내 이야기 녹음하기」로 바로 시작할 수 있어요.'; return; }
      const existing = window.RolePreview.store.snapshot().elders.find((e) => e.name === name);
      if (existing) elderId = existing.elder_id;
      else {
        const btn = form.querySelector('.sc-make'); if (btn.disabled) return; btn.disabled = true;
        const r = await window.RolePreview.store.addElder(name); btn.disabled = false;
        if (!r.ok) { err.textContent = r.error === 'server' ? '지금은 등록하지 못했어요. 잠시 뒤 다시 눌러 주세요.' : '이름을 확인해 주세요.'; return; }
        elderId = r.elder.elder_id;
      }
    }
    window.RolePreview.issueFor(elderId, topic);
  }

  document.addEventListener('click', (event) => {
    const b = event.target.closest('[data-start]');
    if (!b) return;
    event.preventDefault();
    if (b.dataset.start === 'self') navigate('start-self');
    else navigate('invite-setup');
  });
  window.addEventListener('memoir:screen', (event) => {
    if (event.detail.screen === 'start' && start) renderStart();
    if (event.detail.screen === 'start-self') renderSelf();
    if (event.detail.screen === 'invite-setup') renderInvite();
  });
  window.addEventListener('memoir:preview-auth', (event) => {
    if (event.detail.authenticated && pendingInvite) {
      pendingInvite = false; window.MemoirLogin.close();
      const form = invite.querySelector('form');
      if (form && location.hash === '#invite-setup') { form.querySelector('.sc-fine').textContent = ''; make(form); }
    }
  });
  if (location.hash === '#invite-setup') { navigate('invite-setup'); }
  if (location.hash === '#start' && start) { navigate('start'); }
  if (location.hash === '#start-self') { navigate('start-self'); }
}());
