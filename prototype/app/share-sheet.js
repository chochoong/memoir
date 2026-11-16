(function () {
  'use strict';
  // 「보내기」 공통 창 — 자서전 공유 · 인터뷰 초대 링크 보내기가 함께 쓴다.
  //  받는 분에게 보이는 모습(카드) → 함께 보낼 글(고칠 수 있음) → 링크 → 보내는 방법.
  //  시안에서는 「링크 복사」만 실제로 복사하고, 카카오톡 · 문자 · 이메일은 무엇이 열리는지만 알려 준다.
  const dialog = document.createElement('dialog');
  dialog.className = 'review-dialog share-dialog';
  dialog.setAttribute('aria-labelledby', 'share-title');
  dialog.innerHTML = `<form method="dialog"><button class="dialog-close" aria-label="닫기">${icons('close')}</button></form>
    <span class="eyebrow share-eyebrow"></span><h2 id="share-title"></h2>
    <div class="share-setup"></div>
    <div class="share-main">
      <div class="share-card" aria-label="받는 분에게 보이는 모습"><span class="share-card-art" aria-hidden="true"></span><span class="share-card-copy"><small></small><strong></strong><em></em></span></div>
      <label class="share-msg-label" for="share-msg">함께 보낼 글 <small>고쳐 써도 돼요</small></label>
      <textarea id="share-msg" rows="4"></textarea>
      <div class="share-link"><input id="share-link" readonly aria-label="보낼 링크"><button type="button" class="button outline compact" data-share="copy">${icons('check')}<span>링크 복사</span></button></div>
      <div class="share-channels" role="group" aria-label="보내는 방법">
        <button type="button" data-share="kakao"><span class="sc-dot kakao" aria-hidden="true">K</span>카카오톡</button>
        <button type="button" data-share="sms"><span class="sc-dot sms" aria-hidden="true">${icons('letter')}</span>문자</button>
        <button type="button" data-share="mail"><span class="sc-dot mail" aria-hidden="true">@</span>이메일</button>
        <button type="button" data-share="more"><span class="sc-dot more" aria-hidden="true">···</span>다른 앱</button>
      </div>
      <p class="share-status" role="status"></p>
      <div class="share-extras"></div>
      <p class="share-note"></p>
    </div>`;
  document.body.append(dialog);
  const $d = (s) => dialog.querySelector(s);
  let current = null;
  const CH = {kakao: '카카오톡', sms: '문자', mail: '이메일', more: '다른 앱'};

  function fill(o) {
    $d('.share-eyebrow').textContent = o.eyebrow || '';
    $d('#share-title').textContent = o.title;
    $d('.share-card small').textContent = o.card.kicker;
    $d('.share-card strong').textContent = o.card.title;
    $d('.share-card em').textContent = o.card.sub;
    $d('.share-card').dataset.kind = o.kind;
    $d('.share-card-art').innerHTML = o.card.art || '';
    $d('#share-msg').value = o.message;
    $d('#share-link').value = o.link || '';
    $d('.share-status').textContent = o.status || '';
    $d('.share-note').textContent = o.note || '';
    const extras = $d('.share-extras');
    extras.innerHTML = '';
    (o.extras || []).forEach((x) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = `text-button ${x.className || ''}`;
      b.innerHTML = `${x.icon ? icons(x.icon) : ''}<span>${escapeText(x.label)}</span>`;
      b.addEventListener('click', () => x.onClick(api));
      extras.append(b);
    });
    // 링크를 아직 만들지 않았으면(자서전) 설정 단계만 보여 준다
    const setup = $d('.share-setup');
    setup.innerHTML = '';
    if (o.setup) { setup.append(o.setup(api)); setup.hidden = false; $d('.share-main').hidden = true; }
    else { setup.hidden = true; $d('.share-main').hidden = false; }
  }
  function open(o) {
    current = o; fill(o);
    if (!dialog.open) dialog.showModal();
    (o.setup ? $d('.share-setup input:checked, .share-setup button') : $d('[data-share="copy"]'))?.focus();
  }
  const text = () => `${$d('#share-msg').value.trim()}\n${$d('#share-link').value}`;
  // 휴대폰 · 태블릿인가 — 카카오톡이 공유 창에 나오는 기기. 아이패드는 스스로를 맥이라고 하므로 터치로 가린다
  const isPhone = () => (navigator.userAgentData && typeof navigator.userAgentData.mobile === 'boolean' && navigator.userAgentData.mobile)
    || /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
    || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
  async function copyFor(how, all, tip) {
    const st = $d('.share-status');
    try { await navigator.clipboard.writeText(all); st.textContent = `글과 링크를 복사했어요. ${tip || `${CH[how]}에 붙여 넣어 보내 주세요.`}`; }
    catch { $d('#share-link').select(); st.textContent = '자동 복사가 되지 않았어요. 선택된 링크를 직접 복사해 보내 주세요.'; }
  }
  dialog.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-share]');
    if (!b || !current) return;
    const how = b.dataset.share;
    if (how === 'copy') {
      try { await navigator.clipboard.writeText(text()); $d('.share-status').textContent = '글과 링크를 함께 복사했어요. 원하는 곳에 붙여 넣어 보내 주세요.'; }
      catch { $d('#share-link').select(); $d('.share-status').textContent = '자동 복사가 되지 않았어요. 선택된 링크를 직접 복사해 주세요.'; }
      current.onSent?.('copy');
      return;
    }
    // 실제로 보낸다 — 문자 · 이메일은 기기의 앱을 열고, 카카오톡 · 다른 앱은 휴대폰의 공유 창으로.
    // 공유 창이 없는 컴퓨터에서는 글과 링크를 복사해 붙여 넣게 한다 (카카오 SDK 키가 없어 카카오톡을 직접 열 수 없다)
    const msg = $d('#share-msg').value.trim(), link = $d('#share-link').value, all = text();
    const status = (t) => { $d('.share-status').textContent = t; };
    // 문자 — PC(윈도우 · 맥)에는 문자 앱이 없다. sms: 를 열면 윈도우가 「이 'sms' 링크를 무엇으로 열까요?」를 묻는다
    // (11-13 제보 스크린샷). PC 에서는 열지 않고 복사한다
    if (how === 'sms' && !isPhone()) { await copyFor(how, all, 'PC에서는 문자를 바로 보낼 수 없어요. 휴대폰 문자나 카카오톡 PC에 붙여 넣어 보내 주세요.'); }
    else if (how === 'sms') { location.href = `sms:?&body=${encodeURIComponent(all)}`; status('문자 앱을 열었어요. 받는 분을 골라 보내 주세요.'); }
    // 이메일 — PC 에 메일 프로그램이 없으면 같은 「무엇으로 열까요?」 창이 뜰 수 있다. 그래서 PC 에서는 먼저 복사해 둔다
    else if (how === 'mail') {
      if (!isPhone()) await copyFor(how, all, '메일 앱이 열리지 않으면, 쓰시는 메일(네이버 · 지메일 등)에 붙여 넣어 보내 주세요.');
      location.href = `mailto:?subject=${encodeURIComponent(current.title || '내말싸미')}&body=${encodeURIComponent(all)}`;
      if (isPhone()) status('메일 앱을 열었어요. 받는 분 주소를 적어 보내 주세요.');
    }
    // 카카오톡은 휴대폰의 공유 창에만 있다. PC(윈도우 · 맥)의 공유 창에는 카카오톡 PC가 나오지 않아서,
    // 창을 닫으면 아무것도 남지 않았다 (11-13 제보 「PC 에서만 카톡이 안 열린다」). PC 에서는 공유 창 대신 복사한다
    else if (how === 'kakao' && !isPhone()) { await copyFor(how, all, '카카오톡 PC에서 보낼 대화방을 열고 붙여 넣기(Ctrl+V · ⌘V) 해 주세요.'); }
    else if (navigator.share) {
      if (how === 'kakao') status('공유 창이 열리면 「카카오톡」을 골라 주세요.');
      try { await navigator.share({title: current.title || '내말싸미', text: msg, url: link}); status(how === 'kakao' ? '카카오톡에서 보내기를 마쳐 주세요.' : '보냈어요.'); }
      catch (err) {
        if (err && err.name === 'AbortError') { status(how === 'kakao' ? '보내지 않았어요. 다시 누르거나 「링크 복사」로 보내 주세요.' : ''); return; }
        await copyFor(how, all); return;
      }
    } else {
      await copyFor(how, all);
    }
    current.onSent?.(how);
  });
  dialog.addEventListener('close', () => { current?.onClose?.(); current = null; });

  const api = {
    open, close: () => dialog.close(), refill: (o) => { current = o; fill(o); $d('[data-share="copy"]').focus(); },
    setStatus: (t) => { $d('.share-status').textContent = t; },
  };
  window.MemoirShare = api;
}());
