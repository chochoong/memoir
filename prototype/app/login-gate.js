(function () {
  'use strict';
  // 6. 로그인 전에는 처음가기의 「엽서보기 · 자서전 보기」부터 그 아래를 모두 가린다.
  //    엽서 · 자서전 화면으로 가려 하면 로그인 창을 먼저 연다. 로그인은 기존 목데이터 창(MemoirLogin)을 그대로 쓴다.
  const LOCKED = ['records', 'library', 'style', 'draft', 'reader'];
  let loggedIn = !!window.RolePreview?.isLoggedIn?.();
  let pending = null;

  const home = document.querySelector('[data-screen="home"]');
  const hero = home?.querySelector('.hero');
  if (hero) {
    const card = document.createElement('div');
    card.className = 'panel login-gate-card';
    card.innerHTML = `<div class="lg-copy"><span class="eyebrow">모아 둔 이야기는 로그인한 뒤에</span>
      <h2>엽서와 자서전은 로그인하면 보여요</h2>
      <p>들려주신 이야기는 엽서가 되고, 엽서가 모이면 한 권의 책이 돼요. 내 기록은 내 계정에서만 열려요.</p></div>
      <button type="button" class="button primary lg-login">${icons('arrow')}<span>로그인하고 내 기록 보기</span></button>`;
    hero.after(card);
    card.querySelector('.lg-login').addEventListener('click', () => { pending = null; window.MemoirLogin.open(); });
  }

  function apply() {
    document.body.classList.toggle('pre-login', !loggedIn);
    document.querySelectorAll('[data-nav="records"],[data-nav="library"]').forEach((link) => {
      if (loggedIn) link.removeAttribute('data-locked'); else link.setAttribute('data-locked', '로그인 후 볼 수 있어요');
    });
  }
  function ask(target) {
    pending = target;
    window.MemoirLogin.open();
    toast('로그인하면 엽서와 자서전을 볼 수 있어요.');
  }

  // 메뉴 · 바로가기 클릭을 가로챈다(캡처 단계라 원래 이동보다 먼저 본다)
  document.addEventListener('click', (event) => {
    if (loggedIn) return;
    const link = event.target.closest('[data-nav],[data-go],a[href^="#"]');
    if (!link) return;
    const target = link.dataset.nav || link.dataset.go || (link.getAttribute('href') || '').slice(1);
    if (!LOCKED.includes(target)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    ask(target);
  }, true);

  // 주소창으로 바로 들어와도 처음가기로 돌린다
  function guardHash() {
    const screen = location.hash.slice(1);
    if (!loggedIn && LOCKED.includes(screen)) { location.replace('#home'); ask(screen); }
  }
  window.addEventListener('hashchange', guardHash);

  window.addEventListener('memoir:preview-auth', (event) => {
    loggedIn = !!event.detail.authenticated;
    apply();
    if (loggedIn && pending) {
      const target = pending; pending = null;
      window.MemoirLogin.close();
      navigate(target);
    }
    if (!loggedIn && LOCKED.includes(location.hash.slice(1))) location.hash = 'home';
  });

  // 로그인하지 않고 창을 닫으면, 가려던 곳은 잊는다(나중에 다른 이유로 로그인할 때 엉뚱한 화면으로 가지 않게)
  document.querySelector('.memoir-login-dialog')?.addEventListener('close', () => { if (!loggedIn) pending = null; });

  apply();
  // 주소로 바로 들어온 경우 — 로그인 확인(/api/auth/me)이 끝난 뒤에 막을지 정한다 (로그인돼 있는데 로그인 창이 번쩍이지 않게)
  const domReady = document.readyState === 'loading' ? new Promise((r) => document.addEventListener('DOMContentLoaded', r, {once: true})) : Promise.resolve();
  Promise.all([window.MemoirAuthReady || Promise.resolve(), domReady]).then(() => setTimeout(guardHash, 0));
  window.MemoirGate = { isLoggedIn: () => loggedIn, ask };
}());
