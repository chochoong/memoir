(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     srv-links — 어르신이 초대 링크(https://<주소>/i#<토큰>)로 들어온 화면
       · 시안의 「초대 이야기」 화면(invite) 모양 그대로. 메뉴 · 로그인은 보이지 않는다.
       · 들어오면 GET /api/i/preview — 아무것도 바꾸지 않는다 (몇 번 열어도 같다).
       · 「이야기 시작하기」를 누를 때만 POST /api/i/start → 같은 라디오 스튜디오 화면에서 인터뷰.
       · 마치면 GET /api/i/transcript 로 나눈 이야기를 읽기 전용으로 보여 준다.
       · 토큰은 srv-core 가 주소창에서 지우고 헤더(X-Interview-Token)로만 보낸다. 화면 · 로그에 찍지 않는다.
     ═══════════════════════════════════════════════════════════════ */
  const {api, LINK, LINK_SAYS, THEME_LABEL, linkStateOf} = window.Srv;
  if (!LINK.on) { window.SrvLinks = null; return; }
  const entry = document.querySelector('[data-screen="invite"]');
  const content = entry.querySelector('.role-content');
  const h1 = entry.querySelector('h1');
  let preview = null, busy = false;

  // 시안의 탭 안 초대 흉내를 끄고, 이 화면을 손님 화면으로 고정한다
  const RP = window.RolePreview;
  RP.isGuest = () => true;
  RP.isInviteHash = () => false;
  RP.canEnterInterview = () => !!window.SrvInterview?.busy();
  document.body.classList.add('role-guest');
  const fin = document.getElementById('finish-description');
  if (fin) fin.textContent = '지금까지 들려주신 이야기는 저장돼요. 마치면 나눈 이야기를 보여 드려요.';

  const topicOf = (p) => String((p && (p.topic || THEME_LABEL[p.theme])) || '살아온 이야기');
  function paint(stateKey, extra = '') {
    const say = LINK_SAYS[stateKey] || LINK_SAYS.neterr;
    const canStart = stateKey === 'ready' || stateKey === 'in_progress' || stateKey === 'neterr';
    h1.textContent = stateKey === 'ended' ? '오늘 이야기, 고맙습니다' : canStart && stateKey !== 'neterr' ? '이야기를 들려주세요' : '이 주소로는 시작할 수 없어요';
    content.innerHTML = `<div class="panel role-guest-card"><span class="eyebrow">내말싸미 · 이야기 초대</span>
      <h2>${escapeText(say.h)}</h2>
      ${say.topic && preview ? `<p class="role-guest-topic">「${escapeText(topicOf(preview))}」</p>` : ''}
      <p>${escapeText(say.p)}</p>
      ${say.btn ? `<button type="button" class="button primary role-main-action" data-link-start>${escapeText(say.btn)} ${icons('arrow')}</button>` : ''}
      </div>${extra}`;
    h1.focus({preventScroll: true});
  }

  async function load() {
    show('invite');
    content.innerHTML = '<div class="panel role-guest-card"><p>초대를 확인하고 있어요…</p></div>';
    if (!LINK.token) { paint('invalid_link'); return; }
    try {
      preview = await api.linkPreview();
      LINK.preview = preview;
      if (preview.state === 'ended') { await showTranscript(); return; }
      paint(LINK_SAYS[preview.state] ? preview.state : 'neterr');
    } catch (e) { paint(linkStateOf(e)); }
  }

  async function startTalk() {
    if (busy) return;
    busy = true;
    const btn = content.querySelector('[data-link-start]');
    if (btn) btn.disabled = true;
    // 말하는 화면을 먼저 연다 — 마이크 허락 · 첫 질문이 그 위에서 이어진다
    const topic = topicOf(preview);
    const pill = document.querySelector('.studio-topline .pill'); if (pill) pill.textContent = topic;
    const starting = window.SrvInterview.start({link: true, topic});
    navigate('interview');
    await starting;
    busy = false;
  }

  function failed(e) {
    busy = false;
    show('invite');
    paint(linkStateOf(e));
  }

  async function showTranscript() {
    let t = null;
    try { t = await api.linkTranscript(); } catch (_) { /* 아래 안내 */ }
    const turns = (t && t.turns) || [];
    const story = turns.length
      ? `<article class="panel role-guest-story"><h2>오늘 나눈 이야기</h2><ol class="srv-rv-list">${turns.map((x) => `<li><p class="srv-rv-q">${escapeText(x.question || '(질문 없이 이어진 말씀)')}</p><p class="srv-rv-a">${escapeText(x.answer || '')}</p></li>`).join('')}</ol></article>`
      : '';
    show('invite');
    h1.textContent = '오늘 이야기, 고맙습니다';
    content.innerHTML = `<div class="panel role-guest-card"><span class="eyebrow">내말싸미 · 이야기 초대</span>
      <h2>들려주신 이야기를 잘 받았어요</h2>
      <p>링크를 보내 주신 분이 이 이야기로 엽서와 자서전을 만들 수 있어요. 이 창은 닫으셔도 돼요.</p></div>${story}`;
    h1.focus({preventScroll: true});
  }
  /** 인터뷰가 닫혔다 (srv-interview 가 부른다) — 서버가 기록을 남길 때까지 잠깐 기다렸다 보여 준다 */
  async function done(why) {
    show('invite');
    content.innerHTML = '<div class="panel role-guest-card"><p>나눈 이야기를 정리하고 있어요…</p></div>';
    for (let i = 0; i < 6; i++) {
      try { await api.linkTranscript(); break; } catch (e) { if (e.code !== 'not_ended') break; await new Promise((r) => setTimeout(r, 800)); }
    }
    if (why === 'gone') { paint('interrupted'); return; }
    await showTranscript();
  }

  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-link-start]');
    if (!b) return;
    e.preventDefault();
    if (b.textContent.includes(LINK_SAYS.neterr.btn) && !preview) { void load(); return; }
    void startTalk();
  });

  // 같은 창에서 다른 초대 링크(#토큰)를 열면 주소만 바뀌고 화면은 그대로다 — 새로 읽는다
  const SCREENS = ['home', 'interview', 'invite', 'records', 'library', 'style', 'draft', 'reader', 'prepare', 'invitations', 'start', 'start-self', 'invite-setup'];
  window.addEventListener('hashchange', () => { const h = location.hash.slice(1); if (h && !SCREENS.includes(h)) location.reload(); });
  // 어르신이 인터뷰를 중단했다 — 초대 화면으로 (링크는 이미 시작했으니 다시 시작할 수 없다)
  function left() {
    show('invite');
    h1.textContent = '인터뷰를 중단했어요';
    content.innerHTML = `<div class="panel role-guest-card"><span class="eyebrow">내말싸미 · 이야기 초대</span><h2>이야기를 저장하지 않고 마쳤어요</h2>
      <p>이 링크로는 다시 시작할 수 없어요. 다시 이야기하시려면 링크를 보내 주신 분께 새 링크를 부탁해 주세요.</p></div>`;
    h1.focus({preventScroll: true});
  }
  window.SrvLinks = {failed, done, left};
  void load();
}());
