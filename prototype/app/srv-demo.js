(function () {
  'use strict';
  /* ═══════════════════════════════════════════════════════════════
     srv-demo — 서버 없이 화면 전체를 돌려 보는 예시 모드
       · 주소 뒤에 ?demo=1 을 붙여 열 때만 켜진다. 없으면 이 파일은 아무것도 하지 않는다.
       · /api/* 요청을 브라우저 안의 가짜 서버가 받는다 — 실제 서버 · 계정 · AI 는 전혀 부르지 않는다.
       · 예시 데이터는 이 브라우저(localStorage 'memoir.demo.db')에만 남는다. 「처음 상태로」로 지운다.
       · 어르신 링크 화면은 ?demo=elder#<예시 토큰> — 예시 모드에서 만든 초대 주소가 이 모양이다.
       · 녹음: 마이크 소리는 글로 옮기지 않는다. 말씀을 멈추면(3초) 「예시로 받은 말씀」 한 줄이 남는다.
         질문 낭독 소리는 없다(글자로만). 엽서 · 자서전 글은 고른 이야기를 이어 붙인 예시 글이다.
     ═══════════════════════════════════════════════════════════════ */
  const Srv = window.Srv;
  const mode = Srv.QS.get('demo');
  if (!mode) return;
  Srv.DEMO = true;
  const {CONFIG, LINK} = Srv;
  CONFIG.memoir.pollMs = 1200;
  CONFIG.card.pollMs = 600;

  // ── 예시 데이터 ──
  const KEY = 'memoir.demo.db';
  const now = () => new Date().toISOString();
  const ago = (d) => new Date(Date.now() - d * 864e5).toISOString();
  const uid = () => Math.random().toString(16).slice(2, 10) + '-' + Date.now().toString(16).slice(-4) + '-4000-8000-' + Math.random().toString(16).slice(2, 14).padEnd(12, '0');
  const tok = () => 'demo' + Math.random().toString(36).slice(2, 12);
  function seed() {
    const s = (title, topic, d, qa, card) => ({session_id: uid(), title: topic, elder_id: 'demo-e1', state: 'CLOSED', created_at: ago(d),
      fragments: [{idx: 0, question: null, answer: topic}, ...qa.map(([q, a], i) => ({idx: i + 1, question: q, answer: a}))],
      postcard: card ? {title, text: card, style: 'spoken', created_at: ago(d)} : null, deleted: false});
    const sessions = [
      s('느티나무 아래, 우리 동네', '어린 시절', 12, [['어린 시절 살던 동네는 어떤 모습이었나요?', '마을 한가운데 커다란 느티나무가 있었어요. 학교가 끝나면 다들 그 아래 모였지요.']],
        '마을 한가운데 커다란 느티나무가 있었어요. 학교가 끝나면 친구들과 그 아래 모여 해가 질 때까지 놀았지요.\n\n저녁 짓는 냄새가 골목에 퍼지면 그제야 흙을 털고 집으로 달려갔어요.'),
      s('어머니의 따뜻한 밥상', '가족', 9, [['가족과 함께한 기억 중 먼저 떠오르는 것은요?', '어머니가 차려 주시던 밥상이요. 반찬이 없어도 늘 따뜻했어요.']],
        '어머니는 말없이 반찬 한 가지를 더 건네곤 하셨어요. 넉넉하지 않은 살림이었지만 밥상만큼은 늘 따뜻했지요.\n\n지금도 그 반찬을 만들면 그때 부엌 냄새가 떠올라요.'),
      s('처음 내 이름으로 받은 월급', '삶과 일', 6, [['처음 일을 시작하던 날은 어땠나요?', '서툴렀지만 설렜어요. 첫 월급 봉투를 어머니께 드렸지요.']],
        '첫 출근 날은 모든 게 서툴렀어요. 그래도 한 달을 버티고 받은 월급 봉투는 참 묵직했지요.\n\n봉투를 그대로 어머니께 드렸더니 한참을 바라보다 웃으셨어요.'),
      s('우리 가족의 첫 소풍', '가족', 3, [['가족과 함께 간 곳 중 기억나는 곳이 있나요?', '처음 다 같이 소풍을 갔던 날이요. 김밥을 싸 갔어요.']],
        '처음으로 온 가족이 소풍을 간 날, 어머니는 새벽부터 김밥을 싸셨어요.\n\n유난히 맑았던 그날 찍은 사진 한 장이 아직도 앨범에 남아 있어요.'),
      s('', '어린 시절', 1, [['학교 가는 길은 어땠나요?', '모퉁이에서 친구를 만나 함께 걸었어요. 늘 같은 자리에서 기다렸지요.']], null),
    ];
    return {logged: false, user: {user_id: 'demo-u1', name: '예시 사용자', email: 'demo@example.com'},
      elders: [{elder_id: 'demo-e1', name: '어머니'}], sessions, memoirs: [], jobs: {}, shares: [], links: [], seq: 1};
  }
  let db;
  try { db = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (_) { db = null; }
  if (!db || !db.sessions) db = seed();
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(db)); } catch (_) {} };
  save();

  // ── 어르신 링크 예시 (?demo=elder#토큰) ──
  if (mode === 'elder') {
    LINK.on = true;
    const h = location.hash.replace(/^#/, '');
    if (h) { LINK.token = h; try { history.replaceState(null, '', location.pathname + location.search); } catch (_) {} }
  }

  // ── 회차 상태 기계 (서버 controller 흉내) ──
  const QUESTIONS = {
    '어린 시절': ['어린 시절 살던 동네는 어떤 모습이었나요?', '그때 함께 놀던 동무는 누구였나요?', '그 시절의 나에게 해 주고 싶은 말이 있나요?'],
    '가족': ['가족과 함께한 기억 중 먼저 떠오르는 것은요?', '그분과 함께 보낸 어떤 순간이 기억나세요?', '그분에게 지금 어떤 말을 전하고 싶으세요?'],
    '삶과 일': ['처음 일을 시작하던 날은 어땠나요?', '일하면서 가장 마음에 남은 순간은 언제인가요?', '그 시절의 나에게 어떤 말을 건네고 싶으세요?'],
  };
  const live = new Map();   // session_id → {snap, pending, audio, lastAudio}
  function snapOf(L) { return JSON.parse(JSON.stringify(L.snap)); }
  function ask(L) {
    const qs = QUESTIONS[L.topic] || [`「${L.topic}」 하면 어떤 장면이 먼저 떠오르세요?`, '그때 곁에 누가 있었나요?', '그 일을 떠올리면 지금 어떤 마음이 드세요?'];
    const n = L.snap.fragments.filter((f) => f.idx > 0).length;
    L.snap.state = 'SPEAKING'; L.snap.turn = n + 1;
    L.snap.next_question = qs[n % qs.length] + (n >= qs.length ? ' (예시 질문이 다시 돌아요)' : '');
  }
  function commit(L, answer) {
    L.snap.fragments.push({idx: L.snap.fragments.length, question: L.snap.next_question, answer});
    L.snap.audio_bytes = 0; L.audio = 0; L.pending = '';
    L.snap.state = 'PROCESSING';
    setTimeout(() => { if (L.snap.state === 'PROCESSING') ask(L); }, 900);
  }
  function tick(L) {
    // 마이크로 말씀하셨다가 3초 멈추면 — 예시 한 줄로 받는다
    if (L.snap.state !== 'LISTENING' || !L.audio || Date.now() - L.lastAudio <= 3000) return;
    // 짧은 소리(0.6초 미만)는 서버처럼 「빈 말씀」으로 버린다 — 안 그러면 글로 쓰기가 막힌 채로 남는다
    if (L.audio < 16000 * 2 * 0.6) { L.audio = 0; L.snap.audio_bytes = 0; return; }
    commit(L, '(예시 화면) 마이크로 들려주신 말씀이에요. 예시 화면에서는 소리를 글로 옮기지 않아요.');
  }
  function openSession({topic, elder_id, link}) {
    const sid = uid();
    const L = {topic, elder_id, link, audio: 0, lastAudio: 0, pending: '',
      snap: {session_id: sid, state: 'SPEAKING', turn: 1, max_turn: 0, next_question: '', question_audio_stream: false, audio_bytes: 0, resumable: false,
        fragments: [{idx: 0, question: null, answer: topic}]}};
    ask(L);
    live.set(sid, L);
    return L;
  }
  function closeSession(L) {
    if (L.snap.state === 'CLOSED') return;
    L.snap.state = 'CLOSED';
    db.sessions.unshift({session_id: L.snap.session_id, title: L.topic, elder_id: L.elder_id, state: 'CLOSED', created_at: now(),
      fragments: L.snap.fragments, postcard: null, deleted: false});
    if (L.link) { const k = db.links.find((x) => x.link_id === L.link); if (k) k.state = 'ended'; }
    save();
  }

  // ── 가짜 서버 ──
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  class Res { constructor(status, body) { this.status = status; this.body = body; } }
  const ok = (b) => new Res(200, b), made = (b) => new Res(201, b), err = (s, detail, code) => new Res(s, {detail, code});
  const said = (s) => s.fragments.some((f) => f.idx > 0 && String(f.answer || '').trim());
  const row = (s) => ({session_id: s.session_id, title: s.title, elder_id: s.elder_id, state: s.state, created_at: s.created_at, photo_id: null,
    turn: s.fragments.length - 1, fragment_count: s.fragments.length, has_words: said(s), has_postcard: !!s.postcard, postcard_title: s.postcard ? s.postcard.title : null});
  const mySessions = () => db.sessions.filter((s) => !s.deleted);
  function cardFrom(s) {
    const answers = s.fragments.filter((f) => f.idx > 0).map((f) => f.answer).filter((a) => a && !a.startsWith('(예시 화면)'));
    const text = answers.length ? answers.join('\n\n') : '들려주신 이야기를 엽서로 옮겼어요. (예시 화면에서는 마이크 말씀을 글로 옮기지 않아 예시 문장으로 채웠어요.)';
    return {title: `${s.title} 이야기`, text, style: 'spoken', caption: '', created_at: now()};
  }
  function memoirResult(ids, style) {
    const chosen = ids.map((id) => db.sessions.find((s) => s.session_id === id)).filter(Boolean)
      .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
    const chapters = chosen.map((s, i) => ({no: i + 1, title: (s.postcard && s.postcard.title) || s.title, status: 'ready',
      paragraphs: String((s.postcard && s.postcard.text) || s.fragments.filter((f) => f.idx > 0).map((f) => f.answer).join('\n\n'))
        .split(/\n\s*\n/).filter((p) => p.trim()).map((p) => ({sentences: p.split(/(?<=[.?!요다])\s+/).filter(Boolean).map((t) => ({text: t, turns: []}))}))}));
    const title = chosen.length ? `${chapters[0].title}에서 시작된 이야기` : '나의 이야기';
    return {status: 'ready', style, title, body: '', sources: [], to_confirm: [], chapters, run: {session_ids: ids, chapters_requested: chapters.length}};
  }
  function linkView(k) { return {state: k.state, theme: null, topic: k.topic, photo_url: null}; }
  const linkByToken = () => db.links.find((x) => x.token === LINK.token);
  const linkLive = () => { const k = linkByToken(); return k && k.session_id ? live.get(k.session_id) : null; };
  const pageUrl = () => location.href.split('#')[0].split('?')[0];

  async function handle(method, path, q, body) {
    await sleep(method === 'GET' ? 120 : 260);
    // 다른 탭(어르신 링크 예시)이 바꾼 것을 읽어 온다
    try { const fresh = JSON.parse(localStorage.getItem(KEY) || 'null'); if (fresh && fresh.sessions) db = fresh; } catch (_) {}
    let m;
    // 로그인
    if (path === '/auth/me') return db.logged ? ok({user: db.user, elders: db.elders}) : err(401, '로그인이 필요해요', 'login_required');
    if (path === '/auth/google' && method === 'POST') { db.logged = true; save(); return ok({user: db.user, elders: db.elders}); }
    if (path === '/auth/logout') { db.logged = false; save(); return new Res(204, null); }
    // 어르신 링크
    if (path.startsWith('/i/')) {
      const k = linkByToken();
      if (!k) return err(404, '링크를 찾을 수 없어요', 'invalid_link');
      if (k.state === 'revoked') return err(410, '거둔 링크예요', 'revoked');
      if (path === '/i/preview') return ok(linkView(k));
      if (path === '/i/start') {
        if (k.state === 'ended') return err(409, '끝난 인터뷰예요', 'ended');
        let L = linkLive();
        if (!L) { L = openSession({topic: k.topic, elder_id: k.elder_id, link: k.link_id}); k.session_id = L.snap.session_id; k.state = 'in_progress'; save(); }
        return ok({...snapOf(L), ...linkView(k)});
      }
      if (path === '/i/transcript') {
        if (k.state !== 'ended') return err(409, '아직 끝나지 않았어요', 'not_ended');
        const s = db.sessions.find((x) => x.session_id === k.session_id);
        return ok({theme: null, topic: k.topic, turns: (s ? s.fragments : []).filter((f) => f.idx > 0).map((f) => ({question: f.question || '', answer: f.answer}))});
      }
      if (path.startsWith('/i/session')) { const L = linkLive(); if (!L) return err(404, '회차가 없어요', 'interrupted'); return sessionRoute(L, method, path.slice('/i/session'.length), body); }
      return err(404, '없음');
    }
    if (!db.logged) return err(401, '로그인이 필요해요', 'login_required');
    // 화자
    if ((m = path.match(/^\/elders\/([^/]+)$/)) && (method === 'PATCH' || method === 'DELETE')) {
      const e = db.elders.find((x) => x.elder_id === m[1]);
      if (!e) return err(404, '이야기 주인공을 찾을 수 없어요', 'elder_not_found');
      if (method === 'PATCH') {
        const nm = String(body.name || '').trim();
        if (!nm) return err(422, '이름을 적어 주세요');
        e.name = nm; save(); return ok(e);
      }
      const has = db.sessions.some((s) => !s.deleted && s.elder_id === e.elder_id) || db.memoirs.some((x) => !x.deleted && x.elder_id === e.elder_id)
        || db.links.some((k) => k.elder_id === e.elder_id && ['ready', 'in_progress'].includes(k.state));
      if (has) return err(409, '기록이 있어 지울 수 없어요', 'has_records');
      db.elders = db.elders.filter((x) => x.elder_id !== e.elder_id); save(); return ok({elder_id: e.elder_id, deleted: true});
    }
    if (path === '/elders' && method === 'POST') { const e = {elder_id: 'demo-e' + (++db.seq + 10), name: String(body.name || '').trim()}; db.elders.push(e); save(); return made(e); }
    // 회차 목록 · 시작
    if (path === '/sessions' && method === 'GET') {
      let rows = mySessions();
      if (q.get('elder_id')) rows = rows.filter((s) => s.elder_id === q.get('elder_id'));
      if (q.get('has_postcard')) rows = rows.filter((s) => s.postcard);
      rows = rows.slice().sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, Number(q.get('limit')) || 20);
      return ok({sessions: rows.map(row)});
    }
    if (path === '/sessions' && method === 'POST') {
      if (!db.elders.some((e) => e.elder_id === body.elder_id)) return err(400, '화자를 골라 주세요', 'elder_required');
      return ok(snapOf(openSession({topic: body.topic || body.title || '나의 이야기', elder_id: body.elder_id})));
    }
    if ((m = path.match(/^\/sessions\/([^/]+)(\/.*)?$/))) {
      const id = m[1], rest = m[2] || '';
      const L = live.get(id);
      if (L && L.snap.state !== 'CLOSED' && rest !== '/record' && rest !== '/postcard') return sessionRoute(L, method, rest, body);
      const s = db.sessions.find((x) => x.session_id === id && !x.deleted);
      if (L && !rest && method === 'GET') return ok(snapOf(L));
      if (!s) return err(404, '회차를 찾을 수 없어요', 'not_found');
      if (rest === '' && method === 'DELETE') { s.deleted = true; save(); return ok({session_id: id, deleted: true}); }
      if (rest === '/record') return ok({session_id: id, title: s.title, elder_id: s.elder_id, created_at: s.created_at, fragments: s.fragments, postcard: s.postcard});
      if (rest === '/postcard' && method === 'POST') {
        if (!said(s)) return err(409, '엽서에 담을 말씀이 없어요', 'no_answers');
        await sleep(1200);
        s.postcard = cardFrom(s); save();
        return ok(s.postcard);
      }
      if (rest === '' && method === 'GET') return ok({...row(s), state: 'CLOSED', fragments: s.fragments});
      return err(404, '없음');
    }
    // 자서전
    if (path === '/memoirs' && method === 'POST') {
      const ids = body.session_ids || [];
      if (ids.length < 3) return err(400, '이야기를 3개 이상 골라 주세요', 'bad_selection');
      const job_id = 'demo-job-' + (++db.seq);
      db.jobs[job_id] = {ids, style: body.style || 'spoken', t0: Date.now(), cancelled: false}; save();
      return new Res(202, {job_id, status: 'running', stage: 'analysis', elapsed: 0});
    }
    if (path === '/memoirs/saved' && method === 'GET') {
      const rows = db.memoirs.filter((x) => !x.deleted && (!q.get('elder_id') || x.elder_id === q.get('elder_id')));
      return ok({memoirs: rows.slice().reverse().map(({result, deleted, ...r}) => r)});
    }
    if ((m = path.match(/^\/memoirs\/saved\/([^/]+)$/))) {
      const x = db.memoirs.find((y) => y.memoir_id === m[1] && !y.deleted);
      if (!x) return err(404, '자서전을 찾을 수 없어요', 'memoir_not_found');
      if (method === 'DELETE') { x.deleted = true; save(); return ok({memoir_id: x.memoir_id, deleted: true}); }
      const {deleted, ...r} = x; return ok(r);
    }
    if ((m = path.match(/^\/memoirs\/([^/]+)$/))) {
      const j = db.jobs[m[1]];
      if (!j) return err(404, '작업을 찾을 수 없어요', 'job_not_found');
      if (method === 'DELETE') { j.cancelled = true; save(); return ok({job_id: m[1], status: 'failed', code: 'cancelled'}); }
      if (j.cancelled) return ok({job_id: m[1], status: 'failed', code: 'cancelled', detail: '그만두었어요'});
      const sec = Math.round((Date.now() - j.t0) / 1000), n = j.ids.length;
      if (sec < 2) return ok({job_id: m[1], status: 'running', stage: 'outline', elapsed: sec});
      if (sec < 2 + n) return ok({job_id: m[1], status: 'running', stage: 'chapter', chapter: Math.min(n, sec - 1), chapters: n, elapsed: sec});
      if (!j.memoir_id) {
        const result = memoirResult(j.ids, j.style), elder = db.sessions.find((s) => s.session_id === j.ids[0]);
        j.memoir_id = 'demo-m' + (++db.seq);
        db.memoirs.push({memoir_id: j.memoir_id, elder_id: elder ? elder.elder_id : null, session_ids: j.ids, style: j.style, engine: 'demo', status: 'ready', title: result.title, created_at: now(), result});
        save();
      }
      const x = db.memoirs.find((y) => y.memoir_id === j.memoir_id);
      return ok({job_id: m[1], status: 'done', style: j.style, elapsed: sec, memoir_id: j.memoir_id, result: x.result, run: {session_ids: j.ids}});
    }
    // 책 공유
    if (path === '/shares' && method === 'POST') {
      const sh = {share_id: 'demo-sh' + (++db.seq), book_id: body.book_id || '', title: body.book.title, chapters: (body.book.chapters || []).length, created_at: now(), revoked_at: null, live: true};
      db.shares.unshift(sh); save();
      return made({...sh, token: tok(), url: 'https://naemalssami.com/b#예시-공유-링크'});
    }
    if (path === '/shares') return ok({shares: db.shares});
    if ((m = path.match(/^\/shares\/([^/]+)\/revoke$/))) { const sh = db.shares.find((x) => x.share_id === m[1]); if (!sh) return err(404, '없음'); sh.live = false; sh.revoked_at = now(); save(); return ok(sh); }
    // 초대 링크
    const linkOut = (k) => { const {token, ...r} = k; return r; };
    const issue = (base) => {
      const k = {link_id: 'demo-l' + (++db.seq), elder_id: base.elder_id, title: base.title || base.topic, theme: null, topic: base.topic, picked_topic: null,
        state: 'ready', session_id: null, created_at: now(), expires_at: new Date(Date.now() + 72 * 3600e3).toISOString(), token: tok()};
      db.links.unshift(k); save();
      return made({...linkOut(k), token: k.token, url: `${pageUrl()}?demo=elder#${k.token}`});
    };
    if (path === '/links' && method === 'POST') return issue(body);
    if (path === '/links') return ok({links: db.links.filter((k) => !q.get('elder_id') || k.elder_id === q.get('elder_id')).map(linkOut)});
    if ((m = path.match(/^\/links\/([^/]+)\/(revoke|reissue)$/))) {
      const k = db.links.find((x) => x.link_id === m[1]);
      if (!k) return err(404, '없음');
      if (m[2] === 'reissue' && k.session_id) return err(409, '이미 시작한 인터뷰의 링크예요', 'already_started');
      k.state = 'revoked'; save();
      if (m[2] === 'revoke') { const L = k.session_id && live.get(k.session_id); if (L) closeSession(L); return ok(linkOut(k)); }
      return issue(k);
    }
    return err(404, '예시 화면에 없는 기능이에요', 'demo_missing');
  }
  function sessionRoute(L, method, rest, body) {
    tick(L);
    const s = L.snap;
    if (rest === '' && method === 'GET') return ok(snapOf(L));
    if (rest === '/question/audio' || rest === '/question/stream') return new Res(204, null);
    if (rest === '/tts-done') { if (s.state === 'SPEAKING') s.state = 'LISTENING'; return ok(snapOf(L)); }
    if (rest === '/speech/audio') {
      if (s.state !== 'LISTENING') return err(409, '지금은 받을 수 없어요');
      const n = body && body.byteLength || 0;
      if (n > 1600) { L.audio += n; L.lastAudio = Date.now(); s.audio_bytes = L.audio; }
      return ok(snapOf(L));
    }
    if (rest === '/speech') { if (s.state !== 'LISTENING') return err(409, '정리하는 중이에요'); L.pending = String(body.text || ''); return ok(snapOf(L)); }
    if (rest === '/done') {
      if (L.pending) commit(L, L.pending);
      else if (L.audio > 0) commit(L, '(예시 화면) 마이크로 들려주신 말씀이에요. 예시 화면에서는 소리를 글로 옮기지 않아요.');
      return ok(snapOf(L));
    }
    if (rest === '/abort') { closeSession(L); return ok(snapOf(L)); }
    return err(404, '없음');
  }

  // ── fetch 가로채기 — /api/ 로 가는 요청만 ──
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const raw = typeof input === 'string' ? input : input.url;
    const i = raw.indexOf('/api/');
    if (i < 0) return realFetch(input, init);
    const u = new URL(raw.slice(i + 4), 'http://demo.local');
    const method = String(init.method || 'GET').toUpperCase();
    let body = init.body;
    if (typeof body === 'string') { try { body = JSON.parse(body); } catch (_) { body = {}; } }
    if (init.signal && init.signal.aborted) throw new DOMException('Aborted', 'AbortError');
    const r = await handle(method, u.pathname, u.searchParams, body || {});
    if (r.status === 204) return new Response(null, {status: 204});
    return new Response(JSON.stringify(r.body), {status: r.status, headers: {'Content-Type': 'application/json'}});
  };

  // ── 화면 표시: 예시 모드 띠 ──
  const badge = document.createElement('div');
  badge.className = 'demo-badge';
  badge.innerHTML = `<span><b>예시 화면</b> · 서버에 연결되지 않아요</span>${mode === 'elder' ? '' : '<button type="button">처음 상태로</button>'}`;
  badge.querySelector('button')?.addEventListener('click', () => {
    if (!window.confirm('예시 화면을 처음 상태로 되돌릴까요? 이 브라우저에 남은 예시 기록이 지워져요.')) return;
    try {
      localStorage.removeItem(KEY);
      ['memoir.elderId', 'memoir.job', 'memoir.shares', 'liveSession'].forEach((k) => localStorage.removeItem(k));
      Object.keys(localStorage).filter((k) => k.startsWith('memoir.edit.')).forEach((k) => localStorage.removeItem(k));
    } catch (_) {}
    location.reload();
  });
  const st = document.createElement('style');
  st.textContent = `.demo-badge{position:fixed;left:12px;bottom:12px;z-index:9999;display:flex;gap:10px;align-items:center;padding:7px 10px 7px 14px;border-radius:999px;background:#2b2420e6;color:#fff8ec;font-size:13px;box-shadow:0 6px 18px #0004}
  .demo-badge button{font:inherit;font-size:12px;border:1px solid #fff8ec66;background:transparent;color:inherit;border-radius:999px;padding:4px 10px;cursor:pointer}
  @media(max-width:760px){.demo-badge{bottom:86px;left:8px;font-size:12px}}`;
  document.head.append(st);
  const put = () => document.body.append(badge);
  if (document.body) put(); else document.addEventListener('DOMContentLoaded', put);
  setInterval(() => live.forEach(tick), 1000);
}());
