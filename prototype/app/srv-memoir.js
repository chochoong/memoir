(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     srv-memoir — 자서전 만들기 · 책장 (시안 화면 + 서버)
       · 만들기: POST /api/memoirs {session_ids, style} → 202 {job_id}
                 → GET /api/memoirs/{job_id} 를 몇 초마다 (running · done · failed)
                 409 busy 면 이미 만드는 작업(job_id)을 이어서 기다린다.
                 작업 번호는 이 브라우저에 기억한다 — 새로고침해도 이어서 기다린다 (v0.54 와 같다).
       · 다 만든 자서전은 서버가 저절로 보관한다 (memoir_id). 「작은 책으로 보관하기」는 책장에 꽂는 연출만 한다.
       · 책장: GET /api/memoirs/saved?elder_id= (본문 없음) → 펼칠 때 GET /api/memoirs/saved/{id}
       · 지우기: DELETE /api/memoirs/saved/{id} — 「되돌리기」 시간이 지난 뒤에 보낸다.
       · 글 고치기: 서버에 고친 글을 받는 API 가 아직 없다. 고친 글은 이 기기(localStorage)에만 두고,
         책을 펼칠 때 · PDF · 공유에 그 글을 쓴다.
     ═══════════════════════════════════════════════════════════════ */
  const {api, AUTH, CONFIG, ApiError} = window.Srv;
  const contract = window.MemoirServiceContract;

  /* ── 문체: 시안의 네 가지를 서버가 받는 네 가지로 ── */
  const SERVER_STYLES = [
    {id: 'spoken', title: '담백한 기록', description: '내 말투에 가까운, 솔직하고 편안한 글 · 구어체', icon: 'pen',
      sample: '우리 동네에는 커다란 느티나무가 있었어요. 학교가 끝나면 친구들하고 그 아래 모였지요. 해가 기울고 집집마다 저녁 짓는 냄새가 날 때까지, 시간 가는 줄을 몰랐어요.'},
    {id: 'essay', title: '다정한 에세이', description: '그때의 마음을 천천히 돌아보는 글 · 수필체', icon: 'leaf',
      sample: '이상하게도 어린 날의 기억에는 늘 나무 그늘이 있다. 그 아래서 보낸 오후들은 아주 평범했는데, 오래 지나 돌아보니 가장 넉넉했던 시간이었다. 내 마음은 아직도 가끔 그 그늘에서 쉰다.'},
    {id: 'literary', title: '문학적인 글', description: '장면과 마음을 결 고운 문장으로 · 문학체', icon: 'book',
      sample: '느티나무 그늘은 오후마다 조금씩 자리를 옮겨 앉았다. 아이들의 웃음은 그늘을 따라 흘렀고, 골목 끝으로 저녁 빛이 번질 무렵에야 하나둘 제 이름을 부르는 목소리 쪽으로 흩어졌다.'},
    {id: 'novel', title: '이야기 소설', description: '한 장면씩 생생하게 펼쳐지는 글 · 소설체', icon: 'spark',
      sample: '“조금만 더 놀다 가자!” 누군가 소리치자 아이들이 다시 느티나무 아래로 모여들었다. 골목 끝으로 노을이 번지고 있었다. 멀리서 저녁을 먹으라는 목소리가 들려왔다.'},
  ].filter((s) => s.id !== 'spoken' && (CONFIG.style.memoirOpen || []).includes(s.id));   // 자서전은 구어체를 고르지 않는다 (요청 11-12)
  styles.splice(0, styles.length, ...SERVER_STYLES);
  state.style = styles[0] ? styles[0].id : 'essay';
  // 예전 책(구어체 · 시안 문체)을 펼쳤다가 돌아와도 문체 이름이 깨지지 않게 — 고를 수 없는 문체는 이름만 보여 준다
  window.selectedStyle = () => styles.find((s) => s.id === state.style)
    || {id: state.style, title: CONFIG.style.names[state.style] || '구어체', description: '', icon: 'pen', sample: styles[0] ? styles[0].sample : ''};
  window.addEventListener('memoir:before-screen', (e) => { if (e.detail.screen === 'style' && !styles.some((s) => s.id === state.style) && styles[0]) state.style = styles[0].id; });
  const styleTitle = (id) => (styles.find((s) => s.id === id) || styles[0]).title;

  /* ── 고친 글 (이 기기에만) ── */
  const EDIT_KEY = (id) => `memoir.edit.${id}`;
  const readEdit = (id) => { try { return JSON.parse(localStorage.getItem(EDIT_KEY(id)) || 'null'); } catch (_) { return null; } };
  const writeEdit = (id, v) => { try { if (v) localStorage.setItem(EDIT_KEY(id), JSON.stringify(v)); else localStorage.removeItem(EDIT_KEY(id)); } catch (_) {} };

  /* ═══ 만들기 ═══ */
  const JOB_KEY = 'memoir.job';
  const who = () => String((AUTH.user && AUTH.user.user_id) || '');
  const jobKeep = (v) => { try { if (v) localStorage.setItem(JOB_KEY, JSON.stringify({...v, who: who()})); else localStorage.removeItem(JOB_KEY); } catch (_) {} };
  const jobLeft = () => { try { const v = JSON.parse(localStorage.getItem(JOB_KEY) || 'null'); return v && v.who === who() ? v : null; } catch (_) { return null; } };
  const STAGE = {analysis: '이야기를 정리하고 있어요', outline: '목차를 짜고 있어요', edit: '글을 다듬고 있어요', verify: '마지막으로 확인하고 있어요', write: '글을 쓰고 있어요'};
  const SAYS = {
    mixed_speakers: '한 분의 이야기만 골라 주세요. 서로 다른 분의 이야기는 한 자서전에 넣을 수 없어요.',
    speaker_unassigned: '누구의 이야기인지 정하지 않은 기록이 섞여 있어요.',
    too_much: '이야기가 너무 많아 한 번에 만들 수 없어요. 넣지 않을 엽서를 몇 장 빼 주세요.',
    job_not_found: '만들던 자서전을 찾을 수 없어요. 다시 만들어 주세요.',
    unsupported_style: '지금은 이 문체로 만들 수 없어요. 다른 문체를 골라 주세요.',
    insufficient_material: '자서전에 담을 만큼 분명한 이야기가 모이지 않았어요. 엽서를 더 골라 주세요.',
    cancelled: '자서전 만들기를 그만두었어요.',
  };
  const FAIL = {400: '고른 엽서를 확인해 주세요. 말씀이 없는 기록은 넣을 수 없어요.', 404: '고른 엽서를 찾을 수 없어요. 다시 골라 주세요.',
    422: '고른 이야기의 자료를 불러오지 못했어요.', 503: '지금은 자서전을 만들 수 없어요. 잠시 뒤 다시 해 주세요.',
    504: '정해진 시간 안에 자서전을 받지 못했어요. 다시 해 주세요.', other: '자서전을 만드는 중 문제가 생겼어요. 다시 해 주세요.'};
  const CODE = {bad_selection: 400, not_found: 404, source_unavailable: 422, invalid_model_output: 'other', not_final: 503, needs_confirmation: 503, needs_context: 503, generation_timeout: 504, incomplete: 503};
  const why = (e) => SAYS[e && e.code] || FAIL[CODE[e && e.code]] || FAIL[e && e.status] || FAIL.other;

  const dialog = document.getElementById('generation-dialog');
  dialog.querySelector('p').id = 'generation-stage';
  dialog.insertAdjacentHTML('beforeend', `<p class="small-copy srv-gen-note">몇 분 걸릴 수 있어요. 이 창을 닫거나 다른 화면으로 가도 서버는 계속 만들어요. 다 만든 자서전은 「자서전 보기」 책장에 저장돼요.</p>
    <div class="dialog-actions srv-gen-actions"><button type="button" class="button outline" data-gen="stop">그만두기</button><button type="button" class="button primary" data-gen="hide">닫고 기다리기</button></div>`);
  let job = null;          // {job_id, elderId, style, title}
  let seq = 0, stagePast = false;

  /* ── 「자서전 만드는 중」 알림 — 창을 닫고 기다리는 동안 화면에 늘 떠 있다 (휴대폰은 위, PC 는 오른쪽 아래). 누르면 진행 창을 다시 연다 ── */
  const pill = document.createElement('button');
  pill.type = 'button'; pill.className = 'srv-gen-pill'; pill.hidden = true;
  pill.setAttribute('aria-label', '자서전 만드는 중 — 진행 상황 보기');
  pill.innerHTML = `<span class="sgp-spin" aria-hidden="true"></span><span class="sgp-text"><b>자서전 만드는 중</b><small class="sgp-stage">시작하고 있어요</small></span>`;
  document.body.append(pill);
  let lastStage = '시작하고 있어요';
  function paintPill() {
    const on = !!(job && state.generating) && !dialog.open && !document.body.classList.contains('ebook-mode') && location.hash !== '#interview' && location.hash !== '#library'; // 인터뷰 중에는 말씀에 집중하게, 책장은 「만드는 중」 책이 대신 보여 준다
    pill.hidden = !on;
    if (on) pill.querySelector('.sgp-stage').textContent = lastStage;
    paintShelf();
  }
  pill.addEventListener('click', () => { if (job && state.generating && !dialog.open) dialog.showModal(); paintPill(); });
  dialog.addEventListener('close', () => { busyNote.hidden = true; paintPill(); });
  window.addEventListener('memoir:screen', paintPill);

  /* ── 만드는 동안은 새 자서전을 시작하지 않는다 — 한 번에 한 권 (서버도 409 busy 로 막는다) ──
       「자서전 만들기」 · 「자서전 만들기(문체 화면)」를 누르면 막는다는 말과 함께 지금 만드는 책의 진행 창을 연다. */
  const busyNote = document.createElement('p');
  busyNote.className = 'srv-gen-busy'; busyNote.hidden = true; busyNote.setAttribute('role', 'alert');
  busyNote.innerHTML = '<b>지금 만들고 있는 자서전이 있어요.</b><br>한 번에 한 권씩 만들어요. 이 책이 다 만들어진 뒤에 새로 만들 수 있어요.';
  dialog.querySelector('#generation-stage').before(busyNote);
  const running = () => !!(job && state.generating);
  function showBusy() { busyNote.hidden = false; if (!dialog.open) dialog.showModal(); paintPill(); }
  document.addEventListener('click', (e) => {
    if (!running() || !e.target.closest('#choose-style')) return;
    e.preventDefault(); e.stopImmediatePropagation(); showBusy();
  }, true);

  /* ── 책장에 「만드는 중」인 책 한 권 — 반짝이며 기다린다. 누르면 진행 창 ── */
  const shelfScreen = document.querySelector('[data-screen="library"]');
  function paintShelf() {
    if (!shelfScreen) return;
    const want = running() && job.elderId === AUTH.elderId;
    let li = shelfScreen.querySelector('.ml-making-item');
    if (!want) { if (li) { const row = li.closest('.ml-shelf-row.ml-making-row'); (row || li).remove(); } return; }
    const shelves = shelfScreen.querySelector('.ml-shelves');
    if (!shelves) return;
    if (!li) {
      li = document.createElement('li'); li.className = 'ml-making-item';
      li.innerHTML = `<button type="button" class="ml-book-card ml-making" data-gen-open aria-label="만들고 있는 자서전 — 진행 상황 보기">
        <span class="ml-cover-bay" aria-hidden="true"><span class="ml-cover ml-cover-making"><span class="ml-cover-title">새 책을<br>엮는 중</span><span class="ml-cover-rule"></span><span class="mlm-spark s1">✦</span><span class="mlm-spark s2">✧</span><span class="mlm-spark s3">✦</span><span class="mlm-spark s4">✧</span><span class="mlm-shine"></span></span></span>
        <span class="ml-book-copy"><span class="ml-volume-label">만드는 중</span><strong>${escapeText(job.title || '새 자서전')}</strong><span class="ml-book-meta mlm-stage"></span><span class="ml-read-label">진행 보기 <span aria-hidden="true">→</span></span></span></button>`;
      const firstRow = shelves.querySelector('.ml-books');
      if (firstRow) firstRow.prepend(li);
      else { const row = document.createElement('div'); row.className = 'ml-shelf-row ml-making-row'; row.innerHTML = '<ul class="ml-books" aria-label="만들고 있는 책"></ul><span class="ml-shelf-plank" aria-hidden="true"></span>'; row.firstChild.append(li); shelves.prepend(row); }
    }
    li.querySelector('.mlm-stage').textContent = lastStage;
  }
  if (shelfScreen) new MutationObserver(() => { if (running() && !shelfScreen.querySelector('.ml-making-item')) paintShelf(); }).observe(shelfScreen, {childList: true, subtree: true});
  document.addEventListener('click', (e) => { if (e.target.closest('[data-gen-open]')) { e.preventDefault(); if (running() && !dialog.open) dialog.showModal(); paintPill(); } });

  function paintStage(j) {
    if (j.stage && j.stage !== 'analysis') stagePast = true;
    const st = j.stage === 'chapter' && j.chapters ? `${j.chapters}장 중 ${j.chapter}장을 쓰고 있어요`
      : j.stage === 'analysis' && stagePast ? '이야기를 다시 정리하고 있어요'
      : STAGE[j.stage] || '자서전을 만들고 있어요';
    const sec = Number(j.elapsed) || 0;
    const ago = sec >= 60 ? `${Math.floor(sec / 60)}분 ${sec % 60}초` : `${sec}초`;
    dialog.querySelector('#generation-stage').textContent = `${st} · ${ago} 지났어요`;
    lastStage = `${st} · ${ago}`;
    paintPill();
  }

  async function generate() {
    if (state.generating) return;
    const chosen = recordData.filter((r) => state.selected.has(r.id));
    if (!memoirSelection.canGenerate(chosen.length, MEMOIR_POLICY)) { navigate('records'); toast(`엽서를 ${selectionRangeText()} 골라주세요.`); return; }
    // 서버는 회차가 만들어진 순서로 엮는다. 화면도 같은 순서로 보낸다
    const ids = chosen.sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at)).map((r) => r.session_id);
    const style = styles.some((s) => s.id === state.style) ? state.style : (styles[0] ? styles[0].id : 'essay');
    state.generating = true;
    stagePast = false;
    dialog.querySelector('#generation-stage').textContent = '자서전 만들기를 시작하고 있어요…';
    if (!dialog.open) dialog.showModal();
    let first;
    try {
      first = await api.memoirStart({ids}, style);
    } catch (e) {
      if (e.status === 409 && e.code === 'busy' && e.body && e.body.job_id) {
        first = {job_id: e.body.job_id, status: 'running'};
        busyNote.hidden = false; // 다른 기기 · 창에서 시작한 책 — 서버가 409 busy 로 알려 준다
      } else {
        state.generating = false; dialog.close();
        toast(why(e));
        return;
      }
    }
    job = {job_id: first.job_id, elderId: AUTH.elderId, style, title: state.pendingMemoirTitle || ''};
    jobKeep(job);
    void wait(job, true);
  }

  async function wait(j, visible) {
    const my = ++seq;
    const t0 = Date.now();
    let misses = 0;
    state.generating = true;
    lastStage = '이어서 기다리고 있어요';
    paintPill();
    for (;;) {
      if (my !== seq) return;
      let r;
      try { r = await api.memoirJob(j.job_id); misses = 0; }
      catch (e) {
        if (my !== seq) return;
        // 작업은 서버 메모리에 30분만 남는다. 다 만든 책은 DB 에 저장되므로 오래 지나 돌아왔으면 책장을 본다
        if (e.status === 404) { finish(); void reloadLibrary(); toast(visible ? SAYS.job_not_found : '만들던 자서전은 「자서전 보기」 책장에서 확인해 주세요.'); return; }
        if (++misses >= 5) { finish(); toast('자서전 소식을 받지 못하고 있어요. 잠시 뒤 다시 열어 주세요.'); return; }
        await sleepMs(CONFIG.memoir.pollMs); continue;
      }
      if (my !== seq) return;
      if (r.status === 'running') {
        paintStage(r);
        if (Date.now() - t0 > CONFIG.memoir.jobMaxMs) { finish(); toast(FAIL[504]); return; }
        await sleepMs(CONFIG.memoir.pollMs); continue;
      }
      if (r.status === 'failed') { finish(); toast(why(r)); return; }
      // done
      let view;
      try { view = contract.jobView(r, {elder_id: j.elderId, uiStyle: j.style}); } catch (_) { view = null; }
      if (!view || !view.canRead) {
        finish();
        const st = r.result && r.result.status;
        toast(SAYS[st] || (st === 'partial' || st === 'incomplete' ? '자서전 몇 장을 만들지 못했어요. 다시 해 주세요.' : FAIL.other));
        return;
      }
      finish();
      state.document = view.document; state.title = view.document.title; state.body = [...view.document.body];
      state.style = styles.some((s) => s.id === r.style) ? r.style : j.style;
      state.draftElderId = j.elderId; state.spread = 0; state.pendingMemoirTitle = null;
      state.savedMemoirId = r.memoir_id || (r.result && r.result.memoir_id) || null;
      state.draftKept = !(['#style', '#records', '#draft'].includes(location.hash) && !window.SrvInterview?.busy());
      state.selected.clear(); state.pickRecords = false;
      // 자서전을 고르던 화면에 있을 때만 초안으로 옮긴다 — 인터뷰 · 다른 화면을 보고 있으면 알리기만 한다
      const here = ['#style', '#records', '#draft'].includes(location.hash) && !window.SrvInterview?.busy();
      if (AUTH.elderId === j.elderId && here) { navigate('draft'); toast('자서전 초안이 나왔어요. 읽어 보고 책으로 보관해 주세요.'); }
      else if (AUTH.elderId === j.elderId) toast('자서전이 다 만들어졌어요. 「자서전 보기」 책장에서 펼쳐 보세요.');
      else toast('다른 이야기 주인공의 자서전이 다 만들어졌어요. 그분을 고르면 책장에서 볼 수 있어요.');
      void reloadLibrary();
      return;
    }
  }
  function finish() { state.generating = false; job = null; jobKeep(null); if (dialog.open) dialog.close(); paintPill(); }
  const sleepMs = (ms) => new Promise((r) => setTimeout(r, ms));

  dialog.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-gen]');
    if (!b) return;
    if (b.dataset.gen === 'hide') { dialog.close(); toast('다 만들어지면 알려 드릴게요. 「자서전 만드는 중」 알림을 누르면 진행 상황을 볼 수 있어요.'); return; }
    if (b.dataset.gen === 'stop' && job) {
      if (!window.confirm('자서전 만들기를 그만둘까요?')) return;
      const id = job.job_id;
      seq++; finish();
      try { await api.memoirCancel(id); } catch (_) {}
      toast(SAYS.cancelled);
    }
  });
  // 만드는 동안 다시 「초안 미리보기」를 누르면 창만 다시 연다
  const gen = document.getElementById('generate-draft');
  const fresh = gen.cloneNode(true); gen.replaceWith(fresh);
  fresh.innerHTML = fresh.innerHTML.replace('초안 미리보기', '자서전 만들기');
  fresh.addEventListener('click', () => { if (running()) { showBusy(); return; } void generate(); });

  /* ── 자서전에 넣을 엽서 고르기: 처음엔 전체 선택 · 「전체 해제 / 전체 선택」 버튼 ── */
  const allBtn = document.createElement('button');
  allBtn.type = 'button'; allBtn.id = 'toggle-all-postcards'; allBtn.className = 'button outline compact srv-pick-all'; allBtn.hidden = true;
  document.getElementById('choose-style').before(allBtn);
  const pickable = () => currentRecords().map((r) => r.id);
  const allPicked = () => { const ids = pickable(); return ids.length > 0 && ids.every((id) => state.selected.has(id)); };
  function selectAll(on) {
    const ids = pickable();
    const max = MEMOIR_POLICY.max == null ? Infinity : MEMOIR_POLICY.max;
    state.selected.clear();
    if (on) ids.slice(0, max).forEach((id) => state.selected.add(id));
  }
  const updateOriginal = window.updateSelection;
  window.updateSelection = function () {
    updateOriginal();
    allBtn.hidden = !state.pickRecords || !pickable().length;
    allBtn.textContent = allPicked() ? '전체 해제' : '전체 선택';
  };
  allBtn.addEventListener('click', () => { selectAll(!allPicked()); renderRecords(); });
  const startOriginal = window.startMemoirFromPostcards;
  window.startMemoirFromPostcards = function () { if (running()) { showBusy(); return; } startOriginal(); selectAll(true); renderRecords(); };
  // 고르는 중에 엽서 목록이 늦게 도착하면 (로그인 · 화자 바꿈 직후) 그때 전체 선택
  window.addEventListener('memoir:records', () => { if (state.pickRecords && !state.selected.size) { selectAll(true); renderRecords(); } });

  /* ═══ 책장 ═══ */
  const fmtDate = (iso) => { const d = new Date(iso); return isNaN(d) ? '' : `${d.getFullYear()}. ${d.getMonth() + 1}. ${d.getDate()}.`; };
  let libSeq = 0;
  async function reloadLibrary() {
    const lib = window.MemoirLibrary;
    const my = ++libSeq;
    if (!AUTH.user || !AUTH.elderId) { lib.setBooks([]); return; }
    try {
      const r = await window.Srv.call(`/memoirs/saved?elder_id=${encodeURIComponent(AUTH.elderId)}&limit=50`);
      if (my !== libSeq) return;
      const hide = location.hash === '#draft' || location.hash === '#reader' ? (state.draftKept ? null : state.savedMemoirId) : null;
      const rows = ((r && r.memoirs) || []).filter((m) => m.memoir_id !== hide && (!m.status || m.status === 'ready'));
      // 오래된 책이 01 — 서버는 최근 순으로 준다
      lib.setBooks(rows.reverse().map((m) => {
        const old = lib.getBook(m.memoir_id), edit = readEdit(m.memoir_id);
        return old && old.document ? old : {
          id: m.memoir_id, elder_id: m.elder_id || AUTH.elderId, title: (edit && edit.title) || m.title || '제목 없는 자서전',
          date: fmtDate(m.created_at), style: m.style || 'spoken', count: (m.session_ids || []).length, body: [], document: null, server: true,
        };
      }));
    } catch (e) {
      if (my !== libSeq) return;
      if (e.status !== 401 && location.hash === '#library') toast('책장을 불러오지 못했어요. 잠시 뒤 다시 열어 주세요.');
    }
  }
  /** 책 한 권의 본문을 받아 둔다 (펼치기 · PDF · 공유 전에) */
  async function ensure(id) {
    const book = window.MemoirLibrary.getBook(id);
    if (!book) return null;
    if (book.document) return book;
    if (book._loading) return book._loading;
    book._loading = (async () => {
      try {
        const r = await window.Srv.call(`/memoirs/saved/${encodeURIComponent(id)}`);
        let doc = contract.memoirView(r.result, {elder_id: book.elder_id, uiStyle: book.style});
        const edit = readEdit(id);
        if (edit) doc = contract.editMemoir(doc, {title: edit.title, body: edit.body});
        book.document = doc; book.title = doc.title; book.body = [...doc.body];
        return book;
      } catch (e) {
        toast(e.status === 404 ? '이 책을 찾을 수 없어요. 책장을 다시 불러올게요.' : '책을 펼치지 못했어요. 잠시 뒤 다시 눌러 주세요.');
        if (e.status === 404) void reloadLibrary();
        return null;
      } finally { delete book._loading; }
    })();
    return book._loading;
  }
  /** 서버에서 지운다 (되돌리기 시간이 지난 뒤). 실패한 책은 돌려준다 */
  async function removeSaved(books) {
    const failed = [];
    for (const b of books) {
      try { await window.Srv.call(`/memoirs/saved/${encodeURIComponent(b.id)}`, {method: 'DELETE'}); writeEdit(b.id, null); }
      catch (e) { if (e.status !== 404) failed.push(b); else writeEdit(b.id, null); }
    }
    return failed;
  }

  // 초안에서 고친 글 — 이 기기에 남긴다
  document.getElementById('draft-editor').addEventListener('submit', () => {
    setTimeout(() => { if (state.savedMemoirId && state.document && state.document.edited) writeEdit(state.savedMemoirId, {title: state.title, body: state.body}); }, 0);
  });

  /* ── 새로고침해도 만들던 자서전을 이어서 기다린다 ── */
  window.addEventListener('memoir:preview-auth', (e) => {
    if (!e.detail.authenticated) return;
    const left = jobLeft();
    if (left && !job) { job = left; void wait(left, false); }
  });

  window.SrvLibrary = {reload: reloadLibrary, ensure, removeSaved, styleTitle, readEdit, writeEdit};
  void ApiError;
}());
