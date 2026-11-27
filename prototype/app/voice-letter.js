(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     voice-letter — 가족 음성편지 (업무지시서 「가족 음성편지」 11/26 · 서버 계약 10-C1 · develop 1dffd3b 019)
       · 자서전을 만드는 동안(진행 창) 원하는 사람만 녹음한다. 자서전마다 음성편지 1개 · 최대 5분.
       · 녹음 · 미리듣기는 이 탭 안에서만. 「저장」을 눌러야 올린다.
           ② POST /api/voice-message-uploads (원본 바이트 + X-Request-ID) → state 'uploaded' — 저장 완료가 아니다
           ③ 책이 아직 없으면(작업이 끝나지 않았거나 memoir_id 없음) 「책 연결 대기」
           ④ PUT /api/memoirs/saved/{memoir_id}/voice-message → message.state === 'ready' 일 때만 「책에 저장 완료」
       · 화면 상태: idle → asking(마이크 허락 기다림) → recording → stopping → preview(아직 저장 안 됨)
                    → uploading → waiting_book → linking → ready.  그 밖: denied · error · conflict · orphan · ask_attach
       · 300초는 시작 시각 기준의 경과시간으로 잰다(조각 수로 세지 않는다). 종료는 마지막 dataavailable → stop 이벤트를
         받은 뒤 미리듣기로 — 끝부분이 빠지지 않게. 5분 자동 종료는 「녹음 종료」일 뿐 저장으로 이어지지 않는다.
       · 실패해도 음성을 버리지 않는다: 업로드 실패 → 같은 X-Request-ID 로 다시 · 410 upload_expired → 새 id 로 다시 올림 ·
         연결 실패 → 같은 request_id 로 다시 · 409 revision_conflict → 다시 읽고 사용자에게 묻기.
         자서전 생성이 실패 · 취소 · memoir_id 없음 → 음성은 이 탭에 남기고(orphan), 다음에 만든 책에 붙일지 묻는다.
         다른 책 · 최신 책에 저절로 붙이지 않는다.
       · 전자책 마지막 쪽: 저장된 음성 길이 + 「음성편지 듣기」(눌러야 재생 · 자동재생 없음) · 다시 녹음해 바꾸기 · 지우기.
         바꾸기는 새 연결이 성공한 뒤에야 예전 것이 바뀐다(서버 보장). 지우기는 서버가 204 를 준 뒤에야 화면에서 뺀다.
       · 인터뷰 · 받아쓰기와 따로 — 녹음 전에 질문 낭독(TTS)을 멈추고, 인터뷰가 진행 중이면 녹음을 시작하지 않는다.
       · 공유받은 사람의 재생은 서버의 공유 페이지(/b · /api/b 의 voice_message) 몫이다 — 이 화면에는 공유받은 사람용 조작이 없다.
     ═══════════════════════════════════════════════════════════════ */
  const S = window.Srv;
  if (!S || !S.api || !S.api.voiceUpload) return;
  const {api, CONFIG} = S;
  const VC = Object.assign({maxSec: 300, warnSec: 30, maxBytes: 8 * 1024 * 1024, mimes: ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']}, CONFIG.voice || {});
  // 예시 모드 시험용: ?voiceMax=초 — 5분을 기다리지 않고 자동 종료를 본다 (실제 서버 화면에서는 쓰지 않는다)
  if (S.DEMO && Number(S.QS.get('voiceMax')) > 0) { VC.maxSec = Number(S.QS.get('voiceMax')); VC.warnSec = Math.min(VC.warnSec || 0, Math.floor(VC.maxSec / 2)); }
  const MAX_MS = VC.maxSec * 1000;
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const icon = (n) => `<svg class="icon" aria-hidden="true"><use href="#i-${n}"/></svg>`;
  const toast = (m, ms = 3600) => { const t = document.getElementById('toast'); if (!t) return; t.textContent = m; t.hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, ms); };
  const clock = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
  const long = (ms) => { const s = Math.max(1, Math.round(ms / 1000)); return s >= 60 ? `${Math.floor(s / 60)}분${s % 60 ? ` ${s % 60}초` : ''}` : `${s}초`; };
  const newId = () => (window.crypto && crypto.randomUUID ? crypto.randomUUID() : 'v' + Date.now().toString(36) + Math.random().toString(36).slice(2));
  const pickMime = () => { if (!window.MediaRecorder) return null; if (!MediaRecorder.isTypeSupported) return ''; return VC.mimes.find((m) => MediaRecorder.isTypeSupported(m)) ?? ''; };
  // 서버 10-C1 실패 갈래 → 화면 말
  function errText(e) {
    const say = {
      request_id_required: '요청을 다시 보내 주세요.', bad_revision: '요청을 다시 보내 주세요.',
      memoir_not_found: '이 자서전을 찾을 수 없어요. 책장에서 다시 열어 주세요.',
      upload_not_found: '올린 음성을 찾을 수 없어요. 다시 저장해 주세요.', message_not_found: '지울 음성편지가 없어요.',
      revision_conflict: '다른 곳에서 음성편지가 바뀌었어요.', upload_in_use: '이미 다른 책에 연결된 음성이에요.',
      upload_attached: '책에 연결된 음성이에요.', upload_expired: '올린 음성의 보관 기한이 지났어요.',
      unsupported_audio: '이 음성은 저장할 수 없는 형식이에요. 다시 녹음해 주세요.',
      too_long: '음성편지는 5분까지예요. 다시 녹음해 주세요.', too_short: '녹음이 너무 짧아요. 다시 녹음해 주세요.',
      voice_unavailable: '지금은 음성편지를 저장할 수 없어요. 잠시 뒤 다시 저장해 주세요.', voice_busy: '음성을 처리하는 데 오래 걸려요. 잠시 뒤 다시 저장해 주세요.',
    }[e && e.code];
    if (say) return say;
    if (e && e.status === 413) return '음성이 너무 커요. 조금 짧게 다시 녹음해 주세요.';
    if (e && e.status === 401) return '로그인이 풀렸어요. 다시 로그인해 주세요.';
    return '연결이 잠시 끊겼어요. 음성은 그대로 있어요 — 다시 저장해 주세요.';
  }
  const fatal = (e) => e && (['unsupported_audio', 'too_long', 'too_short'].includes(e.code) || e.status === 413);   // 같은 음성으로 다시 보내도 안 되는 것

  /* ═══ 녹음기 하나 (진행 창용 · 책 음성 바꾸기 창용) ═══ */
  const all = [];
  function makeRecorder(root, opts) {
    const st = {phase: 'idle', blob: null, url: null, ms: 0, startAt: 0, rec: null, stream: null, chunks: [], tick: null, auto: null,
      upRid: null, upload: null, linkRid: null, memoir: null, title: '', jobId: null, jobLost: false, err: '', errStep: '', note: '', conflictRev: null, hidden: false};
    const player = new Audio(); player.preload = 'metadata';
    const ctl = {st, render, discard, start, stop, save, holding, unsaved, setMemoir, jobStarted, jobDone, jobFailed, reset};
    all.push(ctl);
    player.addEventListener('ended', paintPlay); player.addEventListener('pause', paintPlay); player.addEventListener('play', paintPlay);
    function paintPlay() { const b = root.querySelector('[data-vl="listen"]'); if (b) b.innerHTML = player.paused ? `${icon('play')}<span>들어보기</span>` : `${icon('pause')}<span>멈추기</span>`; }
    const busy = () => ['uploading', 'linking', 'stopping'].includes(st.phase);

    function render() {
      const p = st.phase, len = st.ms ? long(st.ms) : '';
      const unsavedNote = `<p class="vl-unsaved" role="status">${icon('close')}<b>아직 저장되지 않았습니다</b></p>`;
      const listen = st.url ? `<button type="button" class="button outline vl-btn" data-vl="listen">${icon('play')}<span>들어보기</span></button>` : '';
      const again = `<button type="button" class="button outline vl-btn" data-vl="again" ${busy() ? 'disabled' : ''}>${icon('mic')}<span>다시 녹음</span></button>`;
      let body = '';
      if (p === 'idle') {
        body = `<p class="vl-lead">${opts.mode === 'gen' ? '자서전을 기다리는 동안, 책에 가족의 목소리를 남길 수 있어요.' : '이 자서전에 가족의 목소리를 남겨요.'} <b>최대 5분</b>.${opts.mode === 'gen' ? ' 남기지 않아도 자서전은 그대로 만들어져요.' : ''}</p>
          <button type="button" class="button primary vl-big" data-vl="start">${icon('mic')}<span>녹음 시작</span></button>`;
      } else if (p === 'asking') {
        body = `<p class="vl-lead">마이크를 쓸 수 있게 허락해 주세요. 허락하면 바로 녹음이 시작돼요.</p>`;
      } else if (p === 'denied') {
        body = `<p class="vl-warn" role="alert">${esc(st.err)}</p><p class="vl-help">주소창 왼쪽의 자물쇠(또는 설정)에서 「마이크」를 허용한 뒤 다시 눌러 주세요.</p>
          <button type="button" class="button primary vl-big" data-vl="start">${icon('mic')}<span>다시 시도</span></button>`;
      } else if (p === 'recording') {
        body = `<p class="vl-rec" role="status"><span class="vl-dot" aria-hidden="true"></span><b>녹음 중</b> <span class="vl-time">${clock(performance.now() - st.startAt)} / ${clock(MAX_MS)}</span></p>
          <p class="vl-warn vl-soon" hidden>30초 후 녹음이 끝납니다</p>
          <button type="button" class="button primary vl-big vl-stop" data-vl="stop">${icon('pause')}<span>녹음 종료</span></button>
          <p class="vl-help">5분이 되면 저절로 끝나요. 그 전에도 언제든 끝낼 수 있어요.</p>`;
      } else if (p === 'stopping') {
        body = `<p class="vl-lead" role="status">녹음을 마무리하고 있어요…</p>`;
      } else if (p === 'preview') {
        body = `${unsavedNote}<p class="vl-len">녹음 길이 <b>${len}</b></p>${st.note ? `<p class="vl-note">${esc(st.note)}</p>` : ''}
          <div class="vl-row">${listen}${again}<button type="button" class="button primary vl-btn" data-vl="save">${icon('check')}<span>저장</span></button></div>`;
      } else if (p === 'uploading') {
        body = `${unsavedNote}<p class="vl-lead" role="status"><span class="sp-spin" aria-hidden="true"></span> 음성을 보내는 중이에요…</p>`;
      } else if (p === 'waiting_book') {
        body = `${unsavedNote}<p class="vl-lead" role="status">음성을 보냈어요. <b>자서전이 다 만들어지면 그 책에 저장돼요.</b></p><p class="vl-len">녹음 길이 <b>${len}</b></p>
          <div class="vl-row">${listen}${again}</div>`;
      } else if (p === 'linking') {
        body = `${unsavedNote}<p class="vl-lead" role="status"><span class="sp-spin" aria-hidden="true"></span> 책에 저장하는 중이에요…</p>`;
      } else if (p === 'ready') {
        body = `<p class="vl-done" role="status">${icon('check')}<b>책에 저장 완료</b> · ${len}</p>${opts.mode === 'gen' && st.title ? `<p class="vl-help">「${esc(st.title)}」 마지막 쪽에서 들을 수 있어요.</p>` : ''}
          <div class="vl-row">${listen}</div>`;
      } else if (p === 'error') {
        body = `${unsavedNote}<p class="vl-warn" role="alert">${esc(st.err)}</p><p class="vl-len">녹음 길이 <b>${len}</b></p>
          <div class="vl-row">${listen}${again}${fatal(st.lastErr) ? '' : `<button type="button" class="button primary vl-btn" data-vl="retry">${icon('check')}<span>다시 저장</span></button>`}</div>`;
      } else if (p === 'conflict') {
        body = `${unsavedNote}<p class="vl-warn" role="alert">다른 곳에서 이 책의 음성편지가 바뀌었어요. 지금 녹음한 음성으로 바꿀까요?</p>
          <div class="vl-row">${listen}<button type="button" class="button outline vl-btn" data-vl="keep-old">바꾸지 않기</button><button type="button" class="button primary vl-btn" data-vl="take">${icon('check')}<span>지금 녹음으로 바꾸기</span></button></div>`;
      } else if (p === 'orphan') {
        body = `${unsavedNote}<p class="vl-warn" role="status">자서전이 만들어지지 않아 음성편지를 책에 저장하지 못했어요.</p>
          <p class="vl-help">음성은 이 화면을 닫거나 새로고침하기 전까지 남아 있어요. 자서전을 다시 만들면 그 책에 저장할지 물어볼게요.</p><p class="vl-len">녹음 길이 <b>${len}</b></p>
          <div class="vl-row">${listen}<button type="button" class="button outline vl-btn" data-vl="drop">음성 버리기</button></div>`;
      } else if (p === 'ask_attach') {
        body = `${unsavedNote}<p class="vl-lead">아까 녹음한 음성편지(${len})를 이번에 만든 <b>「${esc(st.title || '새 자서전')}」</b>에 저장할까요?</p>
          <div class="vl-row">${listen}<button type="button" class="button outline vl-btn" data-vl="drop">저장하지 않기</button><button type="button" class="button primary vl-btn" data-vl="attach">${icon('check')}<span>이 책에 저장</span></button></div>`;
      }
      root.dataset.phase = p;
      root.innerHTML = `<h3 class="vl-title">${icon('mic')}<span>가족 음성편지</span>${opts.mode === 'gen' ? '<small>선택</small>' : ''}</h3>${body}`;
      if (st.url && player.src !== st.url) player.src = st.url;
      paintPlay();
      if (opts.onChange) opts.onChange(ctl);
    }
    function set(phase, extra) { Object.assign(st, extra || {}); st.phase = phase; render(); }

    // ── 녹음 ──
    async function start() {
      if (['asking', 'recording', 'stopping'].includes(st.phase)) return;
      // 인터뷰 · 낭독과 분리: 인터뷰 중이면 시작하지 않고, 질문 낭독 · 다른 소리는 멈춘다
      if (window.SrvInterview && window.SrvInterview.busy && window.SrvInterview.busy()) { toast('인터뷰가 진행 중이에요. 인터뷰를 마친 뒤 음성편지를 녹음해 주세요.'); return; }
      try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (_) {}
      document.querySelectorAll('audio, video').forEach((a) => { try { a.pause(); } catch (_) {} });
      all.forEach((c) => { try { c.pausePlayer && c.pausePlayer(); } catch (_) {} });
      const mime = pickMime();
      if (mime === null || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { set('denied', {err: '이 브라우저에서는 녹음을 할 수 없어요. 크롬 · 사파리 최신 판에서 열어 주세요.'}); return; }
      dropRecording(false);
      set('asking', {note: '', err: ''});
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true}});
      } catch (e) {
        const name = e && e.name;
        set('denied', {err: name === 'NotFoundError' || name === 'OverconstrainedError' ? '마이크를 찾지 못했어요. 마이크가 연결돼 있는지 확인해 주세요.'
          : name === 'NotReadableError' ? '다른 프로그램이 마이크를 쓰고 있어요. 그 프로그램을 끈 뒤 다시 시도해 주세요.'
          : '마이크를 쓸 수 있게 허락되지 않았어요.'});
        return;
      }
      let rec;
      try { rec = new MediaRecorder(stream, mime ? {mimeType: mime} : undefined); } catch (_) { stream.getTracks().forEach((t) => t.stop()); set('denied', {err: '이 브라우저에서는 녹음을 할 수 없어요.'}); return; }
      st.stream = stream; st.rec = rec; st.chunks = [];
      rec.addEventListener('dataavailable', (ev) => { if (ev.data && ev.data.size) st.chunks.push(ev.data); });
      // 마지막 dataavailable 다음에 오는 stop 이벤트를 받은 뒤에야 미리듣기로 (끝부분이 빠지지 않게)
      rec.addEventListener('stop', () => finalize(rec));
      stream.getAudioTracks().forEach((t) => t.addEventListener('ended', () => { if (st.rec === rec && rec.state === 'recording') { st.note = '마이크 연결이 끊겨 녹음이 멈췄어요. 멈추기 전까지 녹음된 것을 들어 보세요.'; stop(); } }));
      st.jobId = opts.mode === 'gen' ? (opts.currentJob ? opts.currentJob() : null) : null;
      st.jobLost = false;
      rec.start(1000);
      st.startAt = performance.now();
      set('recording');
      st.tick = setInterval(tick, 200);
      st.auto = setTimeout(() => { if (st.rec === rec && rec.state === 'recording') { st.note = '5분이 되어 녹음이 끝났어요. 들어 보고 저장해 주세요.'; stop(); } }, MAX_MS);
    }
    function tick() {
      if (st.phase !== 'recording') return;
      const ms = performance.now() - st.startAt;
      const t = root.querySelector('.vl-time'); if (t) t.textContent = `${clock(Math.min(ms, MAX_MS))} / ${clock(MAX_MS)}`;
      const soon = root.querySelector('.vl-soon'); if (soon && VC.warnSec) soon.hidden = !(MAX_MS - ms <= VC.warnSec * 1000);
      if (ms >= MAX_MS && st.rec && st.rec.state === 'recording') { st.note = st.note || '5분이 되어 녹음이 끝났어요. 들어 보고 저장해 주세요.'; stop(); }   // 시작 시각 기준 — 타이머가 늦어도 넘기지 않게
    }
    function stop() {
      const rec = st.rec;
      if (!rec || st.phase !== 'recording') return;
      st.ms = Math.min(MAX_MS, performance.now() - st.startAt);
      clearInterval(st.tick); clearTimeout(st.auto);
      set('stopping');
      try { if (rec.state === 'recording') { try { rec.requestData(); } catch (_) {} rec.stop(); } else finalize(rec); } catch (_) { finalize(rec); }
    }
    function finalize(rec) {
      if (st.rec !== rec) return;
      clearInterval(st.tick); clearTimeout(st.auto);
      if (st.phase === 'recording') st.ms = Math.min(MAX_MS, performance.now() - st.startAt);   // 저절로 멈춘 경우(화면 잠금 · 마이크 끊김)
      if (st.stream) st.stream.getTracks().forEach((t) => t.stop());                          // 마이크를 바로 놓는다
      const type = (rec.mimeType || (st.chunks[0] && st.chunks[0].type) || 'audio/webm').split(';')[0];
      st.blob = new Blob(st.chunks, {type});
      st.chunks = []; st.rec = null; st.stream = null;
      if (st.url) URL.revokeObjectURL(st.url);
      st.url = URL.createObjectURL(st.blob);
      st.upRid = newId(); st.upload = null; st.linkRid = null;                                // 새 녹음은 새 id
      if (!st.blob.size) { set('error', {err: '녹음된 소리가 없어요. 다시 녹음해 주세요.', lastErr: {code: 'too_short'}}); return; }
      set('preview');
    }
    // 녹음 중인 것 · 미리듣기를 정리 (upload 는 discardUpload 가)
    function dropRecording(keepUrl) {
      clearInterval(st.tick); clearTimeout(st.auto);
      if (st.rec) { const r = st.rec; st.rec = null; try { if (r.state !== 'inactive') r.stop(); } catch (_) {} }
      if (st.stream) { st.stream.getTracks().forEach((t) => t.stop()); st.stream = null; }
      try { player.pause(); } catch (_) {}
      if (!keepUrl && st.url) { URL.revokeObjectURL(st.url); player.removeAttribute('src'); try { player.load(); } catch (_) {} st.url = null; st.blob = null; st.ms = 0; }
    }
    // 버리기 · 재녹음: 연결 안 된 임시 업로드는 서버에서도 버린다 (실패하면 서버 정리에 맡긴다)
    function discardUpload() {
      const u = st.upload; st.upload = null;
      if (u && u.upload_id && st.phase !== 'ready') api.voiceDiscard(u.upload_id).catch(() => {});
    }
    function discard() { dropRecording(false); discardUpload(); set('idle', {note: '', err: '', upRid: null, linkRid: null, jobLost: false}); }
    function reset() { if (st.phase === 'ready') { dropRecording(false); set('idle', {upload: null, note: '', err: ''}); } }

    // ── 저장: 업로드 → (책이 있으면) 연결 ──
    async function save() {
      if (!st.blob || busy()) return;
      try { player.pause(); } catch (_) {}
      if (st.blob.size > VC.maxBytes) { set('error', {err: errText({status: 413}), lastErr: {status: 413}, errStep: 'upload'}); return; }
      if (!st.upload) {
        set('uploading');
        for (let tries = 0; ; tries++) {
          try { st.upload = await api.voiceUpload(st.blob, st.upRid); break; }
          catch (e) {
            if (e.code === 'upload_expired' && tries === 0) { st.upRid = newId(); continue; }   // 기한 지남 · 버려짐 — 탭에 원본이 있으니 새 id 로
            set('error', {err: errText(e), lastErr: e, errStep: 'upload'}); return;
          }
        }
      }
      const memoir = st.memoir || (opts.getMemoir && opts.getMemoir());
      if (!memoir) { set(st.jobLost ? 'orphan' : 'waiting_book'); return; }
      st.memoir = memoir;
      await link();
    }
    async function link(revision) {
      if (!st.upload || !st.memoir) return;
      set('linking');
      st.linkRid = st.linkRid || newId();
      let rev = revision;
      try {
        if (!Number.isInteger(rev)) rev = (await api.voiceGet(st.memoir)).revision || 0;
        const r = await api.voiceLink(st.memoir, {uploadId: st.upload.upload_id, requestId: st.linkRid, expectedRevision: rev});
        // 저장 완료는 연결 응답의 message.state === 'ready' (이번 음성) 를 확인한 뒤에만
        if (r && r.message && r.message.state === 'ready' && (!r.message.message_id || r.message.message_id === st.upload.upload_id)) {
          st.ms = r.message.duration_ms || st.ms;
          set('ready');
          VoiceCard.put(st.memoir, r);
          if (opts.onReady) opts.onReady(ctl, r);
          return;
        }
        set('error', {err: '책에 저장됐는지 확인하지 못했어요. 다시 저장해 주세요.', lastErr: {}, errStep: 'link'});
      } catch (e) {
        if (e.code === 'revision_conflict') { st.linkRid = null; set('conflict', {conflictRev: e.body && Number.isInteger(e.body.revision) ? e.body.revision : null}); return; }
        if (e.code === 'upload_expired' || e.code === 'upload_not_found') {
          // 올린 것이 사라졌다 — 탭에 원본이 있으면 새 id 로 다시 올린 뒤 연결
          st.upload = null; st.upRid = newId(); st.linkRid = null;
          if (st.blob) { st.phase = 'preview'; await save(); return; }   // (save 는 저장 중이면 멈추므로 상태를 먼저 되돌린다)
          set('error', {err: '올린 음성이 사라졌어요. 다시 녹음해 주세요.', lastErr: {code: 'too_short'}, errStep: 'link'}); return;
        }
        set('error', {err: errText(e), lastErr: e, errStep: 'link'});
      }
    }
    async function take() {   // 충돌 뒤 「지금 녹음으로 바꾸기」 — 지금 상태를 다시 읽고 그 revision 으로
      try { const g = await api.voiceGet(st.memoir); st.linkRid = newId(); await link(g.revision || 0); }
      catch (e) { set('error', {err: errText(e), lastErr: e, errStep: 'link'}); }
    }

    // ── 자서전 만들기와 맞추기 (진행 창) ──
    function setMemoir(id, title) { st.memoir = id; if (title) st.title = title; }
    function jobStarted(jobId) {
      if (st.phase === 'ready' || st.phase === 'idle' || st.phase === 'denied') { dropRecording(false); set('idle', {memoir: null, title: '', jobId, upload: null, note: '', err: ''}); }
      else st.newJob = jobId;   // 앞선 실패에서 남은 음성 — 이번 책이 끝나면 물어본다
    }
    // 책이 다 만들어졌다. 돌려주는 값: 진행 창을 열어 둬야 하는지(녹음 · 저장이 진행 중 · 사용자 확인이 필요)
    function jobDone(jobId, memoirId, title) {
      if (st.phase === 'idle' || st.phase === 'denied' || st.phase === 'ready') return false;
      if (!memoirId) return jobFailed(jobId);
      const mine = st.jobId === jobId && !st.jobLost;
      st.title = title || st.title;
      if (!mine) { st.memoir = null; st.candidate = memoirId; set('ask_attach'); return true; }   // 다른 작업에서 남은 음성 — 이 책에 붙일지 묻는다
      st.memoir = memoirId;
      if (st.phase === 'waiting_book') void link();
      else render();
      return true;
    }
    function jobFailed(jobId) {
      if (st.phase === 'idle' || st.phase === 'denied' || st.phase === 'ready') return false;
      if (st.jobId !== jobId && st.phase !== 'waiting_book') return holding();
      st.jobLost = true; st.memoir = null;
      if (st.phase === 'waiting_book') set('orphan'); else render();
      return true;
    }
    function holding() { return !['idle', 'denied', 'ready', 'waiting_book'].includes(st.phase); }
    function unsaved() { return !!st.blob && st.phase !== 'ready'; }
    ctl.pausePlayer = () => { try { player.pause(); } catch (_) {} };

    root.addEventListener('click', (e) => {
      const b = e.target.closest('[data-vl]'); if (!b || b.disabled) return;
      const a = b.dataset.vl;
      if (a === 'start') void start();
      else if (a === 'stop') stop();
      else if (a === 'listen') { if (player.paused) { all.forEach((c) => c !== ctl && c.pausePlayer()); VoiceCard.pause(); void player.play().catch(() => {}); } else player.pause(); }
      else if (a === 'again') { if (window.confirm('지금 녹음한 음성이 사라져요. 다시 녹음할까요?')) { discardUpload(); void start(); } }
      else if (a === 'save') void save();
      else if (a === 'retry') { if (st.errStep === 'link' && st.upload) void link(); else void save(); }
      else if (a === 'take') void take();
      else if (a === 'keep-old') { if (window.confirm('지금 녹음한 음성은 저장하지 않고 버릴까요?')) discard(); }
      else if (a === 'drop') { if (window.confirm('이 음성편지를 버릴까요? 되돌릴 수 없어요.')) discard(); }
      else if (a === 'attach') { st.memoir = st.candidate; st.jobLost = false; if (st.upload) void link(); else void save(); }
    });
    // 화면 잠금 · 다른 앱으로 갔다 오면 실제 녹음 상태를 확인해 알린다 (계속 녹음된다고 보장하지 않는다)
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) { st.hidden = st.phase === 'recording'; return; }
      if (!st.hidden) return;
      st.hidden = false;
      if (st.phase === 'recording' && st.rec && st.rec.state !== 'recording') { st.note = '화면이 꺼진 동안 녹음이 멈췄어요. 멈추기 전까지 녹음된 것을 들어 보세요.'; stop(); }
      else if (st.phase === 'recording') toast('녹음이 이어지고 있어요. 다른 화면에 있던 동안의 소리는 녹음되지 않았을 수 있어요 — 끝낸 뒤 들어 보고 확인해 주세요.', 6000);
      else if (st.phase === 'preview' && st.note) render();
    });
    render();
    return ctl;
  }

  /* ═══ 진행 창(자서전 만드는 중)의 녹음기 ═══ */
  const genDlg = document.getElementById('generation-dialog');
  let gen = null;
  if (genDlg) {
    const box = document.createElement('section');
    box.className = 'vl-box vl-gen'; box.setAttribute('aria-label', '가족 음성편지');
    const done = document.createElement('div');
    done.className = 'vl-gen-done'; done.hidden = true;
    done.innerHTML = '<p><b>자서전이 다 만들어졌어요.</b> 음성편지를 마친 뒤 초안을 볼 수 있어요.</p><button type="button" class="button outline" data-vl-view>초안 보기</button>';
    const note = genDlg.querySelector('.srv-gen-note');
    (note || genDlg.lastElementChild).before(box);
    box.after(done);
    gen = makeRecorder(box, {mode: 'gen', currentJob: () => VoiceLetter.jobId, getMemoir: () => null,
      onChange: (c) => { if (!done.hidden) done.querySelector('p').innerHTML = c.st.phase === 'ready' ? '<b>자서전이 다 만들어졌어요.</b> 음성편지도 책에 저장했어요.' : c.st.phase === 'idle' ? '<b>자서전이 다 만들어졌어요.</b>' : '<b>자서전이 다 만들어졌어요.</b> 음성편지를 마친 뒤 초안을 볼 수 있어요.'; },
      onReady: (c) => { toast('음성편지를 책에 저장했어요.'); if (!genDlg.open) toast(`「${c.st.title || '자서전'}」에 음성편지를 저장했어요.`); }});
    done.querySelector('[data-vl-view]').addEventListener('click', () => {
      if (gen.unsaved() && gen.holding() && !window.confirm('저장하지 않은 음성편지가 사라져요. 초안을 볼까요?')) return;
      if (gen.unsaved() && gen.holding()) gen.discard();
      done.hidden = true; genDlg.close();
      if (typeof navigate === 'function') navigate('draft'); // eslint-disable-line no-undef
    });
  }

  /* ═══ 전자책 마지막 쪽 — 음성편지 (책 주인용) ═══ */
  const VoiceCard = (() => {
    const cache = new Map();   // memoir_id → {status: 'loading' | 'ok' | 'error', revision, message}
    const blobs = new Map();   // message_id → Promise<objectURL>
    const audio = new Audio(); audio.preload = 'none';
    let playing = null, busy = false;
    const reader = () => document.body.classList.contains('ebook-mode');
    // 음성편지 쪽이 이미 화면에 있으면 그 칸만 다시 그린다(보던 쪽이 바뀌지 않게). 쪽이 생기거나 없어질 때만 쪽을 다시 나눈다
    function relayout() {
      if (!reader()) return;
      const here = document.querySelectorAll('[data-vl-card]');
      if (here.length && show()) { const html = pageHTML(); here.forEach((el) => { el.outerHTML = html; }); return; }
      window.dispatchEvent(new Event('resize'));
    }
    async function load(id, force) {
      if (!id) return;
      const c = cache.get(id);
      if (c && !force && c.status !== 'error') return;
      cache.set(id, Object.assign({}, c, {status: c && c.status === 'ok' && !force ? 'ok' : 'loading'}));
      try { const r = await api.voiceGet(id); put(id, r); }
      catch (e) { cache.set(id, {status: e.status === 404 ? 'none' : 'error'}); relayout(); }
    }
    function put(id, r) {
      cache.set(id, {status: 'ok', revision: (r && r.revision) || 0, message: r && r.message && r.message.state === 'ready' ? r.message : null});
      relayout(); paint();
    }
    // 재생할 바이트 — 로그인 쿠키 · 개발용 머리(idHeaders)가 필요해 fetch 로 받아 둔다. 받는 것은 미리, 재생은 눌러야
    function fetchUrl(m) {
      if (!blobs.has(m.message_id)) {
        blobs.set(m.message_id, (async () => {
          const p = String(m.playback_url || '').replace(/^\/api/, '');
          const res = await fetch(`${CONFIG.apiBase}/api${p}`, {credentials: 'include', headers: S.idHeaders ? S.idHeaders(p.split('?')[0]) : {}});
          if (!res.ok) throw Object.assign(new Error('audio'), {status: res.status});
          return URL.createObjectURL(await res.blob());
        })().catch((e) => { blobs.delete(m.message_id); throw e; }));
      }
      return blobs.get(m.message_id);
    }
    const current = () => { const id = typeof state !== 'undefined' && state ? state.savedMemoirId : null; return id ? {id, c: cache.get(id)} : null; }; // eslint-disable-line no-undef
    function show() { const x = current(); return !!(x && x.c && (x.c.status === 'ok' || x.c.status === 'error')); }
    function pageBlock(sections) {
      if (!show() || !sections || !sections.length) return null;
      const n = sections.length - 1, len = Array.from(sections[n] || '').length;
      return {voice: true, section: n, start: len, end: len};
    }
    function pageHTML() {
      if (!show()) return '';
      const {c} = current(), m = c.message;
      let inner;
      if (c.status === 'error') inner = `<p class="ebv-lead">음성편지를 불러오지 못했어요.</p><button type="button" class="button outline ebv-btn" data-vlc="reload">다시 불러오기</button>`;
      else if (m) {
        void fetchUrl(m).catch(() => {});
        const on = playing === m.message_id && !audio.paused;
        inner = `<p class="ebv-lead">가족이 목소리로 남긴 편지예요.</p><p class="ebv-len">음성 길이 <b>${long(m.duration_ms)}</b></p>
          <button type="button" class="button primary ebv-play" data-vlc="play" aria-pressed="${on}">${on ? `${icon('pause')}<span>멈추기</span>` : `${icon('play')}<span>음성편지 듣기</span>`}</button>
          <p class="ebv-pos" aria-live="off">${playing === m.message_id && audio.currentTime ? `${clock(audio.currentTime * 1000)} / ${clock(m.duration_ms)}` : ''}</p>
          <div class="ebv-tools"><button type="button" class="button outline ebv-btn" data-vlc="replace" ${busy ? 'disabled' : ''}>${icon('mic')}<span>다시 녹음해 바꾸기</span></button><button type="button" class="button outline ebv-btn ebv-del" data-vlc="delete" ${busy ? 'disabled' : ''}>${icon('close')}<span>지우기</span></button></div>`;
      } else inner = `<p class="ebv-lead">아직 음성편지가 없어요. 가족의 목소리로 한마디 남겨 보세요 (최대 5분).</p><button type="button" class="button outline ebv-btn" data-vlc="add">${icon('mic')}<span>음성편지 남기기</span></button>`;
      return `<section class="ebook-section ebook-voice" data-vl-card><span class="ebook-chapter-label">음성편지</span><h2>목소리로 남긴 편지</h2>${inner}</section>`;
    }
    function paint() {
      const x = current(); if (!x || !x.c || !x.c.message) return;
      const m = x.c.message, on = playing === m.message_id && !audio.paused;
      document.querySelectorAll('[data-vl-card] [data-vlc="play"]').forEach((b) => { b.setAttribute('aria-pressed', String(on)); b.innerHTML = on ? `${icon('pause')}<span>멈추기</span>` : `${icon('play')}<span>음성편지 듣기</span>`; });
      document.querySelectorAll('[data-vl-card] .ebv-pos').forEach((p) => { p.textContent = playing === m.message_id && audio.currentTime ? `${clock(audio.currentTime * 1000)} / ${clock(m.duration_ms)}` : ''; });
    }
    ['play', 'pause', 'ended', 'timeupdate'].forEach((ev) => audio.addEventListener(ev, paint));
    audio.addEventListener('ended', () => { audio.currentTime = 0; });
    async function play() {
      const x = current(); if (!x || !x.c || !x.c.message) return;
      const m = x.c.message;
      if (playing === m.message_id && !audio.paused) { audio.pause(); return; }
      all.forEach((c) => c.pausePlayer && c.pausePlayer());
      try {
        const url = await fetchUrl(m);
        if (playing !== m.message_id) { audio.src = url; playing = m.message_id; }
        await audio.play();
      } catch (e) {
        if (e && e.status === 404) { toast('음성편지가 바뀌었어요. 다시 불러올게요.'); void load(x.id, true); }
        else if (e && e.name === 'NotAllowedError') toast('한 번 더 눌러 들어 주세요.');
        else toast('음성편지를 불러오지 못했어요. 잠시 뒤 다시 눌러 주세요.');
      }
    }
    async function remove() {
      const x = current(); if (!x || !x.c || !x.c.message || busy) return;
      if (!window.confirm('이 자서전의 음성편지를 지울까요? 지우면 되돌릴 수 없어요.')) return;
      busy = true; relayout();
      try {
        await api.voiceDelete(x.id, x.c.revision || 0);
        if (playing === x.c.message.message_id) { audio.pause(); audio.removeAttribute('src'); playing = null; }
        busy = false; await load(x.id, true);   // 서버가 지운 뒤에만 화면에서 뺀다
        toast('음성편지를 지웠어요.');
      } catch (e) {
        busy = false;
        if (e.code === 'revision_conflict') { toast('다른 곳에서 음성편지가 바뀌었어요. 다시 불러왔으니 확인해 주세요.', 5000); await load(x.id, true); }
        else if (e.code === 'message_not_found') { await load(x.id, true); }
        else { toast(`음성편지를 지우지 못했어요. ${errText(e)}`.replace(' 음성은 그대로 있어요 — 다시 저장해 주세요.', ' 잠시 뒤 다시 해 주세요.'), 5000); relayout(); }
      }
    }
    function pause() { try { audio.pause(); } catch (_) {} }
    document.addEventListener('click', (e) => {
      const b = e.target.closest('[data-vl-card] [data-vlc]'); if (!b || b.disabled) return;
      e.stopPropagation();
      const a = b.dataset.vlc, x = current();
      if (a === 'play') void play();
      else if (a === 'delete') void remove();
      else if (a === 'reload' && x) void load(x.id, true);
      else if ((a === 'replace' || a === 'add') && x) openBookRecorder(x.id, a === 'replace');
    }, true);
    // 읽기 화면을 열면 그 책의 음성편지를 읽어 둔다 · 화면을 떠나면 소리를 멈춘다
    window.addEventListener('memoir:screen', (e) => {
      if (e.detail && e.detail.screen === 'reader') { const x = current(); if (x) void load(x.id); }
      else pause();
    });
    window.addEventListener('hashchange', () => { if (location.hash === '#reader') { const x = current(); if (x) void load(x.id); } else pause(); });
    return {load, put, pageBlock, pageHTML, pause, cache};
  })();

  /* ═══ 책 음성 남기기 · 바꾸기 창 ═══ */
  let bookDlg = null, bookRec = null;
  function openBookRecorder(memoirId, replacing) {
    if (!bookDlg) {
      bookDlg = document.createElement('dialog');
      bookDlg.id = 'voice-letter-dialog'; bookDlg.className = 'review-dialog vl-dialog';
      bookDlg.setAttribute('aria-labelledby', 'vl-dialog-title');
      bookDlg.innerHTML = `<button type="button" class="dialog-close" data-vld="close" aria-label="닫기">${icon('close')}</button><h2 id="vl-dialog-title" tabindex="-1"></h2><p class="vl-dialog-note"></p><section class="vl-box"></section>`;
      document.body.append(bookDlg);
      bookRec = makeRecorder(bookDlg.querySelector('.vl-box'), {mode: 'book', getMemoir: () => bookDlg.dataset.memoir,
        onReady: () => { toast('음성편지를 책에 저장했어요.'); }});
      const tryClose = (e) => {
        const r = bookRec;
        if (['asking', 'recording', 'stopping', 'uploading', 'linking'].includes(r.st.phase)) { if (e) e.preventDefault(); toast(r.st.phase === 'recording' ? '녹음을 끝낸 뒤 닫아 주세요.' : '저장하는 중이에요. 잠시만 기다려 주세요.'); return; }
        if (r.unsaved() && !window.confirm('저장하지 않은 음성편지가 사라져요. 닫을까요?')) { if (e) e.preventDefault(); return; }
        if (r.unsaved()) r.discard();
        if (!e) bookDlg.close();
      };
      bookDlg.addEventListener('cancel', tryClose);
      bookDlg.querySelector('[data-vld="close"]').addEventListener('click', () => tryClose(null));
    }
    bookDlg.dataset.memoir = memoirId;
    bookDlg.querySelector('#vl-dialog-title').textContent = replacing ? '음성편지 다시 녹음하기' : '음성편지 남기기';
    bookDlg.querySelector('.vl-dialog-note').textContent = replacing ? '새 음성을 「저장」해 책에 저장되기 전까지는 지금 음성편지가 그대로 남아 있어요.' : '녹음한 뒤 들어 보고 「저장」을 눌러야 책에 저장돼요.';
    bookRec.st.memoir = memoirId;
    if (bookRec.st.phase === 'ready' || bookRec.st.phase === 'idle' || bookRec.st.phase === 'denied') { bookRec.reset(); bookRec.st.memoir = memoirId; bookRec.render(); }
    VoiceCard.pause();
    bookDlg.showModal(); bookDlg.querySelector('#vl-dialog-title').focus();
  }

  // 닫기 · 새로고침 경고 (브라우저가 허락하는 만큼) — 저장하지 않은 음성 · 저장 중
  window.addEventListener('beforeunload', (e) => {
    if (all.some((c) => c.unsaved() || ['recording', 'asking', 'uploading', 'linking'].includes(c.st.phase))) { e.preventDefault(); e.returnValue = ''; }
  });

  const VoiceLetter = {
    jobId: null,
    gen, card: VoiceCard,
    // srv-memoir 이 부른다
    jobStarted(jobId) { VoiceLetter.jobId = jobId; if (gen) gen.jobStarted(jobId); const d = genDlg && genDlg.querySelector('.vl-gen-done'); if (d) d.hidden = true; },
    jobDone(jobId, memoirId, title) {
      if (!gen) return false;
      const hold = gen.jobDone(jobId, memoirId, title);
      const done = genDlg && genDlg.querySelector('.vl-gen-done');
      if (done) done.hidden = !hold;
      if (hold && gen) gen.render();
      if (memoirId) VoiceCard.cache.delete(memoirId);
      return hold;
    },
    jobFailed(jobId) { VoiceLetter.jobId = null; return gen ? gen.jobFailed(jobId) : false; },
    // 진행 창을 닫아도 되는지 (녹음 중 · 저장 전 음성)
    canCloseGen() {
      if (!gen) return true;
      const p = gen.st.phase;
      if (['asking', 'recording', 'stopping'].includes(p)) { toast('녹음을 끝낸 뒤 닫아 주세요.'); return false; }
      if (['preview', 'error', 'conflict', 'orphan', 'ask_attach'].includes(p)) {
        if (!window.confirm('저장하지 않은 음성편지가 사라져요. 창을 닫을까요?')) return false;
        gen.discard();
      }
      return true;   // uploading · waiting_book · linking 은 뒤에서 이어진다
    },
    pageBlock: (sections) => VoiceCard.pageBlock(sections),
    pageHTML: () => VoiceCard.pageHTML(),
    openBookRecorder,
  };
  window.MemoirVoiceLetter = VoiceLetter;
}());
