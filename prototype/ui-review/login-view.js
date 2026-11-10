(function () {
  'use strict';

  // One-click mock only. Real Google login and first-speaker registration are
  // documented separately; no SDK, requests, credentials, or persistence here.
  const mockAccount = Object.freeze({name:'Google Login Mock Data',speaker:'나'});
  let account = null;
  let opener = null;
  const dialog = document.createElement('dialog');
  dialog.className = 'memoir-login-dialog';
  dialog.setAttribute('aria-labelledby', 'login-preview-heading');
  dialog.setAttribute('aria-describedby', 'login-preview-description');
  dialog.innerHTML = `
    <div class="mlg-topbar"><span class="mlg-preview-label">로그인 화면 미리보기</span><button type="button" class="mlg-close" data-login-close aria-label="로그인·계정 미리보기 닫기">${icons('close')}</button></div>
    <div class="mlg-layout">
      <div class="mlg-visual" aria-hidden="true"><span class="mlg-brand">내말싸미</span><img src="book-illustration.svg" alt=""><p>작은 이야기가 모여<br>오래 남는 한 권으로.</p><span class="mlg-visual-rule"></span></div>
      <div class="mlg-main"><h2 id="login-preview-heading" tabindex="-1"></h2><p id="login-preview-description"></p><div class="mlg-content" data-login-content></div></div>
    </div>`;
  document.body.append(dialog);

  function render() {
    const heading = dialog.querySelector('#login-preview-heading');
    const description = dialog.querySelector('#login-preview-description');
    const content = dialog.querySelector('[data-login-content]');
    if (account) {
      heading.textContent = '목데이터로 둘러보고 있어요';
      description.textContent = '테스트용 로그인 상태입니다.';
      content.innerHTML = `
        <div class="mlg-account"><span class="mlg-account-avatar" aria-hidden="true">G</span><span><strong>${escapeText(account.name)}</strong><small>Mock Google Account</small></span></div>
        <button type="button" class="button primary mlg-primary" data-login-close>이어서 둘러보기</button>
        <button type="button" class="mlg-secondary" data-login-logout>가상 계정 로그아웃</button>`;
      return;
    }
    heading.textContent = '나의 이야기를 함께 모아요';
    description.textContent = '버튼 한 번으로 목데이터 계정을 사용해 보세요.';
    content.innerHTML = `
      <button type="button" class="button primary mlg-primary" data-login-google>Google Login Mock Data</button>
      <button type="button" class="mlg-secondary" data-login-close>로그인 없이 계속 둘러보기</button>
      <p class="mlg-fixture-note">실제 Google 계정 선택창은 열리지 않아요.</p>`;
  }

  function notify() {
    window.dispatchEvent(new CustomEvent('memoir:preview-auth', {detail:{
      preview:true,
      authenticated:!!account,
      displayName:account ? account.name : '',
      speaker:account ? account.speaker : ''
    }}));
  }

  function focusHeading() { dialog.querySelector('#login-preview-heading').focus({preventScroll:true}); }

  function open() {
    opener=document.activeElement;
    render();
    if (!dialog.open) dialog.showModal();
    const firstAction = dialog.querySelector(account ? '.mlg-primary' : '[data-login-google]');
    firstAction?.focus({preventScroll:true});
  }

  function close() { if (dialog.open) dialog.close(); }
  dialog.addEventListener('close',()=>{const target=opener?.isConnected?opener:document.querySelector('[data-login]');target?.focus({preventScroll:true});opener=null;});

  function logout() {
    account = null;
    notify();
    render();
    if (dialog.open) focusHeading();
  }

  dialog.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button) {
      if (event.target === dialog) {
        const bounds = dialog.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) close();
      }
      return;
    }
    if (button.hasAttribute('data-login-close')) { close(); return; }
    if (button.hasAttribute('data-login-google')) {
      account = {...mockAccount};
      notify();
      render();
      focusHeading();
      return;
    }
    if (button.hasAttribute('data-login-logout')) logout();
  });

  window.MemoirLogin = {open, close, logout};
  render();
}());
