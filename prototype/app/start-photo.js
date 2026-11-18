(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     start-photo — 인터뷰를 시작하기 전에 「사진 한 장」 넣기 (골라도, 안 골라도 된다)
       · 「내 이야기」(start-self) · 「초대 주소 만들기」(invite-setup) 화면의 고르기 칸에 들어간다.
       · 서버: POST /api/photos (바이트 그대로) → { photo_id }
               그 photo_id 를 POST /api/sessions · POST /api/links 에 싣는다 (StartReq · LinkReq.photo_id).
       · 고르는 순간 올린다 — 서버가 올리는 자리에서 사진 분석을 걸어 두므로(analyze_later),
         시작을 누를 때쯤 단서가 준비되어 첫 질문부터 사진 이야기가 된다 (CONFIG.photo.uploadOnPick).
       · 로그인 전에는 올리지 않고 들고 있다가, 시작할 때 올린다.
       · 올리지 못해도 이야기는 시작한다 — 사진은 거들 뿐이다.
     ═══════════════════════════════════════════════════════════════ */
  // 비교용으로 끄기: 주소 끝에 ?photo=off (예: ?demo=1&photo=off) — 사진 칸 없는 예전 모습
  if (new URLSearchParams(location.search).get('photo') === 'off') return;
  const S = window.Srv;
  const PCFG = (S && S.CONFIG && S.CONFIG.photo) || {upload: true, maxUploadMB: 20, uploadOnPick: true, sendIdOnCreate: true, waitBeforeStartMs: 8000};
  // 한 장만 들고 있는다. 화면을 다시 그려도(다른 화면에 다녀와도) 그대로 남는다
  let pick = null; // {file, url, previewOk, status: 'idle'|'uploading'|'ready'|'failed', id, promise, error}

  const loggedIn = () => !!window.MemoirGate?.isLoggedIn?.();
  const MB = 1024 * 1024;

  // 너무 큰 사진은 긴 변 2400px JPEG 로 줄여서 올린다 (브라우저가 열 수 있는 형식일 때만)
  async function bytesOf(file) {
    if (file.size <= PCFG.maxUploadMB * MB) return {body: await file.arrayBuffer(), mime: file.type};
    try {
      const bmp = await createImageBitmap(file);
      const k = Math.min(1, 2400 / Math.max(bmp.width, bmp.height));
      const c = document.createElement('canvas'); c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
      c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
      const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.88));
      return {body: await blob.arrayBuffer(), mime: 'image/jpeg'};
    } catch (_) { return null; }
  }

  function upload() {
    if (!pick || !S || !PCFG.upload) return Promise.resolve(null);
    if (pick.status === 'uploading' || pick.status === 'ready') return pick.promise;
    const me = pick;
    me.status = 'uploading'; me.error = '';
    paintAll();
    me.promise = (async () => {
      const b = await bytesOf(me.file);
      if (!b) throw Object.assign(new Error('too_big'), {status: 413});
      const r = await S.api.uploadPhoto(b.body, b.mime);
      return r.photo_id;
    })().then((id) => { if (pick === me) { me.status = 'ready'; me.id = id; paintAll(); } return id; },
      (e) => {
        if (pick === me) {
          me.status = 'failed';
          me.error = e.status === 400 ? '이 사진은 열 수 없어요. 다른 사진을 골라 주세요.'
            : e.status === 413 ? '사진이 너무 커요. 다른 사진을 골라 주세요.'
            : '사진을 올리지 못했어요. 그래도 사진 없이 시작할 수 있어요.';
          paintAll();
        }
        return null;
      });
    return me.promise;
  }

  function choose(file) {
    if (!file) return;
    if (file.type && !file.type.startsWith('image/')) { toast('사진 파일을 골라 주세요.'); return; }
    clear(false);
    pick = {file, url: URL.createObjectURL(file), previewOk: true, status: 'idle', id: null, promise: null, error: ''};
    paintAll();
    if (PCFG.uploadOnPick && loggedIn()) void upload();
  }

  function clear(repaint = true) {
    if (pick?.url) URL.revokeObjectURL(pick.url);
    pick = null;
    if (repaint) paintAll();
  }

  /** 시작 · 초대 직전에 부른다 — 올리는 중이면 잠깐 기다리고, 아직 안 올렸으면 지금 올린다 */
  async function takeId(waitMs = PCFG.waitBeforeStartMs) {
    if (!pick) return null;
    if (pick.status === 'ready') return pick.id;
    if (pick.status !== 'uploading') void upload();
    const id = await Promise.race([pick.promise, new Promise((r) => setTimeout(() => r(null), waitMs))]);
    if (!id) toast('사진은 아직 올라가지 않아 빼고 시작해요.');
    return id;
  }

  // ── 고르는 칸 (start-choice 의 다른 칸과 같은 fieldset 모양) ──
  function fieldset(step) {
    return `<fieldset class="sc-photo"><legend>${step ? `<span class="sc-step">${step}</span>` : ''}사진 한 장 <small class="sc-optional">골라도, 안 골라도 돼요</small></legend>
      <div class="sp-body"></div>
      <input type="file" accept="image/*" class="sp-input" hidden>
      <p class="sc-voice-note">사진을 넣으면 사진 속 장면부터 여쭤봐요.</p></fieldset>`;
  }

  function paint(fs) {
    const body = fs.querySelector('.sp-body');
    if (!pick) {
      body.innerHTML = `<button type="button" class="sp-drop" data-sp="pick"><svg class="icon" aria-hidden="true"><use href="#i-photo"/></svg><span class="sp-drop-main">사진 고르기</span><span class="sp-drop-sub">앨범이나 사진기에서 한 장</span></button>`;
      return;
    }
    const st = pick.status === 'uploading' ? '<span class="sp-st sp-st-busy" role="status"><span class="sp-spin" aria-hidden="true"></span>사진을 올리는 중이에요</span>'
      : pick.status === 'ready' ? '<span class="sp-st sp-st-ok" role="status">사진이 준비됐어요</span>'
      : pick.status === 'failed' ? `<span class="sp-st sp-st-err" role="alert">${pick.error}</span>`
      : `<span class="sp-st" role="status">${loggedIn() ? '' : '시작할 때 함께 올려요'}</span>`;
    body.innerHTML = `<div class="sp-card">
        <div class="sp-thumb">${pick.previewOk ? `<img src="${pick.url}" alt="고른 사진">` : '<span>미리보기를 보여 드릴 수 없는 형식이에요. 그래도 보낼 수 있어요.</span>'}</div>
        <div class="sp-meta"><strong class="sp-name"></strong>${st}
          <div class="sp-acts"><button type="button" class="text-button" data-sp="pick">다른 사진</button><button type="button" class="text-button" data-sp="remove">빼기</button>${pick.status === 'failed' ? '<button type="button" class="text-button" data-sp="retry">다시 올리기</button>' : ''}</div></div></div>`;
    body.querySelector('.sp-name').textContent = pick.file.name || '고른 사진';
    const img = body.querySelector('img');
    if (img) img.addEventListener('error', () => { if (pick) { pick.previewOk = false; paintAll(); } }, {once: true});
  }
  function paintAll() {
    document.querySelectorAll('fieldset.sc-photo').forEach(paint);
    document.querySelectorAll('form').forEach((f) => f.dispatchEvent(new Event('sp-change')));
  }

  function bind(form) {
    const fs = form.querySelector('fieldset.sc-photo'); if (!fs) return;
    const input = fs.querySelector('.sp-input');
    fs.addEventListener('click', (e) => {
      const b = e.target.closest('[data-sp]'); if (!b) return;
      e.preventDefault();
      if (b.dataset.sp === 'pick') input.click();
      if (b.dataset.sp === 'remove') clear();
      if (b.dataset.sp === 'retry') { pick.status = 'idle'; void upload(); }
    });
    input.addEventListener('change', (e) => { e.stopPropagation(); choose(input.files[0]); input.value = ''; });
    // 끌어다 놓기 (PC)
    fs.addEventListener('dragover', (e) => { e.preventDefault(); fs.classList.add('sp-over'); });
    fs.addEventListener('dragleave', () => fs.classList.remove('sp-over'));
    fs.addEventListener('drop', (e) => { e.preventDefault(); fs.classList.remove('sp-over'); choose(e.dataTransfer.files[0]); });
    paint(fs);
  }

  // 로그인하면 들고 있던 사진을 바로 올린다
  window.addEventListener('memoir:preview-auth', (e) => { if (e.detail?.authenticated && pick && pick.status === 'idle' && PCFG.uploadOnPick) void upload(); });

  /** 회차 · 초대에 실은 뒤 — 들고 있던 사진을 내려놓고, 미리보기 주소는 넘겨준다(인터뷰 화면이 쓴다) */
  function release() { const url = pick?.previewOk ? pick.url : null; pick = null; paintAll(); return url; }

  window.MemoirStartPhoto = {fieldset, bind, takeId, clear, choose, release,
    get has() { return !!pick; }, get previewUrl() { return pick?.previewOk ? pick.url : null; },
    label: () => (pick ? '한 장 넣음' : '넣지 않음')};
}());
