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
  ].filter((s) => (CONFIG.style.memoirOpen || ['spoken']).includes(s.id));
  styles.splice(0, styles.length, ...SERVER_STYLES);
  state.style = 'spoken';
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
  dialog.insertAdjacentHTML('beforeend', `<p class="small-copy srv-gen-note">몇 분 걸릴 수 있어요. 창을 닫아도 서버는 계속 만들고, 다 되면 알려 드려요.</p>
    <div class="dialog-actions srv-gen-actions"><button type="button" class="button outline" data-gen="stop">그만두기</button><button type="button" class="button primary" data-gen="hide">닫고 기다리기</button></div>`);
  let job = null;          // {job_id, elderId, style, title}
  let seq = 0, stagePast = false;

  function paintStage(j) {
    if (j.stage && j.stage !== 'analysis') stagePast = true;
    const st = j.stage === 'chapter' && j.chapters ? `${j.chapters}장 중 ${j.chapter}장을 쓰고 있어요`
      : j.stage === 'analysis' && stagePast ? '이야기를 다시 정리하고 있어요'
      : STAGE[j.stage] || '자서전을 만들고 있어요';
    const sec = Number(j.elapsed) || 0;
    dialog.querySelector('#generation-stage').textContent = `${st} · ${sec >= 60 ? `${Math.floor(sec / 60)}분 ${sec % 60}초` : `${sec}초`} 지났어요`;
  }

  async function generate() {
    if (state.generating) return;
    const chosen = recordData.filter((r) => state.selected.has(r.id));
    if (!memoirSelection.canGenerate(chosen.length, MEMOIR_POLICY)) { navigate('records'); toast(`엽서를 ${selectionRangeText()} 골라주세요.`); return; }
    // 서버는 회차가 만들어진 순서로 엮는다. 화면도 같은 순서로 보낸다
    const ids = chosen.sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at)).map((r) => r.session_id);
    const style = styles.some((s) => s.id === state.style) ? state.style : 'spoken';
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
        toast('이미 만들고 있는 자서전이 있어요. 그 자서전을 이어서 기다려요.');
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
    for (;;) {
      if (my !== seq) return;
      let r;
      try { r = await api.memoirJob(j.job_id); misses = 0; }
      catch (e) {
        if (my !== seq) return;
        if (e.status === 404) { finish(); toast(SAYS.job_not_found); return; }
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
      state.draftKept = false;
      state.selected.clear(); state.pickRecords = false;
      if (AUTH.elderId === j.elderId) { navigate('draft'); toast('자서전 초안이 나왔어요. 읽어 보고 책으로 보관해 주세요.'); }
      else toast('다른 이야기 주인공의 자서전이 다 만들어졌어요. 그분을 고르면 책장에서 볼 수 있어요.');
      void reloadLibrary();
      return;
    }
  }
  function finish() { state.generating = false; job = null; jobKeep(null); if (dialog.open) dialog.close(); }
  const sleepMs = (ms) => new Promise((r) => setTimeout(r, ms));

  dialog.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-gen]');
    if (!b) return;
    if (b.dataset.gen === 'hide') { dialog.close(); toast('다 만들어지면 알려 드릴게요. 다른 화면을 둘러보셔도 돼요.'); return; }
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
  fresh.addEventListener('click', () => { if (job && state.generating) { if (!dialog.open) dialog.showModal(); return; } void generate(); });

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
