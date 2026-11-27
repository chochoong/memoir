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
  // 예시 사진 — 「우리 가족의 첫 소풍」 엽서에 붙어 있다 (예전 예시 기록에도 붙여 준다)
  const SEED_PHOTO = 'demo-ph-seed';
  db.sessions.forEach((x) => { if (x.photo_id === undefined && x.postcard && x.postcard.title === '우리 가족의 첫 소풍') { x.photo_id = SEED_PHOTO; x.postcard.caption = x.postcard.caption || '소풍날, 돗자리에 둘러앉은 가족'; } });
  const SEED_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 1200 900"><defs><filter id="s"><feColorMatrix type="matrix" values=".39 .77 .19 0 0 .35 .69 .17 0 0 .27 .53 .13 0 0 0 0 0 1 0"/></filter><radialGradient id="v" cx=".5" cy=".5" r=".75"><stop offset=".6" stop-opacity="0"/><stop offset="1" stop-opacity=".3"/></radialGradient><linearGradient id="k" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#9cc7e8"/><stop offset="1" stop-color="#e8f1f4"/></linearGradient></defs><g filter="url(#s)"><rect width="1200" height="900" fill="url(#k)"/><circle cx="980" cy="160" r="70" fill="#fff6d6"/><path d="M0 470Q250 360 520 440T1200 400V900H0Z" fill="#7fa36a"/><path d="M0 560Q300 500 640 560T1200 540V900H0Z" fill="#94b47a"/><rect x="150" y="300" width="40" height="230" fill="#6b4a32"/><circle cx="170" cy="280" r="120" fill="#4f7a45"/><circle cx="100" cy="330" r="80" fill="#5c8a50"/><circle cx="250" cy="320" r="90" fill="#5c8a50"/><path d="M330 670L850 630L930 760L390 810Z" fill="#c95b4f"/><g fill="#3d3330"><circle cx="460" cy="560" r="34"/><circle cx="580" cy="545" r="38"/><circle cx="700" cy="590" r="26"/><circle cx="790" cy="600" r="24"/></g><rect x="430" y="590" width="60" height="110" rx="24" fill="#2f4b6e"/><rect x="545" y="580" width="72" height="125" rx="26" fill="#efe7da"/><rect x="678" y="612" width="46" height="80" rx="18" fill="#d9a441"/><rect x="770" y="620" width="42" height="74" rx="16" fill="#7aa6c9"/><rect x="600" y="690" width="120" height="50" rx="8" fill="#2b2b2b"/><rect x="610" y="698" width="100" height="34" rx="4" fill="#f4e1a8"/></g><rect width="1200" height="900" fill="url(#v)"/></svg>`;
  // 올린 사진 — 이 탭 메모리에 둔다. 작으면(2MB 아래) 이 브라우저에도 남겨 다시 열어도 보이게
  const photos = new Map();
  const PHOTO_KEY = 'memoir.demo.photo.';
  async function keepPhoto(id, body, mime) {
    const blob = new Blob([body], {type: mime || 'image/jpeg'});
    photos.set(id, blob);
    if (blob.size < 2 * 1024 * 1024) {
      try { const url = await new Promise((r) => { const f = new FileReader(); f.onload = () => r(f.result); f.readAsDataURL(blob); }); localStorage.setItem(PHOTO_KEY + id, url); } catch (_) { /* 꽉 차면 이 탭에서만 */ }
    }
  }
  async function photoBlob(id) {
    if (id === SEED_PHOTO) return new Blob([SEED_SVG], {type: 'image/svg+xml'});
    if (photos.has(id)) return photos.get(id);
    try { const url = localStorage.getItem(PHOTO_KEY + id); if (url) return await (await fetch(url)).blob(); } catch (_) {}
    return null;
  }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(db)); } catch (_) {} };
  // ?demo=1&sample=1 — 보여 주기용: 열자마자 로그인돼 있고 책장에 예시 자서전 한 권 (v1.24).
  //   엽서 네 장(사진 붙은 「우리 가족의 첫 소풍」 포함)으로 만든 책 — 사진 · AI 그림 · 사진 편집을 바로 볼 수 있다.
  //   이 브라우저에 자서전이 하나도 없을 때만 넣는다(이미 있으면 그대로). 「처음 상태로」로 지우고 다시 열면 다시 들어간다.
  if (Srv.QS.get('sample')) {
    db.logged = true;
    if (!db.memoirs.some((x) => !x.deleted)) {
      const ids = db.sessions.filter((x) => !x.deleted && x.postcard && x.postcard.text).sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at)).map((x) => x.session_id);
      if (ids.length >= 3) {
        const result = memoirResult(ids, 'essay');
        db.memoirs.push({memoir_id: 'demo-m' + (++db.seq), elder_id: 'demo-e1', session_ids: ids, style: 'essay', engine: 'demo', status: 'ready', title: result.title, created_at: now(), result, sample: true});
      }
    }
  }
  save();

  // ── 가족 음성편지 (10-C1 흉내 · develop 1dffd3b 019) ──
  //   업로드: 바이트 그대로 + X-Request-ID(같은 id = 같은 업로드 200) → 201 {upload_id, state: 'uploaded', duration_ms, mime, size_bytes, expires_at, memoir_id}
  //   길이는 브라우저가 소리를 풀어 실제로 잰다(서버의 ffprobe 대신). 300초 + 2초 넘으면 422 too_long, 0.5초 미만 422 too_short,
  //   8MB 넘으면 413, 풀 수 없으면 415. 책 연결 PUT {upload_id, request_id, expected_revision} → {revision, message} — revision 이 다르면 409.
  //   음성 바이트는 이 탭 메모리 + (작으면) 이 브라우저에. 시험용 실패: localStorage 'demo.failVoice' =
  //     UPLOAD(503 한 번) · UPLOAD-after-save(저장은 되고 응답만 503) · LINK(503) · LINK-expired(410) · LINK-conflict(409) · DELETE(503)
  const VOICE_KEY = 'memoir.demo.voice.';
  const voices = new Map();
  const ups = () => (db.voiceUploads = db.voiceUploads || {});   // db 가 「처음 상태로」 등으로 바뀌어도
  async function keepVoice(id, blob) {
    voices.set(id, blob);
    if (blob.size < 2.5 * 1024 * 1024) {
      try { const url = await new Promise((r) => { const f = new FileReader(); f.onload = () => r(f.result); f.readAsDataURL(blob); }); localStorage.setItem(VOICE_KEY + id, url); } catch (_) { /* 꽉 차면 이 탭에서만 */ }
    }
  }
  async function voiceBlob(id) {
    if (voices.has(id)) return voices.get(id);
    try { const url = localStorage.getItem(VOICE_KEY + id); if (url) { const b = await (await fetch(url)).blob(); voices.set(id, b); return b; } } catch (_) {}
    return null;
  }
  async function measureMs(blob) {
    const Ctx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!Ctx) return null;
    try { const buf = await new Ctx(1, 44100, 44100).decodeAudioData(await blob.arrayBuffer()); return Math.round(buf.duration * 1000); } catch (_) { return null; }
  }
  const failVoice = (what) => { try { const v = localStorage.getItem('demo.failVoice'); if (v && v.startsWith(what)) { localStorage.removeItem('demo.failVoice'); return v; } } catch (_) {} return ''; };
  const upView = (u) => ({upload_id: u.upload_id, state: u.state, duration_ms: u.duration_ms, mime: u.mime, size_bytes: u.size_bytes, expires_at: u.expires_at, memoir_id: u.memoir_id || null});
  const msgView = (x) => {
    const v = x.voice;
    const message = v ? {message_id: v.upload_id, state: 'ready', duration_ms: v.duration_ms, mime: 'audio/mp4', created_at: v.created_at,
      playback_url: `/api/memoirs/saved/${x.memoir_id}/voice-message/audio?v=${v.upload_id}`} : null;
    return {revision: x.voiceRev || 0, message};
  };
  async function voiceRoute(method, path, q, body) {
    let m;
    if (path === '/voice-message-uploads' && method === 'POST') {
      await sleep(700);
      const rid = String(headersRid || '').trim();
      if (!rid) return err(400, 'X-Request-ID 가 필요해요', 'request_id_required');
      const old = Object.values(ups()).find((u) => u.request_id === rid);
      if (old) return old.state === 'uploaded' || old.state === 'attached' ? ok(upView(old)) : err(410, '올린 음성의 보관 기한이 지났어요. 새로 저장해 주세요', 'upload_expired');
      const blob = body instanceof Blob ? body : new Blob([body], {type: headersMime});
      if (blob.size > 8 * 1024 * 1024) return new Res(413, {detail: '음성이 너무 커요'});
      const fail = failVoice('UPLOAD');
      if (fail === 'UPLOAD') return err(503, '지금은 음성편지를 저장하지 못했어요');
      const ms = await measureMs(blob);
      if (ms === null) return err(415, '음성 파일을 읽지 못했어요', 'unsupported_audio');
      if (ms > 302000) return err(422, '음성편지는 5분까지예요', 'too_long');
      if (ms < 500) return err(422, '녹음이 너무 짧아요', 'too_short');
      const id = 'vu_demo' + (++db.seq) + Date.now().toString(36);
      const u = {upload_id: id, request_id: rid, state: 'uploaded', duration_ms: Math.min(ms, 300000), mime: /mp4/.test(blob.type) ? 'audio/mp4' : 'audio/webm',
        size_bytes: blob.size, expires_at: new Date(Date.now() + 24 * 3600e3).toISOString(), memoir_id: null};
      ups()[id] = u; await keepVoice(id, blob); save();
      if (fail === 'UPLOAD-after-save') return err(503, '연결이 잠시 끊겼어요');
      return made(upView(u));
    }
    if ((m = path.match(/^\/voice-message-uploads\/([^/]+)$/)) && method === 'DELETE') {
      const u = ups()[m[1]];
      if (!u) return err(404, '올린 음성을 찾을 수 없어요', 'upload_not_found');
      if (u.state === 'attached') return err(409, '책에 연결된 음성이에요. 책에서 지워 주세요', 'upload_attached');
      u.state = 'discarded'; save(); return new Res(204, null);
    }
    if (!(m = path.match(/^\/memoirs\/saved\/([^/]+)\/voice-message(\/audio)?$/))) return null;
    const x = db.memoirs.find((y) => y.memoir_id === m[1] && !y.deleted);
    if (!x) return err(404, '자서전을 찾을 수 없어요', 'memoir_not_found');
    if (m[2]) { const b = x.voice && await voiceBlob(x.voice.upload_id); return b ? new Res(200, b) : err(404, '음성편지를 찾을 수 없어요'); }
    if (method === 'GET') return ok(msgView(x));
    if (method === 'PUT') {
      await sleep(500);
      const rid = String(body.request_id || '').trim(), rev = body.expected_revision, u = ups()[String(body.upload_id || '')];
      if (!rid) return err(400, 'request_id 가 필요해요', 'request_id_required');
      if (!Number.isInteger(rev) || rev < 0) return err(400, 'expected_revision 은 0 이상의 숫자여야 해요', 'bad_revision');
      x.voiceReqs = x.voiceReqs || {};
      if (x.voiceReqs[rid]) return ok(msgView(x));                       // 같은 연결 요청의 재시도
      const fail = failVoice('LINK');
      if (fail === 'LINK') return err(503, '지금은 음성편지를 저장하지 못했어요');
      if (fail === 'LINK-conflict') { x.voiceRev = (x.voiceRev || 0) + 1; save(); return new Res(409, {detail: '다른 곳에서 음성편지가 바뀌었어요. 다시 불러와 주세요', code: 'revision_conflict', revision: x.voiceRev}); }
      if (rev !== (x.voiceRev || 0)) return new Res(409, {detail: '다른 곳에서 음성편지가 바뀌었어요. 다시 불러와 주세요', code: 'revision_conflict', revision: x.voiceRev || 0});
      if (!u) return err(404, '올린 음성을 찾을 수 없어요', 'upload_not_found');
      if (fail === 'LINK-expired' || u.state === 'discarded' || u.state === 'expired') { u.state = 'expired'; save(); return err(410, '올린 음성의 보관 기한이 지났어요. 새로 저장해 주세요', 'upload_expired'); }
      if (u.state === 'attached' && u.memoir_id !== x.memoir_id) return err(409, '이미 다른 책에 연결된 음성이에요', 'upload_in_use');
      if (x.voice && x.voice.upload_id !== u.upload_id) { const old = ups()[x.voice.upload_id]; if (old) old.state = 'discarded'; }
      u.state = 'attached'; u.memoir_id = x.memoir_id;
      x.voice = {upload_id: u.upload_id, duration_ms: u.duration_ms, created_at: now()};
      x.voiceRev = (x.voiceRev || 0) + 1; x.voiceReqs[rid] = true; save();
      return ok(msgView(x));
    }
    if (method === 'DELETE') {
      const rev = Number(q.get('expected_revision'));
      if (!Number.isInteger(rev) || rev < 0) return err(400, 'expected_revision 이 필요해요', 'bad_revision');
      if (failVoice('DELETE')) return err(503, '지금은 음성편지를 지우지 못했어요');
      if (rev !== (x.voiceRev || 0)) return new Res(409, {detail: '다른 곳에서 음성편지가 바뀌었어요. 다시 불러와 주세요', code: 'revision_conflict', revision: x.voiceRev || 0});
      if (!x.voice) return err(404, '음성편지가 없어요', 'message_not_found');
      const old = ups()[x.voice.upload_id]; if (old) old.state = 'discarded';
      x.voice = null; x.voiceRev = (x.voiceRev || 0) + 1; save();
      return new Res(204, null);
    }
    return err(405, '지원하지 않는 요청이에요.');
  }

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
    L.snap.next_question = (L.photo && n === 0) ? '함께 보내 주신 사진이 반가워요. 이 사진은 언제, 어디서 찍으신 건가요?'
      : qs[n % qs.length] + (n >= qs.length ? ' (예시 질문이 다시 돌아요)' : '');
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
  // 서버와 같은 목소리 이름만 받는다 (default · young). 예시 모드에서는 소리가 없어 고른 값만 기억한다
  const VOICE_OK = ['default', 'young'];
  function openSession({topic, elder_id, link, voice, photo}) {
    const sid = uid();
    const L = {topic, elder_id, link, photo, audio: 0, lastAudio: 0, pending: '',
      snap: {session_id: sid, state: 'SPEAKING', turn: 1, max_turn: 0, next_question: '', question_audio_stream: false, audio_bytes: 0, resumable: false, voice: voice || 'default',
        fragments: [{idx: 0, question: null, answer: topic}]}};
    ask(L);
    live.set(sid, L);
    return L;
  }
  function closeSession(L) {
    if (L.snap.state === 'CLOSED') return;
    L.snap.state = 'CLOSED';
    db.sessions.unshift({session_id: L.snap.session_id, title: L.topic, elder_id: L.elder_id, state: 'CLOSED', created_at: now(),
      fragments: L.snap.fragments, postcard: null, deleted: false, photo_id: L.photo || null});
    if (L.link) { const k = db.links.find((x) => x.link_id === L.link); if (k) k.state = 'ended'; }
    save();
  }

  // ── 가짜 서버 ──
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let headersMime = '', headersRid = '';
  class Res { constructor(status, body) { this.status = status; this.body = body; } }
  const ok = (b) => new Res(200, b), made = (b) => new Res(201, b), err = (s, detail, code) => new Res(s, {detail, code});
  const said = (s) => s.fragments.some((f) => f.idx > 0 && String(f.answer || '').trim());
  const row = (s) => ({session_id: s.session_id, title: s.title, elder_id: s.elder_id, state: s.state, created_at: s.created_at, photo_id: s.photo_id || null,
    turn: s.fragments.length - 1, fragment_count: s.fragments.length, has_words: said(s), has_postcard: !!s.postcard, postcard_title: s.postcard ? s.postcard.title : null});
  const mySessions = () => db.sessions.filter((s) => !s.deleted);
  function cardFrom(s) {
    const answers = s.fragments.filter((f) => f.idx > 0).map((f) => f.answer).filter((a) => a && !a.startsWith('(예시 화면)'));
    const text = answers.length ? answers.join('\n\n') : '들려주신 이야기를 엽서로 옮겼어요. (예시 화면에서는 마이크 말씀을 글로 옮기지 않아 예시 문장으로 채웠어요.)';
    return {title: `${s.title} 이야기`, text, style: 'spoken', caption: s.photo_id ? '함께 보내 주신 사진' : '', photo_id: s.photo_id || null, created_at: now()};
  }
  // 자서전 속 사진 · 삽화 (예시) — 장마다 그 회차의 사진을 첫 문단 뒤에. 사진 없는 첫 장에는 예시 삽화 한 장(「AI가 그린 그림」 모양 보기용)
  const DEMO_ILLUST = `<svg xmlns="http://www.w3.org/2000/svg" width="1250" height="1000" viewBox="0 0 1250 1000"><rect width="1250" height="1000" fill="#f3ead9"/><circle cx="1010" cy="190" r="80" fill="#f6d9a0"/><path d="M0 700Q300 600 640 680T1250 650V1000H0Z" fill="#c9d3a8"/><rect x="590" y="360" width="70" height="360" rx="20" fill="#7b5a3f"/><circle cx="625" cy="320" r="210" fill="#8fae6f"/><circle cx="470" cy="400" r="140" fill="#9cbb7b"/><circle cx="790" cy="400" r="150" fill="#86a766"/><g fill="#5d4a3d"><circle cx="420" cy="690" r="22"/><circle cx="500" cy="700" r="20"/><circle cx="820" cy="690" r="22"/></g><rect x="402" y="710" width="36" height="70" rx="14" fill="#c46a5a"/><rect x="483" y="718" width="34" height="62" rx="14" fill="#5f86a8"/><rect x="802" y="710" width="36" height="70" rx="14" fill="#d9a441"/></svg>`;
  // 자서전 사진 · 그림 자리 — 서버 계약 9-C1 (backend-agent 86cd502 · memoir_photos.py) 과 같은 모양으로 흉내 낸다.
  //   사진 배치(placement): auto(a_… 자동으로 놓인 회차 사진) · manual(p_… 사용자가 넣은 사진). AI 삽화는 origin ai · placement_id null — 옮기거나 빼지 않는다.
  //   같은 문단: 사진은 display_order → 넣은 순서, AI 삽화는 사진들 뒤. 넣은 사진은 책 한 권에 30장까지.
  const PHOTOS_MAX = 30;
  function initPlacements(x) {
    const ids = (x.session_ids || (x.result && x.result.run && x.result.run.session_ids) || []);
    const chosen = ids.map((id) => db.sessions.find((s) => s.session_id === id)).filter(Boolean).sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
    let drew = false;
    // ?demo=1&unplaced=1 — 「책에 넣지 못한 사진」 안내를 보려고: 사진 붙은 첫 회차의 사진을 놓지 못한 것으로, 올리다 끊긴 사진 하나를 더
    const unplacedDemo = Srv.QS.get('unplaced') ? chosen.find((s) => s.photo_id) : null;
    x.unplaced = unplacedDemo ? [
      {photo_id: unplacedDemo.photo_id, session_id: unplacedDemo.session_id, reason: 'session_not_cited', chapters: [], url: `/api/photos/${unplacedDemo.photo_id}`},
      {photo_id: 'demo-broken-photo', session_id: unplacedDemo.session_id, reason: 'photo_not_stored', chapters: [], url: null},
    ] : [];
    x.placements = []; x.ai = []; x.reqs = {};
    chosen.forEach((s, i) => {
      if (s.photo_id && s !== unplacedDemo) x.placements.push({placement_id: 'a_' + (++db.seq), origin: 'auto', photo_id: s.photo_id, chapter_no: i + 1, after_paragraph: 0, display_order: 0, seq: db.seq, width: s.photo_id === SEED_PHOTO ? 1200 : null, height: s.photo_id === SEED_PHOTO ? 900 : null});
      else if (!drew) { drew = true; x.ai.push({chapter_no: i + 1, after_paragraph: 0, url: `/api/memoirs/saved/${x.memoir_id}/illustrations/${i + 1}?v=demo`}); }
    });
    save();
  }
  const plOut = (pl) => ({placement_id: pl.placement_id, origin: pl.origin, photo_id: pl.photo_id, url: `/api/photos/${pl.photo_id}`, chapter_no: pl.chapter_no, after_paragraph: pl.after_paragraph, display_order: pl.display_order, width: pl.width, height: pl.height});
  function demoIllust(x) {
    if (!x.placements || !x.ai) initPlacements(x);
    const n = (x.result && x.result.chapters || []).length;
    const chapters = Array.from({length: n}, (_, i) => {
      const no = i + 1;
      const photos = x.placements.filter((pl) => pl.chapter_no === no).map((pl) => ({at: pl.after_paragraph, k: 0, o: pl.display_order, q: pl.seq,
        f: {kind: 'photo', url: `/api/photos/${pl.photo_id}`, after_paragraph: pl.after_paragraph, width: pl.width, height: pl.height, ai_generated: false, caption: null,
          placement_id: pl.placement_id, origin: pl.origin, display_order: pl.display_order, photo_id: pl.photo_id}}));
      const ai = x.ai.filter((a) => a.chapter_no === no).map((a) => ({at: a.after_paragraph, k: 1, o: 0, q: 0,
        f: {kind: 'illustration', url: a.url, after_paragraph: a.after_paragraph, width: 1250, height: 1000, ai_generated: true, caption: 'AI가 그린 그림',
          placement_id: null, origin: 'ai', display_order: null}}));
      const figs = [...photos, ...ai].sort((a, b) => a.at - b.at || a.k - b.k || a.o - b.o || a.q - b.q).map((x) => x.f);
      return {no, state: photos.length ? 'photo' : ai.length ? 'illustrated' : 'none', figures: figs};
    });
    return {status: 'done', automatic: true, human_reviewed: false, chapters, unplaced_photos: x.unplaced || []};
  }
  // 자리 검사 — 서버와 같은 갈래 (bad_position · no_such_chapter · no_such_paragraph)
  function badSpot(x, ch, para, order) {
    const num = (v) => v === undefined || v === null || v === '' ? NaN : Number(v);
    const c = num(ch), p = num(para);
    if (!Number.isInteger(c) || !Number.isInteger(p) || (order !== undefined && order !== null && !Number.isInteger(num(order)))) return err(422, '사진을 넣을 자리가 올바르지 않아요.', 'bad_position');
    const chap = (x.result && x.result.chapters || [])[c - 1];
    if (!chap || c < 1) return err(422, '자서전에 없는 장이에요.', 'no_such_chapter');
    if (p < 0 || p >= (chap.paragraphs || []).length) return err(422, '그 장에 없는 문단이에요.', 'no_such_paragraph');
    return null;
  }
  const endOrder = (x, ch, para, skip) => Math.max(-1, ...x.placements.filter((pl) => pl.chapter_no === ch && pl.after_paragraph === para && pl !== skip).map((pl) => pl.display_order)) + 1;
  // 시험용 실패: localStorage 'demo.failPhotoEdit' = POST · PATCH · DELETE 중 하나면 그 요청 한 번을 503 으로.
  // 'POST-after-save' 면 저장은 하고 응답만 503 (응답이 끊긴 경우 — request_id 로 다시 보내도 한 장만 들어가야 한다)
  function failMode(method) { try { const v = localStorage.getItem('demo.failPhotoEdit'); if (v && v.startsWith(method)) { localStorage.removeItem('demo.failPhotoEdit'); return v; } } catch (_) {} return ''; }
  async function photoEdit(method, x, pid, body, q) {
    await sleep(500);
    const fm = failMode(method);
    if (fm === method) return err(503, '잠시 저장하지 못했어요. 다시 시도해 주세요.');
    if (!x.placements || !x.ai) initPlacements(x);
    if (method === 'POST' && !pid) {
      const raw = body instanceof ArrayBuffer || ArrayBuffer.isView(body) || body instanceof Blob;
      const at = raw ? {chapter_no: q.get('chapter_no'), after_paragraph: q.get('after_paragraph'), display_order: q.get('display_order') ?? undefined, request_id: q.get('request_id')}
        : {chapter_no: body.chapter_no, after_paragraph: body.after_paragraph, display_order: body.display_order, request_id: body.request_id};
      const bad = badSpot(x, at.chapter_no, at.after_paragraph, at.display_order); if (bad) return bad;
      const ch = Number(at.chapter_no), para = Number(at.after_paragraph);
      if (at.request_id && x.reqs[at.request_id]) { const again = x.placements.find((pl) => pl.placement_id === x.reqs[at.request_id]); if (again) return ok({placement: plOut(again)}); }
      if (x.placements.filter((pl) => pl.origin === 'manual').length >= PHOTOS_MAX) return err(422, `한 권에 넣을 수 있는 사진은 ${PHOTOS_MAX}장까지예요.`, 'too_many_photos');
      let photoId, w = null, h = null;
      if (raw) {
        const blob = body instanceof Blob ? body : new Blob([body], {type: headersMime});
        if (blob.size > 20 * 1048576) return err(413, '사진이 너무 커요.');
        if (!/^image\//.test(headersMime || blob.type || '')) return err(400, '사진 파일이 아니에요.');
        photoId = 'demo-ph' + (++db.seq) + '-' + Date.now().toString(36);
        await keepPhoto(photoId, await blob.arrayBuffer(), headersMime);
        try { const bmp = await createImageBitmap(blob); w = bmp.width; h = bmp.height; } catch (_) {}
      } else {
        const id = String(body.photo_id || '');
        const known = (x.unplaced || []).find((u) => u.photo_id === id) || db.sessions.find((s) => s.photo_id === id);
        if (!id || !known) return err(404, '사진을 찾을 수 없어요.', 'photo_not_found');
        if (known.reason === 'photo_not_stored') return err(422, '아직 저장되지 않은 사진이에요.', 'photo_not_stored');
        photoId = id;
      }
      const pl = {placement_id: 'p_' + (++db.seq), origin: 'manual', photo_id: photoId, chapter_no: ch, after_paragraph: para,
        display_order: at.display_order !== undefined && at.display_order !== null && at.display_order !== '' ? Number(at.display_order) : endOrder(x, ch, para), seq: db.seq, width: w, height: h};
      x.placements.push(pl);
      if (at.request_id) x.reqs[at.request_id] = pl.placement_id;
      x.unplaced = (x.unplaced || []).filter((u) => u.photo_id !== photoId);
      save();
      if (fm === 'POST-after-save') return err(503, '잠시 저장하지 못했어요. 다시 시도해 주세요.');
      return made({placement: plOut(pl)});
    }
    const pl = x.placements.find((y) => y.placement_id === pid);
    if (!pl) return err(404, '그 사진을 찾을 수 없어요.', 'placement_not_found');
    if (method === 'PATCH') {
      const moving = 'chapter_no' in body || 'after_paragraph' in body;
      const ch = 'chapter_no' in body ? body.chapter_no : pl.chapter_no, para = 'after_paragraph' in body ? body.after_paragraph : pl.after_paragraph;
      const bad = badSpot(x, ch, para, body.display_order); if (bad) return bad;
      const nc = Number(ch), np = Number(para);
      const changed = nc !== pl.chapter_no || np !== pl.after_paragraph;
      pl.chapter_no = nc; pl.after_paragraph = np;
      if (Number.isInteger(body.display_order)) pl.display_order = body.display_order;
      else if (moving && changed) { pl.display_order = endOrder(x, nc, np, pl); pl.seq = ++db.seq; }
      save(); return ok({placement: plOut(pl)});
    }
    if (method === 'DELETE') { x.placements = x.placements.filter((y) => y !== pl); save(); return new Res(204, null); }
    return err(405, '지원하지 않는 요청이에요.');
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
        if (!L) { L = openSession({topic: k.topic, elder_id: k.elder_id, link: k.link_id, voice: k.voice, photo: k.photo_id || null}); k.session_id = L.snap.session_id; k.state = 'in_progress'; save(); }
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
    if (path === '/photos' && method === 'POST') { await sleep(900); const id = 'demo-ph' + (++db.seq) + '-' + Date.now().toString(36); save(); if (body instanceof ArrayBuffer || ArrayBuffer.isView(body)) await keepPhoto(id, body, headersMime); return ok({photo_id: id, url: `/api/photos/${id}`, mime: 'image/jpeg', width: 1024, height: 768, bytes: 123456}); }
    if (path === '/sessions' && method === 'POST') {
      if (!db.elders.some((e) => e.elder_id === body.elder_id)) return err(400, '화자를 골라 주세요', 'elder_required');
      if (body.voice !== undefined && !VOICE_OK.includes(body.voice)) return err(422, '목소리를 확인해 주세요');
      return ok(snapOf(openSession({topic: body.topic || body.title || '나의 이야기', elder_id: body.elder_id, voice: body.voice, photo: body.photo_id || null})));
    }
    if ((m = path.match(/^\/photos\/([^/]+)$/)) && method === 'GET') { const blob = await photoBlob(m[1]); return blob ? new Res(200, blob) : err(404, '사진을 찾을 수 없어요'); }
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
      // 삽화 그림체 — 실제 서버와 같게: 없으면 수채화, 모르는 값은 400 unsupported_illust_style
      const illust = body.illust_style === undefined ? 'watercolor' : body.illust_style;
      if (!['watercolor', 'anime', 'oil_painting'].includes(illust)) return err(400, '지원하지 않는 삽화 그림체예요.', 'unsupported_illust_style');
      const job_id = 'demo-job-' + (++db.seq);
      db.jobs[job_id] = {ids, style: body.style || 'spoken', illust_style: illust, t0: Date.now(), cancelled: false}; save();
      return new Res(202, {job_id, status: 'running', stage: 'analysis', elapsed: 0, illust_style: illust});
    }
    if (path === '/memoirs/saved' && method === 'GET') {
      const rows = db.memoirs.filter((x) => !x.deleted && (!q.get('elder_id') || x.elder_id === q.get('elder_id')));
      return ok({memoirs: rows.slice().reverse().map(({result, deleted, ...r}) => r)});
    }
    // 가족 음성편지 (10-C1 흉내) — voiceRoute 가 맡으면 그 답을 쓴다
    { const v = await voiceRoute(method, path, q, body); if (v) return v; }
    if ((m = path.match(/^\/memoirs\/saved\/([^/]+)\/photos(?:\/([^/]+))?$/))) {
      const x = db.memoirs.find((y) => y.memoir_id === m[1] && !y.deleted);
      if (!x) return err(404, '자서전을 찾을 수 없어요', 'memoir_not_found');
      return photoEdit(method, x, m[2] || null, body, q);
    }
    if ((m = path.match(/^\/memoirs\/saved\/([^/]+)\/illustrations(?:\/(\d+))?$/))) {
      const x = db.memoirs.find((y) => y.memoir_id === m[1] && !y.deleted);
      if (!x) return err(404, '자서전을 찾을 수 없어요', 'memoir_not_found');
      if (m[2]) return new Res(200, new Blob([DEMO_ILLUST], {type: 'image/svg+xml'}));
      return ok(demoIllust(x));
    }
    if ((m = path.match(/^\/memoirs\/saved\/([^/]+)$/))) {
      const x = db.memoirs.find((y) => y.memoir_id === m[1] && !y.deleted);
      if (!x) return err(404, '자서전을 찾을 수 없어요', 'memoir_not_found');
      if (method === 'DELETE') { x.deleted = true; save(); return ok({memoir_id: x.memoir_id, deleted: true}); }
      const {deleted, ...r} = x; return ok({...r, illustrations: demoIllust(x)});
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
      const k = {link_id: 'demo-l' + (++db.seq), elder_id: base.elder_id, title: base.title || base.topic, theme: null, topic: base.topic, picked_topic: null, voice: base.voice || 'default', photo_id: base.photo_id || null,
        state: 'ready', session_id: null, created_at: now(), expires_at: new Date(Date.now() + 72 * 3600e3).toISOString(), token: tok()};
      db.links.unshift(k); save();
      return made({...linkOut(k), token: k.token, url: `${pageUrl()}?demo=elder#${k.token}`});
    };
    if (path === '/links' && method === 'POST') { if (body.voice !== undefined && !VOICE_OK.includes(body.voice)) return err(422, '목소리를 확인해 주세요'); return issue(body); }
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
    headersMime = (init.headers && (init.headers['Content-Type'] || init.headers['content-type'])) || '';
    headersRid = (init.headers && (init.headers['X-Request-ID'] || init.headers['x-request-id'])) || '';
    const r = await handle(method, u.pathname, u.searchParams, body || {});
    if (r.status === 204) return new Response(null, {status: 204});
    if (r.body instanceof Blob) return new Response(r.body, {status: r.status, headers: {'Content-Type': r.body.type || 'application/octet-stream'}});
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
