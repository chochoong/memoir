(function () {
  'use strict';
  // 로그인 — 시안의 로그인 창 모양 그대로, 안의 버튼만 진짜 구글 로그인으로 바꿨다.
  //   · 앱을 열면 GET /api/auth/me 로 로그인돼 있는지 본다 (msid 쿠키). 401 이면 로그인 전.
  //   · 구글 버튼(팝업) → POST /api/auth/google {credential} → 서버가 쿠키를 심는다.
  //   · 로그아웃은 POST /api/auth/logout 뒤 새로고침 — 화면 메모리를 통째로 비운다.
  //   · ?authMock=ok 로 열면 「Google로 로그인 (모의)」 버튼이 대신 나온다 (서버 없이 흐름만).
  //   · 구글 credential 은 화면 · 로그 어디에도 남기지 않는다.
  const {api, AUTH, CONFIG, AUTH_SAYS} = window.Srv;
  let opener = null, busy = false, note = '', gsiReady = false;

  const dialog = document.createElement('dialog');
  dialog.className = 'memoir-login-dialog';
  dialog.setAttribute('aria-labelledby', 'login-preview-heading');
  dialog.setAttribute('aria-describedby', 'login-preview-description');
  dialog.innerHTML = `
    <div class="mlg-topbar"><span class="mlg-preview-label">내말싸미 로그인</span><button type="button" class="mlg-close" data-login-close aria-label="로그인 창 닫기">${icons('close')}</button></div>
    <div class="mlg-layout">
      <div class="mlg-visual" aria-hidden="true"><span class="mlg-brand">내말싸미</span><img src="book-illustration.svg" alt=""><p>작은 이야기가 모여<br>오래 남는 한 권으로.</p><span class="mlg-visual-rule"></span></div>
      <div class="mlg-main"><h2 id="login-preview-heading" tabindex="-1"></h2><p id="login-preview-description"></p><div class="mlg-content" data-login-content></div></div>
    </div>`;
  document.body.append(dialog);

  const gsiBox = document.createElement('div');
  gsiBox.className = 'mlg-gsi';

  function render() {
    const heading = dialog.querySelector('#login-preview-heading');
    const description = dialog.querySelector('#login-preview-description');
    const content = dialog.querySelector('[data-login-content]');
    if (AUTH.user) {
      const u = AUTH.user;
      heading.textContent = '로그인되어 있어요';
      description.textContent = '모아 둔 엽서와 자서전은 이 계정에만 보관돼요.';
      content.innerHTML = `
        <div class="mlg-account"><span class="mlg-account-avatar" aria-hidden="true">${escapeText((u.name || u.email || 'G').trim().slice(0, 1))}</span><span><strong>${escapeText(u.name || '이름 없음')}</strong><small>${escapeText(u.email || 'Google 계정')}</small></span></div>
        <button type="button" class="button primary mlg-primary" data-login-close>이어서 하기</button>
        <button type="button" class="mlg-secondary" data-login-logout>로그아웃</button>`;
      return;
    }
    heading.textContent = '나의 이야기를 함께 모아요';
    description.textContent = 'Google 계정으로 로그인하면 엽서와 자서전을 모아 둘 수 있어요.';
    content.innerHTML = '';
    content.append(gsiBox);
    content.insertAdjacentHTML('beforeend', `<p class="mlg-fixture-note mlg-msg" role="status">${escapeText(note)}</p>
      <button type="button" class="mlg-secondary" data-login-close>로그인 없이 둘러보기</button>`);
    if (dialog.open) gsiInit();   // 구글 스크립트는 로그인 창을 열 때만 받는다
  }
  function setNote(text) { note = text || ''; const m = dialog.querySelector('.mlg-msg'); if (m) m.textContent = note; }

  function gsiInit() {
    if (AUTH.mock) {
      if (!gsiBox.querySelector('button')) {
        gsiBox.innerHTML = '<button type="button" class="button primary mlg-primary" data-login-google>Google로 로그인 (모의)</button>';
      }
      return;
    }
    if (!CONFIG.auth.googleClientId) { gsiBox.textContent = '구글 로그인 준비 중이에요.'; return; }
    if (gsiReady) return;
    if (document.querySelector('script[data-gsi]')) return;
    const sc = document.createElement('script');
    sc.src = 'https://accounts.google.com/gsi/client'; sc.async = true; sc.defer = true; sc.dataset.gsi = '1';
    sc.onload = () => {
      gsiReady = true;
      window.google.accounts.id.initialize({
        client_id: CONFIG.auth.googleClientId, ux_mode: 'popup',
        callback: (r) => void onCredential(r && r.credential),
      });
      window.google.accounts.id.renderButton(gsiBox, {theme: 'outline', size: 'large', text: 'signin_with', shape: 'pill', locale: 'ko', width: 280});
    };
    sc.onerror = () => { sc.remove(); gsiBox.textContent = '구글 로그인 버튼을 불러오지 못했어요. 연결을 확인하고 새로고침해 주세요.'; };
    document.head.append(sc);
  }

  function setAccount(r) {
    AUTH.user = (r && r.user) || null;
    window.SrvStore?.setAccount(r);
  }
  function notify() {
    const u = AUTH.user;
    window.dispatchEvent(new CustomEvent('memoir:preview-auth', {detail: {
      authenticated: !!u, displayName: u ? (u.name || u.email || '') : '', speaker: '',
    }}));
  }

  async function onCredential(credential) {
    if (busy) return;
    busy = true; setNote('로그인하는 중이에요…');
    try {
      const r = await api.authGoogle(credential);
      if (r && r.cancelled) { setNote(''); return; }
      setAccount(r); setNote('');
      notify(); render();
      dialog.querySelector('#login-preview-heading').focus({preventScroll: true});
    } catch (e) {
      setNote(AUTH_SAYS[e.code] || AUTH_SAYS.other);
    } finally { busy = false; }
  }

  function open() {
    opener = document.activeElement;
    render();
    if (!dialog.open) dialog.showModal();
    if (!AUTH.user) gsiInit();
    dialog.querySelector(AUTH.user ? '.mlg-primary' : '#login-preview-heading')?.focus({preventScroll: true});
  }
  function close() { if (dialog.open) dialog.close(); }
  dialog.addEventListener('close', () => { const t = opener?.isConnected ? opener : document.querySelector('[data-login]'); t?.focus({preventScroll: true}); opener = null; });

  async function logout() {
    if (window.SrvInterview?.busy?.() && !window.confirm('진행 중인 인터뷰가 있어요. 로그아웃할까요?')) return;
    try { await api.authLogout(); } catch (_) {}
    try { sessionStorage.setItem('authMsg', '로그아웃했어요.'); } catch (_) {}
    location.reload();
  }

  dialog.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button) {
      if (event.target === dialog) {
        const b = dialog.getBoundingClientRect();
        if (event.clientX < b.left || event.clientX > b.right || event.clientY < b.top || event.clientY > b.bottom) close();
      }
      return;
    }
    if (button.hasAttribute('data-login-close')) { close(); return; }
    if (button.hasAttribute('data-login-google')) { void onCredential('mock'); return; }
    if (button.hasAttribute('data-login-logout')) void logout();
  });

  // ── 앱을 열 때: 로그인돼 있나 ──
  const ready = (async () => {
    let flash = '';
    try { flash = sessionStorage.getItem('authMsg') || ''; sessionStorage.removeItem('authMsg'); } catch (_) {}
    try {
      setAccount(await api.authMe());
    } catch (e) {
      AUTH.user = null;
      note = e.status === 401 ? (flash || AUTH_SAYS[e.code] || '') : AUTH_SAYS.other;
      if (flash) setTimeout(() => toast(flash), 300);
    }
  })();
  window.MemoirAuthReady = ready;
  // 다른 스크립트가 다 붙은 뒤에 알린다 (login-gate · role-preview 가 이 신호를 듣는다)
  window.addEventListener('DOMContentLoaded', () => { ready.then(() => { if (AUTH.user) notify(); }); });

  window.MemoirLogin = {open, close, logout};
  render();
}());
