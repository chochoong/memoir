(function () {
  'use strict';
  // 계정 · 화자 저장소 — 시안의 RolePreviewState 와 같은 모양(snapshot · addElder · selectElder …)으로,
  // 화자는 서버에서 온다.
  //   · 화자 목록은 GET /api/auth/me 의 elders 가 전부다 (따로 목록 API 가 없다).
  //   · 화자 등록은 POST /api/elders {name} → 201 {elder_id, name}. **부를 때마다 새 화자가 생긴다** —
  //     같은 이름이 이미 있으면 화면에서 먼저 막는다. 등록은 비동기(Promise)다.
  //   · 고른 화자는 이 브라우저에만 기억한다 (localStorage 'memoir.elderId').
  //   · 「나」 — 내 이야기를 직접 녹음할 때 쓰는 화자. 없으면 처음 녹음할 때 한 번 만든다 (ensureSelf).
  //   · 초대 링크는 서버(/api/links)에서 만들고 · 거두고 · 다시 만든다. 이 함수들은 비동기(Promise)다.
  const {api, AUTH} = window.Srv;
  const KEY = 'memoir.elderId';
  const SELF = '나';
  const copy = (v) => ({...v});
  const success = (data = {}) => ({ok: true, error: null, ...data});
  const failure = (error, invitation) => invitation ? {ok: false, error, invitation: copy(invitation)} : {ok: false, error};
  const listeners = new Set();
  const changed = () => listeners.forEach((fn) => { try { fn(); } catch (_) {} });

  function pickKept() {
    let keep = AUTH.elderId;
    if (!keep) { try { keep = localStorage.getItem(KEY) || ''; } catch (_) {} }
    AUTH.elderId = AUTH.elders.some((x) => x.elder_id === keep) ? keep : ((AUTH.elders[0] && AUTH.elders[0].elder_id) || '');
  }
  function remember(id) { AUTH.elderId = id; try { localStorage.setItem(KEY, id); } catch (_) {} }

  function setAccount(r) {
    AUTH.user = (r && r.user) || null;
    AUTH.elders = ((r && r.elders) || []).map((e) => ({elder_id: String(e.elder_id), name: String(e.name || '이름 없음')}));
    pickKept();
    changed();
  }

  function snapshot() {
    return {
      user: AUTH.user ? copy(AUTH.user) : null,
      elders: AUTH.elders.map(copy),
      selectedElderId: AUTH.elderId || null,
      invitations: invitations.map(copy),
    };
  }
  // 시안의 login() · logout() 자리 — 서버 계정은 srv-auth 가 채운다. 여기서는 아무것도 하지 않는다
  function login() { return success({user: AUTH.user ? copy(AUTH.user) : null}); }
  function logout() { return success({user: null}); }

  const making = new Map();   // 이름 → 진행 중인 등록 (연타 · 중복 요청 막기)
  async function addElder(name) {
    if (typeof name !== 'string' || !name.trim()) return failure('invalid_name');
    const trimmed = name.trim().slice(0, 30);
    if (!AUTH.user) return failure('login_required');
    if (AUTH.elders.some((e) => e.name === trimmed)) return failure('duplicate_name');
    if (making.has(trimmed)) return making.get(trimmed);
    const job = (async () => {
      try {
        const r = await api.elderCreate(trimmed);
        const elder = {elder_id: String(r.elder_id), name: String(r.name || trimmed)};
        if (!AUTH.elders.some((e) => e.elder_id === elder.elder_id)) AUTH.elders.push(elder);
        remember(elder.elder_id);
        changed();
        return success({elder: copy(elder)});
      } catch (e) {
        return failure(e.status === 401 ? 'login_required' : 'server', null);
      } finally { making.delete(trimmed); }
    })();
    making.set(trimmed, job);
    return job;
  }
  /** 「나」 화자 — 있으면 그것, 없으면 한 번 만든다 */
  async function ensureSelf() {
    const self = AUTH.elders.find((e) => e.name === SELF);
    if (self) return success({elder: copy(self)});
    return addElder(SELF);
  }

  function selectElder(id) {
    const elder = AUTH.elders.find((c) => c.elder_id === id);
    if (!elder) return failure('elder_not_found');
    remember(elder.elder_id);
    changed();
    return success({elder: copy(elder)});
  }

  // ── 초대 링크 (서버 /api/links) ──
  //   발급 POST /api/links {elder_id, title, seed, topic} → 201 {link_id, …, token, url}
  //   **주소(url)는 발급 응답에만 한 번 온다** — 목록(GET /api/links)에는 없다.
  //   회수 POST /api/links/{id}/revoke (진행 중이면 인터뷰가 멈춘다) · 재발급 POST /api/links/{id}/reissue (시작한 링크는 409)
  let invitations = [];
  const issuedBy = new Map();     // 주소 → 초대 (방금 만든 것만 — 보내기 창이 이름 · 주제를 채운다)
  const STATE = {ready: 'ready', in_progress: 'in_progress', ended: 'completed', interrupted: 'interrupted', expired: 'expired', revoked: 'revoked'};
  const absUrl = (u) => { try { return new URL(u, location.origin).href; } catch (_) { return String(u || ''); } };
  const fromLink = (l) => ({id: l.link_id, elder_id: l.elder_id, topic: String(l.picked_topic || l.topic || l.title || '').trim() || '살아온 이야기',
    status: STATE[l.state] || l.state, session_id: l.session_id || null, created_at: l.created_at, expires_at: l.expires_at});
  const canRevoke = (inv) => !!inv && ['ready', 'in_progress'].includes(inv.status);
  const canReissue = (inv) => !!inv && !inv.session_id && ['ready', 'expired', 'revoked'].includes(inv.status);
  function upsert(inv) { const i = invitations.findIndex((x) => x.id === inv.id); if (i >= 0) invitations[i] = inv; else invitations.unshift(inv); return inv; }
  async function loadInvitations() {
    if (!AUTH.user) { invitations = []; return success({invitations: []}); }
    try { const r = await api.linkList(100); invitations = ((r && r.links) || []).map(fromLink); return success({invitations: invitations.map(copy)}); }
    catch (e) { return failure('server'); }
  }
  function issued(r) {
    const inv = upsert(fromLink(r)), address = absUrl(r.url);
    issuedBy.set(address, inv);
    return success({invitation: copy(inv), address});
  }
  async function issueInvitation({elderId, topic} = {}) {
    if (!AUTH.elders.some((e) => e.elder_id === elderId)) return failure('elder_not_found');
    if (typeof topic !== 'string' || !topic.trim()) return failure('topic_required');
    const t = topic.trim().slice(0, 60);
    try { return issued(await api.linkCreate({elder_id: elderId, title: t, seed: t, topic: t})); }
    catch (e) { return failure(e.status === 404 ? 'elder_not_found' : 'server'); }
  }
  async function revoke(id) {
    const inv = invitations.find((x) => x.id === id);
    if (!inv) return failure('invitation_not_found');
    if (!canRevoke(inv)) return failure('cannot_revoke', inv);
    try { const r = await api.linkRevoke(id); return success({changed: true, invitation: copy(upsert(fromLink({...r, link_id: id})))}); }
    catch (e) { return failure('server', inv); }
  }
  async function reissue(id) {
    const inv = invitations.find((x) => x.id === id);
    if (!inv) return failure('invitation_not_found');
    if (!canReissue(inv)) return failure('cannot_reissue', inv);
    try { const r = await api.linkReissue(id); inv.status = 'revoked'; return issued(r); }
    catch (e) { return failure(e.code === 'already_started' ? 'already_started' : 'server', inv); }
  }
  const invitationByAddress = (address) => { const inv = issuedBy.get(address); return inv ? copy(inv) : null; };
  // 시안의 탭 안 초대 흉내 — 서버 링크로 바뀌어 쓰지 않는다
  const unused = () => failure('unsupported');

  const store = Object.freeze({
    snapshot, login, logout, addElder, selectElder, ensureSelf, setAccount,
    issueInvitation, revoke, reissue, loadInvitations, invitationByAddress, canRevoke, canReissue,
    startInvitation: unused, completeInvitation: unused, invitationByReference: unused, seedReviewInvitations: unused,
    onChange: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
  });
  window.SrvStore = store;
}());
