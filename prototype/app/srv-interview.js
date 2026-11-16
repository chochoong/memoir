(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     srv-interview — 시안의 라디오 스튜디오 화면 + 운영(v0.54)의 인터뷰 엔진
       · 서버 상태(snapshot)가 화면의 유일한 기준이다.
           SPEAKING   질문을 읽어 주는 중  → 라디오 「질문 낭독」(헤드폰 빛)
           LISTENING  듣는 중            → ON AIR · 마이크 레벨
           PROCESSING 정리 중            → 정리하는 중
           CLOSED     마쳤다             → 「이야기 확인」 창 → 엽서 만들기
       · 엔진(시작 · 0.3초 조회 · 소리 올리기 · 낭독 · 글로 쓰기 · 마지막 말씀 확정 · 남은 회차 닫기)은
         v0.54 의 beginInterview · applySnapshot · readQuestion · sendText · confirmLastSpeech 를 그대로 옮겼다.
       · 「잠시 쉬기」는 서버에 일시정지가 없어 0.05초 무음을 2초마다 올려 회차를 붙들어 둔다 (v0.54 와 같다).
       · 엽서는 회차가 닫힌 뒤 「엽서 만들기」를 눌러야 만든다 (POST /api/sessions/{id}/postcard).
     ═══════════════════════════════════════════════════════════════ */
  const {api, AUTH, CONFIG, LINK, log, sleep} = window.Srv;
  const {speaker, startRecorder, MIME} = window.SrvAudio;

  let snap = null, sessionId = null, recorder = null;
  let pollTimer = null, pollBusy = false, spoken = null, uploadQueue = Promise.resolve();
  let closing = false, stopping = false, held = false, holdTimer = null;
  let inputMode = 'voice', micOk = false, sending = false, awaitingReply = false, drainSince = 0;
  let ttsFailed = false, resumeSent = false, level = 0, levelRaf = null, starting = false;
  let topic = '', elderId = '';
  let queued = false;       // 「이야기 남기기」를 눌렀는데 아직 보낼 수 없다 — 보낼 수 있게 되면 바로 보낸다
  let skippedQ = null;      // 글을 보내려고 낭독을 건너뛴 질문 — 낭독이 끝나도 tts-done 을 다시 올리지 않는다

  const $q = (s) => document.querySelector(s);
  const isListening = () => snap && snap.state === 'LISTENING';
  const isHearing = () => isListening() || !!(snap && snap.state === 'PROCESSING' && snap.resumable);
  const micOpen = () => isHearing() && !held && inputMode === 'voice';
  const live = () => !!sessionId && !closing;

  /* ── 이 기기에서 연 회차를 기억 — 마치기 없이 나갔다 다시 오면 먼저 닫는다 (v0.54 그대로) ── */
  const LIVE_KEY = 'liveSession';
  const liveWho = () => String((AUTH.user && AUTH.user.user_id) || '');
  function liveKeep(id) { try { localStorage.setItem(LIVE_KEY, JSON.stringify({who: liveWho(), id})); } catch (_) {} }
  function liveForget(id) { try { const v = JSON.parse(localStorage.getItem(LIVE_KEY) || 'null'); if (!v || !id || v.id === id) localStorage.removeItem(LIVE_KEY); } catch (_) {} }
  function liveLeft() { try { const v = JSON.parse(localStorage.getItem(LIVE_KEY) || 'null'); return v && v.id && v.who === liveWho() ? String(v.id) : ''; } catch (_) { return ''; } }
  async function closeLeftover() {
    const id = liveLeft();
    if (!id) return false;
    liveForget(id);
    try {
      const s = await api.get(id);
      if (!s || s.state === 'CLOSED') return false;
      await api.abort(id);
      return true;
    } catch (_) { return false; }
  }

  /* ── 화면 ── */
  const ORD = ['첫', '두', '세', '네', '다섯', '여섯', '일곱', '여덟', '아홉', '열'];
  const nth = (n) => n <= ORD.length ? `${ORD[n - 1]} 번째 이야기` : `${n}번째 이야기`;
  function phase() {
    if (!snap) return 'processing';
    if (held) return 'paused';
    if (inputMode !== 'voice') return 'text';
    return ({SPEAKING: 'reading', LISTENING: 'listening', PROCESSING: 'processing', CLOSED: 'idle'})[snap.state] || 'processing';
  }
  function setButton(el, icon, label, disabled) {
    el.innerHTML = `${icons(icon)}<span>${escapeText(label)}</span>`;
    el.disabled = !!disabled;
  }
  function render() {
    const mode = phase();
    setInterviewMode(mode);                // 시안의 라디오 · 버튼 모양을 그대로 쓴다
    const pause = $q('#pause-interview'), toggle = $q('#toggle-answer');
    const status = $q('#listening-status'), hint = $q('#studio-hint'), sub = $q('#question-hint');
    const send = $q('#answer-panel [type="submit"]'), box = $q('#answer-text');
    if (!snap) {
      setButton(pause, 'spark', '준비하는 중', true);
      toggle.disabled = true;
      status.textContent = '이야기를 준비하고 있어요';
      hint.textContent = '마이크를 쓸지 여쭤볼 수 있어요. 「허용」을 눌러 주세요.';
      sub.textContent = '';
      return;
    }
    if (snap.state !== 'SPEAKING') ttsFailed = false;
    const n = ((snap.fragments || []).filter((f) => f.idx > 0).length) + 1;
    $q('#interview-counter').textContent = nth(n);
    if (snap.next_question) $q('#interview-question').textContent = snap.next_question;
    toggle.disabled = inputMode === 'switching' || sending || (inputMode === 'keyboard' && !micOk);
    toggle.innerHTML = `${icons(inputMode === 'voice' ? 'pen' : 'mic')}${inputMode === 'voice' ? '글로 쓰기' : '말로 하기'}`;
    if (mode === 'paused') {
      setButton(pause, 'play', '다시 말하기', false);
      status.textContent = '잠시 쉬어가요'; hint.textContent = '준비되시면 「다시 말하기」를 눌러 주세요.'; sub.textContent = '';
    } else if (mode === 'reading') {
      if (ttsFailed) setButton(pause, 'arrow', '소리 없이 넘어가기', false);
      else setButton(pause, 'mic', '읽어 드리는 중', true);
      status.textContent = '질문을 읽어 드릴게요';
      hint.textContent = ttsFailed ? '소리를 틀지 못했어요. 「소리 없이 넘어가기」를 눌러 주세요.' : '질문이 끝나면 편하게 말씀해 주세요.';
      sub.textContent = '';
    } else if (mode === 'listening') {
      setButton(pause, 'pause', '잠시 쉬기', false);
      status.textContent = '녹음 중이에요'; hint.textContent = '천천히, 편하게 말해도 괜찮아요. 말씀을 멈추면 다음 질문으로 넘어가요.'; sub.textContent = '';
    } else if (mode === 'processing') {
      setButton(pause, 'spark', '정리하는 중', true);
      status.textContent = '잘 들었어요'; hint.textContent = '다음 이야기를 고르고 있어요.'; sub.textContent = '';
    } else if (mode === 'text') {
      // 글로 쓰기 — v0.54 renderCompose 와 같은 규칙
      const text = box.value.trim();
      const leftover = snap.state === 'LISTENING' && snap.audio_bytes > 0;
      if (!leftover) drainSince = 0; else if (!drainSince) drainSince = Date.now();
      const stuck = leftover && Date.now() - drainSince > CONFIG.interview.voiceDrainMs;
      let msg = '떠오르는 기억을 천천히 적어 주세요.';
      if (inputMode === 'switching') msg = '말씀하신 소리를 마저 보내고 있어요…';
      else if (sending) msg = '보내는 중이에요…';
      else if (queued) msg = snap.state === 'SPEAKING' ? '질문을 다 읽으면 바로 보낼게요.' : '앞서 하신 말씀을 정리하는 중이에요. 끝나면 바로 보낼게요.';
      else if (snap.state === 'SPEAKING') msg = ttsFailed ? '질문 소리를 틀지 못했어요. 글을 써서 보내시면 돼요.' : '질문을 읽고 있어요. 다 쓰셨으면 지금 「이야기 남기기」를 눌러도 돼요.';
      else if (snap.state === 'PROCESSING') msg = '이야기를 정리하고 있어요. 미리 써 두셔도 돼요.';
      else if (stuck) msg = '앞서 하신 말씀을 정리하는 데 시간이 걸리고 있어요. 써 두신 글은 정리가 끝나면 보낼 수 있어요.';
      else if (leftover) msg = '앞서 하신 말씀을 먼저 정리하고 있어요. 「이야기 남기기」를 누르면 정리가 끝난 뒤 보내요.';
      else if (!micOk) msg = '마이크를 쓸 수 없어 글로 이야기를 나눠요.';
      status.textContent = awaitingReply ? '잘 받았어요' : '글로 이야기하는 중';
      hint.textContent = msg; sub.textContent = '';
      box.readOnly = sending;
      // 버튼은 끄지 않는다 — 지금 보낼 수 없으면 눌렀을 때 기다렸다가 보낸다 (금지 표시로 막혀 보이지 않게)
      send.disabled = inputMode !== 'keyboard';
      send.setAttribute('aria-busy', String(sending || queued));
      send.classList.toggle('srv-send-wait', sending || queued);
      void text;
    }
  }

  // 라디오 마이크 레벨 — 실제 목소리 크기
  function levelLoop() {
    let smooth = 0;
    const loop = () => {
      const target = micOpen() ? Math.min(1, level * 5.5) : 0;
      smooth += (target - smooth) * 0.22;
      window.RadioFeedback?.setLevel?.(smooth);
      levelRaf = requestAnimationFrame(loop);
    };
    loop();
  }

  /* ── 시작 ── */
  async function start(opts) {
    if (starting || live()) return live();
    starting = true;
    elderId = opts.elderId; topic = (opts.topic || '').slice(0, CONFIG.interview.topicMax);
    snap = null; sessionId = null; closing = false; stopping = false; held = false; spoken = null;
    inputMode = 'voice'; micOk = false; sending = false; awaitingReply = false; ttsFailed = false; resumeSent = false; queued = false; skippedQ = null;
    uploadQueue = Promise.resolve();
    $q('#answer-text').value = '';
    $q('#interview-question').textContent = '첫 질문을 준비하고 있어요…';
    render();
    try {
      await speaker.unlock();
      try {
        recorder = await startRecorder({
          onLevel: (l) => { level = l.rms; },
          onChunk: (pcm) => {
            if (!sessionId || !micOpen()) return;
            uploadQueue = uploadQueue
              .then(() => {
                if (!sessionId || !isHearing()) return null;
                if (snap.state === 'PROCESSING') resumeSent = true;
                return api.audio(sessionId, pcm, MIME);
              })
              .then((s) => { if (s) applySnapshot(s); })
              .catch((e) => log('올림', `실패 · ${e.message || e}`));
          },
        });
        micOk = true; inputMode = 'voice';
      } catch (e) {
        micOk = false; inputMode = 'keyboard';
        toast((e && e.name) === 'NotAllowedError' ? '마이크를 허용하지 않아 글로 이야기를 나눠요.' : '마이크를 쓸 수 없어 글로 이야기를 나눠요.');
      }
      // 어르신 링크(/i#토큰) — 회차는 링크가 정한다. POST /api/i/start (같은 기기에서 다시 누르면 같은 회차)
      if (opts.link) {
        const s = await api.linkStart(opts.pickTopic || '');
        sessionId = s.session_id || 'link';
        applySnapshot(s);
        startPolling();
        levelLoop();
        return true;
      }
      const body = {
        title: topic || `${new Date().toISOString().slice(0, 10)} 기록`,
        seed: topic, pace: CONFIG.session.pace, max_turn: CONFIG.session.max_turn,
        topic, elder_id: elderId,
      };
      const closedLeft = await closeLeftover();
      const s = await api.start(body);
      sessionId = s.session_id;
      liveKeep(sessionId);
      if (closedLeft) toast('하던 이야기는 저장해 두었어요. 엽서보기의 「엽서로 만들기 전의 이야기」에서 볼 수 있어요.');
      applySnapshot(s);
      startPolling();
      levelLoop();
      return true;
    } catch (e) {
      if (recorder) { recorder.stop(); recorder = null; }
      micOk = false; inputMode = 'voice'; snap = null; sessionId = null;
      const msg = e.status === 429 ? `${e.message || '이미 진행 중인 이야기가 있어요.'} 다른 기기나 초대 링크로 진행 중인 이야기가 있을 수 있어요. 마치기 없이 나간 이야기는 30분이 지나면 저절로 정리돼요.`
        : e.status === 503 ? '지금은 이야기를 시작할 수 없어요. 잠시 뒤에 다시 시도해 주세요.'
        : e.status === 400 || e.status === 404 ? '이야기 주인공을 다시 골라 주세요.'
        : e.status === 422 ? '주제를 확인해 주세요.'
        : '서버에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.';
      log('회차', `열기 실패 · ${e.status || ''} ${e.message || e}`);
      if (opts.link) { window.SrvLinks?.failed(e); return false; }
      toast(msg);
      window.RolePreview?.complete?.({id: 'failed'});
      navigate('start');
      return false;
    } finally { starting = false; }
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(async () => {
      if (!sessionId || pollBusy) return;
      pollBusy = true;
      try { applySnapshot(await api.get(sessionId)); }
      catch (e) { if (e.status === 404) void finishSession('gone'); }
      finally { pollBusy = false; }
    }, CONFIG.pollMs);
  }
  function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

  function applySnapshot(s) {
    if (!s || closing) return;
    if (stopping && s.state !== 'CLOSED') return;
    const prev = snap;
    snap = s;
    if (!prev || prev.session_id !== s.session_id) spoken = null;
    if (recorder) recorder.setActive(micOpen());
    if (s.state !== 'LISTENING' && s.state !== 'PROCESSING') resumeSent = false;
    if (prev && prev.state === 'LISTENING' && s.state === 'PROCESSING') resumeSent = false;
    if (prev && prev.state === 'PROCESSING' && s.state === 'LISTENING' && resumeSent) resumeSent = false;
    else if (prev && prev.state === 'PROCESSING' && s.state === 'LISTENING'
        && s.fragments.length === prev.fragments.length && inputMode === 'voice') toast('말씀이 들어오지 않았어요. 다시 듣고 있습니다.');
    if (s.state === 'SPEAKING' || s.state === 'CLOSED' || (prev && prev.state === 'PROCESSING' && s.state === 'LISTENING')) awaitingReply = false;
    if (s.state === 'CLOSED') { void finishSession(); return; }
    if (queued && !sending && inputMode === 'keyboard' && s.state === 'LISTENING' && !(s.audio_bytes > 0)) setTimeout(() => { if (queued) void sendText(); }, 0);
    if (location.hash === '#interview') render();
    if (s.state === 'SPEAKING' && s.next_question && spoken !== s.next_question) {
      spoken = s.next_question;
      void readQuestion(s.session_id, s.next_question, !!s.question_audio_stream);
    }
  }

  async function readQuestion(id, q, stream) {
    const stopped = () => stopping || closing || id !== sessionId || skippedQ === q;
    try {
      if (stream) {
        const res = await api.questionStream(id);
        if (stopped()) { if (res) void res.body.cancel(); return; }
        if (!res) { await api.ttsDone(id).then(applySnapshot); return; }
        await speaker.playStream(res);
        if (stopped()) return;
        applySnapshot(await api.ttsDone(id));
        return;
      }
      const blob = await api.questionAudio(id);
      if (stopped()) return;
      if (!blob) { await api.ttsDone(id).then(applySnapshot); return; }
      await speaker.play(blob);
      if (stopped()) return;
      applySnapshot(await api.ttsDone(id));
    } catch (e) {
      log('낭독', `실패 · ${e.message || e}`);
      if (stopped()) return;
      ttsFailed = true;
      render();
    }
  }

  /* ── 잠시 쉬기 ── */
  function setHold(on) {
    held = on;
    if (recorder) recorder.setActive(!on && isListening());
    clearInterval(holdTimer);
    if (on) holdTimer = setInterval(keepAlive, 2000);
    render();
  }
  function keepAlive() {
    if (!sessionId || !isListening()) return;
    const silence = new Int16Array(800).buffer;
    uploadQueue = uploadQueue
      .then(() => (sessionId && isListening()) ? api.audio(sessionId, silence, MIME) : null)
      .then((s) => { if (s) applySnapshot(s); })
      .catch(() => {});
  }

  /* ── 글로 쓰기 ── */
  async function waitFor(id, pred, ms) {
    const until = Date.now() + ms;
    while (Date.now() < until) {
      try { const s = await api.get(id); applySnapshot(s); if (pred(s)) return true; }
      catch (e) { if (e.status === 404) return false; }
      await sleep(300);
    }
    return false;
  }
  async function toKeyboard() {
    if (inputMode !== 'voice' || stopping || closing || !sessionId) return;
    if (recorder) recorder.flushNow();
    inputMode = 'switching';
    if (recorder) recorder.setActive(false);
    render();
    await uploadQueue.catch(() => {});
    try { applySnapshot(await api.get(sessionId)); } catch (_) {}
    if (stopping || closing) return;
    inputMode = 'keyboard';
    render();
    $q('#answer-text').focus();
  }
  // 보내지 않은 글이 있으면 지워진다고 한 번 여쭙는다. 「지우기」를 고르면 글을 비우고 true
  const draft = () => $q('#answer-text').value.trim();
  async function askDropDraft(title, ok) {
    if (!draft()) return true;
    const yes = await window.MemoirTrash.confirm({title, items: [draft().slice(0, 60) + (draft().length > 60 ? '…' : '')],
      desc: '「이야기 남기기」를 누르지 않은 글은 저장되지 않아요. 계속하면 이 글은 지워져요.', ok, keep: '계속 쓰기'});
    if (yes) $q('#answer-text').value = '';
    else $q('#answer-text').focus();
    return yes;
  }
  async function toVoice() {
    if (inputMode !== 'keyboard' || !micOk || sending) return;
    if (!await askDropDraft('쓰던 글을 지우고 말로 할까요?', '지우고 말로 하기')) return;
    queued = false;
    if (inputMode !== 'keyboard' || sending || !live()) return;
    inputMode = 'voice';
    if (recorder) recorder.setActive(micOpen());
    render();
  }
  async function sendText() {
    const box = $q('#answer-text');
    const text = box.value.trim();
    if (!text) { toast('떠오르는 기억을 한 줄 적어주세요.'); box.focus(); return; }
    if (sending || !sessionId || inputMode !== 'keyboard' || stopping || closing || !snap) return;
    // 질문을 읽는 중이면 낭독을 건너뛰고 듣기로 넘긴다 (다 쓰셨으니 기다리게 하지 않는다)
    if (snap.state === 'SPEAKING' && !queued) {
      skippedQ = snap.next_question;
      speaker.stop();
      try { applySnapshot(await api.ttsDone(sessionId)); } catch (_) { /* 이미 넘어갔으면 아래에서 본다 */ }
      if (!snap || stopping || closing) return;
    }
    // 아직 보낼 수 없다(정리 중 · 앞서 하신 말씀이 남음 · 다음 질문 낭독 중) — 기다렸다가 보낸다
    if (snap.state !== 'LISTENING' || snap.audio_bytes > 0) { queued = true; render(); return; }
    queued = false;
    sending = true; render();
    const id = sessionId, before = snap.fragments.length;
    try {
      let s;
      try { s = await api.speech(id, text); }
      catch (e) {
        if (e.status !== 409) throw e;
        if (!await waitFor(id, (x) => x.state === 'LISTENING', 5000)) throw e;
        s = await api.speech(id, text);
      }
      box.value = '';
      awaitingReply = true;
      applySnapshot(s);
      try { applySnapshot(await api.done(id)); } catch (_) { /* 3초 뒤 저절로 확정된다 */ }
    } catch (e) {
      const got = !e.status && await waitFor(id, (x) => x.fragments.length > before
        && String(x.fragments[x.fragments.length - 1].answer || '').includes(text), 4500);
      if (got) box.value = '';
      else toast('글을 보내지 못했어요. 다시 「이야기 남기기」를 눌러 주세요.');
    } finally { sending = false; if (snap) render(); }
  }

  /* ── 마치기 ── */
  async function confirmLastSpeech() {
    if (!CONFIG.session.confirmBeforeStop) return;
    if (!snap || (snap.state !== 'LISTENING' && snap.state !== 'PROCESSING')) return;
    $q('#listening-status').textContent = '마지막 말씀을 받아 적는 중이에요';
    $q('#studio-hint').textContent = '잠시만 기다려 주세요.';
    const until = Date.now() + CONFIG.session.confirmWaitMs;
    const settle = async (n) => {
      while (Date.now() < until) {
        await sleep(300);
        let s;
        try { s = await api.get(sessionId); } catch (_) { return; }
        snap = s;
        if (s.state !== 'PROCESSING' || s.fragments.length > n) return;
      }
    };
    if (snap.state === 'PROCESSING') {
      await settle(snap.fragments.length);
      if (!snap || snap.state !== 'LISTENING') return;
    }
    const n = snap.fragments.length;
    try { snap = await api.done(sessionId); } catch (_) { return; }
    await settle(n);
  }
  async function stop() {
    if (stopping) return;
    if (sending) { toast('글을 보내는 중이에요. 잠시 뒤에 눌러 주세요.'); return; }
    if (draft()) {
      if ($q('#finish-dialog').open) $q('#finish-dialog').close();
      if (!await askDropDraft('쓰던 글을 지우고 인터뷰를 마칠까요?', '지우고 마치기')) return;
      if (stopping || !live()) return;
    }
    held = false; clearInterval(holdTimer);
    stopping = true; queued = false;
    speaker.stop();
    if (recorder) { recorder.flushNow(); recorder.setActive(false); }
    if (!sessionId) { void finishSession(); return; }
    stopPolling();
    const btn = $q('#confirm-finish'); btn.disabled = true; btn.textContent = '마지막 말씀을 저장하는 중…';
    await uploadQueue.catch(() => {});
    await confirmLastSpeech();
    try { applySnapshot(await api.abort(sessionId)); if (!closing) void finishSession(); }
    catch (_) { void finishSession(); }
  }

  async function finishSession(why) {
    if (closing) return;
    closing = true;
    const id = sessionId;
    if (id && !LINK.on) liveForget(id);
    held = false; clearInterval(holdTimer);
    stopPolling();
    if (levelRaf) cancelAnimationFrame(levelRaf);
    window.RadioFeedback?.setLevel?.(0);
    speaker.stop();
    if (recorder) { recorder.stop(); recorder = null; }
    const fragments = (snap && snap.fragments) || [];
    const expect = Math.max(0, ...fragments.map((f) => f.idx));
    $q('#answer-text').value = ''; state.answers = [];
    const btn = $q('#confirm-finish'); btn.disabled = false; btn.textContent = '이야기 확인하기';
    if ($q('#finish-dialog').open) $q('#finish-dialog').close();
    if (LINK.on) { setInterviewMode('idle'); window.SrvLinks?.done(why); return; }
    window.RolePreview?.complete?.({id: id || 'none', body: ''});
    setInterviewMode('idle');
    state.pickRecords = false;
    navigate('records');
    if (id) {
      window.SrvRecords?.reload();
      void openStory(id, {expect, why, topic});
    }
  }

  /* ═══════════════════════════════════════════════════════════════
     이야기 확인 → 엽서 만들기 (시안의 「이야기 확인」 창)
       · GET /api/sessions/{id}/record 로 나눈 이야기(질문 · 답)를 읽는다.
         방금 마친 회차면 마지막 답이 DB 에 닿을 때까지 잠깐 다시 읽는다 (v0.54 openReview 와 같다).
       · 「엽서 만들기」 = v0.54 serverCard — 이미 있으면 꺼내고, 409 busy 면 기록을 보며 기다린다.
     ═══════════════════════════════════════════════════════════════ */
  let rvId = null, rvReq = 0, rvBusy = false, rvHasCard = false;
  const dlg = $q('#story-review-dialog');
  async function openStory(id, opts = {}) {
    const my = ++rvReq;
    rvId = id; rvHasCard = false;
    $q('#story-review-title').textContent = opts.topic || '나눈 이야기';
    $q('#story-review-body').innerHTML = '<p class="srv-rv-wait">나눈 이야기를 불러오고 있어요…</p>';
    $q('#story-review-note').textContent = '나눈 이야기는 저장되어 있어요. 엽서는 지금 만들어도, 나중에 만들어도 돼요.';
    const make = $q('#make-postcard'); make.disabled = true; make.textContent = '엽서 만들기';
    if (!dlg.open) dlg.showModal();
    const until = Date.now() + CONFIG.interview.recordWaitMs;
    for (;;) {
      let rec;
      try { rec = await api.record(id); }
      catch (e) {
        if (my !== rvReq) return;
        $q('#story-review-body').innerHTML = `<p>${e.status === 404 ? '이 이야기의 기록을 찾지 못했어요.' : '지금은 이야기를 불러오지 못했어요. 잠시 뒤 다시 열어 주세요.'}</p>`;
        return;
      }
      if (my !== rvReq) return;
      const got = Math.max(0, ...((rec && rec.fragments) || []).map((f) => f.idx));
      if (got >= (opts.expect || 0) || Date.now() >= until) { paintStory(rec, got < (opts.expect || 0) || opts.why === 'gone'); return; }
      await sleep(CONFIG.interview.recordRetryMs);
      if (my !== rvReq) return;
    }
  }
  function paintStory(rec, stale) {
    const frs = [...((rec && rec.fragments) || [])].sort((a, b) => a.idx - b.idx);
    const said = frs.filter((f) => f.idx > 0 && String(f.answer || '').trim());
    const seed = frs.find((f) => f.idx === 0);
    const title = String((rec && rec.title) || (seed && seed.answer) || '').trim();
    if (title) $q('#story-review-title').textContent = title;
    const pc = rec && rec.postcard;
    rvHasCard = !!(pc && ((pc.title || '').trim() || (pc.text || '').trim()));
    const make = $q('#make-postcard');
    make.textContent = rvHasCard ? '엽서 보기' : '엽서 만들기';
    make.disabled = !said.length && !rvHasCard;
    const body = $q('#story-review-body');
    if (!said.length) {
      body.innerHTML = '<p>남겨진 말씀이 없어요. 다음에는 조금 더 들려주세요.</p>';
      return;
    }
    body.innerHTML = '<ol class="srv-rv-list"></ol>';
    const list = body.querySelector('ol');
    said.forEach((f) => {
      const li = document.createElement('li');
      const q = document.createElement('p'); q.className = 'srv-rv-q'; q.textContent = f.question || '(질문 없이 이어진 말씀)';
      const a = document.createElement('p'); a.className = 'srv-rv-a'; a.textContent = f.answer;
      li.append(q, a); list.append(li);
    });
    if (stale) $q('#story-review-note').textContent = '마지막 답변이 아직 저장되지 않았을 수 있어요. 잠시 뒤 다시 열어 주세요.';
  }

  // ── 엽서 굽기 (v0.54 그대로) ──
  const str = (v) => (typeof v === 'string' ? v.trim() : '');
  const shapeCard = (r) => { if (!r) return null; const body = str(r.text), title = str(r.title); return (body || title) ? {title, body} : null; };
  async function recordCard(id) { try { const rec = await api.record(id); return shapeCard(rec && rec.postcard); } catch (_) { return undefined; } }
  const CARD_LACK = new Set(['insufficient_material', 'no_answers']);
  const cardWaiting = (e) => e.code === 'busy' || (!e.code && e.status === 409 && /기다|만드는 중|굽는 중/.test(String(e.message || '')));
  const cardFail = (e) => ({fail: (CARD_LACK.has(e.code) || (!e.code && e.status === 409 && !cardWaiting(e))) ? 'lack' : 'error',
    status: e.status || 0, code: e.code || '', why: String(e.message || '')});
  async function serverCard(id) {
    const already = await recordCard(id);
    if (already) return already;
    try {
      const made = shapeCard(await api.card(id));
      if (made) return made;
      return {fail: 'error', status: 200, why: '빈 엽서'};
    } catch (e) {
      if (!cardWaiting(e)) return cardFail(e);
    }
    const deadline = Date.now() + CONFIG.card.waitMs;
    let nextRetry = Date.now() + CONFIG.card.retryMs;
    while (Date.now() < deadline) {
      await sleep(CONFIG.card.pollMs);
      const got = await recordCard(id);
      if (got) return got;
      if (got === undefined) return {fail: 'error', status: 0, why: '기록을 읽지 못했습니다'};
      if (Date.now() < nextRetry) continue;
      nextRetry = Date.now() + CONFIG.card.retryMs;
      try { const made = shapeCard(await api.card(id)); if (made) return made; }
      catch (e) { if (!cardWaiting(e)) return cardFail(e); }
    }
    return {fail: 'error', status: 0, why: 'timeout'};
  }
  async function makePostcard() {
    if (rvBusy || !rvId) return;
    const id = rvId, my = rvReq, btn = $q('#make-postcard'), note = $q('#story-review-note');
    rvBusy = true; btn.disabled = true;
    if (!rvHasCard) { btn.textContent = '엽서를 만드는 중…'; note.textContent = '들려주신 이야기를 엽서 글로 짓고 있어요. 조금만 기다려 주세요.'; }
    let got;
    try { got = await serverCard(id); } finally { rvBusy = false; }
    if (my !== rvReq) return;
    btn.disabled = false;
    if (got.fail) {
      btn.textContent = '엽서 만들기';
      note.textContent = got.code === 'photo_unavailable' ? '사진을 불러오지 못했어요. 다시 만들어 주세요.'
        : got.fail === 'lack' ? '엽서에 담을 만큼 분명한 이야기가 모이지 않았어요. 나눈 이야기는 그대로 있어요.'
        : got.code === 'not_closed' ? '인터뷰를 정리하는 중이에요. 잠시 뒤 다시 눌러 주세요.'
        : got.why === 'timeout' ? '정해진 시간 안에 엽서를 받지 못했어요. 잠시 뒤 다시 눌러 주세요.'
        : '엽서를 만들지 못했어요. 잠시 뒤 다시 눌러 주세요.';
      return;
    }
    dlg.close();
    await window.SrvRecords?.reload();
    const rec = window.SrvRecords?.bySession(id);
    if (rec) {
      rec.body = got.body; rec.title = got.title || rec.title;
      rec.description = got.body.replace(/\s+/g, ' ').slice(0, 68);
      renderRecords(); renderRecent();
      if (!rvHasCard) toast('엽서를 만들어 보드에 붙였어요.');
      openPostcard(rec.id);
    } else toast('엽서를 만들었어요. 엽서보기에서 볼 수 있어요.');
  }

  /* ── 시안 버튼에 엔진을 잇는다 (시안의 예시 동작은 떼어 낸다) ── */
  function rebind(sel) { const el = $q(sel); const fresh = el.cloneNode(true); el.replaceWith(fresh); return fresh; }
  rebind('#pause-interview').addEventListener('click', () => {
    if (!live() || !snap) return;
    if (snap.state === 'SPEAKING' && ttsFailed) {
      speaker.stop();
      api.ttsDone(sessionId).then(applySnapshot).catch(() => {});
      return;
    }
    if (held) { setHold(false); return; }
    if (snap.state === 'LISTENING') setHold(true);
  });
  rebind('#toggle-answer').addEventListener('click', () => { if (inputMode === 'voice') void toKeyboard(); else toVoice(); });
  rebind('#answer-panel').addEventListener('submit', (e) => { e.preventDefault(); void sendText(); });
  $q('#answer-text').addEventListener('input', () => { if (snap && inputMode !== 'voice') render(); });
  rebind('#confirm-finish').addEventListener('click', () => { if (live()) void stop(); else { $q('#finish-dialog').close(); navigate('records'); } });
  rebind('#make-postcard').addEventListener('click', () => {
    if (rvHasCard && !rvBusy) { dlg.close(); const rec = window.SrvRecords?.bySession(rvId); if (rec) openPostcard(rec.id); return; }
    void makePostcard();
  });
  dlg.addEventListener('close', () => { rvReq++; });

  // 「엽서로 만들기 전의 이야기」에서 연다 (data-review-story = session_id)
  window.openStoryReview = (sid) => { const p = window.SrvRecords?.pending?.().find((x) => x.session_id === sid); void openStory(sid, {topic: p ? p.title : ''}); };

  // 인터뷰 화면으로 돌아오면 지금 상태로 다시 그린다 (시안의 show() 가 예시 상태로 되돌리므로)
  window.addEventListener('memoir:screen', (e) => { if (e.detail.screen === 'interview' && live()) render(); });
  /* ── 마치기 없이 다른 화면으로 가려 하면 — 인터뷰를 중단할지 여쭙는다 ──
       · 「중단하기」: 저장하지 않고 끝낸다 — 회차를 닫고(abort) 목록에서도 지운다(DELETE /api/sessions/{id}).
         어르신 링크 회차는 자녀의 것이라 지우지 않고 닫기만 한다.
       · 「계속하기」: 인터뷰 화면에 그대로 머문다.
       · 메뉴 · 버튼 클릭은 미리 막고, 브라우저 「뒤로」 같은 주소 변경은 인터뷰 주소로 되돌린 뒤 여쭙는다. */
  let leaving = false, asking = false;
  async function discard() {
    const id = sessionId;
    closing = true; stopping = true;
    held = false; clearInterval(holdTimer);
    stopPolling();
    if (levelRaf) cancelAnimationFrame(levelRaf);
    window.RadioFeedback?.setLevel?.(0);
    speaker.stop();
    if (recorder) { recorder.stop(); recorder = null; }
    $q('#answer-text').value = ''; state.answers = [];
    if (id && !LINK.on) liveForget(id);
    setInterviewMode('idle');
    if (!LINK.on) window.RolePreview?.complete?.({id: id || 'none', body: ''});
    try { await api.abort(id); } catch (_) { /* 이미 닫혔으면 넘어간다 */ }
    if (!LINK.on && id) { try { await window.Srv.call(`/sessions/${encodeURIComponent(id)}`, {method: 'DELETE'}); } catch (_) {} window.SrvRecords?.reload(); }
  }
  async function confirmLeave(target) {
    if (asking) return;
    asking = true;
    const yes = await window.MemoirTrash.confirm({
      title: '인터뷰를 중단할까요?',
      desc: draft() ? '「마치기」를 누르지 않고 나가면 지금까지 나눈 이야기와 쓰던 글이 저장되지 않아요.' : '「마치기」를 누르지 않고 나가면 지금까지 나눈 이야기가 저장되지 않아요.',
      ok: '저장하지 않고 중단하기', keep: '계속 이야기하기'});
    asking = false;
    if (!yes) return;
    await discard();
    leaving = true;
    if (LINK.on) { window.SrvLinks?.left?.(); leaving = false; return; }
    if (location.hash.slice(1) === target) show(target); else location.hash = target;
    leaving = false;
    toast('인터뷰를 저장하지 않고 중단했어요.');
  }
  const onInterview = () => location.hash === '#interview' || (!location.hash && LINK.on);
  document.addEventListener('click', (e) => {
    if (!live() || leaving) return;
    const link = e.target.closest('[data-nav],[data-go],a[href^="#"]');
    if (!link || link.closest('dialog')) return;
    const target = link.dataset.nav || link.dataset.go || (link.getAttribute('href') || '').slice(1) || 'home';
    if (target === 'interview' || !onInterview()) return;
    e.preventDefault(); e.stopImmediatePropagation();
    void confirmLeave(target);
  }, true);
  window.addEventListener('hashchange', (e) => {
    if (!live() || leaving) return;
    const from = new URL(e.oldURL).hash.slice(1), to = location.hash.slice(1) || 'home';
    if (from !== 'interview' || to === 'interview') return;
    e.stopImmediatePropagation();
    history.replaceState(null, '', '#interview');
    // 다른 화면이 먼저 그려졌을 수 있다 (브라우저마다 듣는 순서가 다르다) — 인터뷰 화면으로 되돌린 뒤 여쭙는다
    setTimeout(() => { if (live() && !leaving) show('interview'); void confirmLeave(to); }, 0);
  }, true);

  // 진행 중에 창을 닫으려 하면 한 번 여쭙는다
  window.addEventListener('beforeunload', (e) => { if (live()) { e.preventDefault(); e.returnValue = ''; } });
  // 남은 회차 닫기 · 기억은 자녀 화면에서만 (어르신 링크 회차는 다른 곳에서 말씀하고 계실 수 있다)
  if (LINK.on) { liveKeep = () => {}; }

  window.SrvInterview = {start, busy: () => live() || starting, stop, openStory};
}());
