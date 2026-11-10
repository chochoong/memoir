const test = require('node:test');
const assert = require('node:assert/strict');
const api = require('./role-preview-state.js');

function issue(store, topic = '어린 시절의 동네') {
  return store.issueInvitation({elderId:'preview-self', topic});
}

test('the initial preview separates a logged-out account from the selected story speaker', () => {
  assert.equal(typeof api.createStore, 'function', 'the isolated role preview store must exist');
  const store = api.createStore();
  assert.deepEqual(store.snapshot(), {
    user:null,
    elders:[{elder_id:'preview-self', name:'나'}],
    selectedElderId:'preview-self',
    invitations:[],
  });
});

test('an account login never invents a speaker and a first speaker needs a nonblank unique name', () => {
  const store = api.createStore({emptySpeakers:true});
  const loggedIn = store.login();
  assert.equal(loggedIn.ok, true);
  assert.deepEqual(store.snapshot().user, {user_id:'preview-user', name:'Google Login Mock Data'});
  assert.deepEqual(store.snapshot().elders, []);
  assert.equal(store.snapshot().selectedElderId, null);
  for (const name of ['', ' \n\t ', null, undefined, 14]) {
    assert.deepEqual(store.addElder(name), {ok:false, error:'invalid_name'});
  }
  const added = store.addElder('  김영자  ');
  assert.equal(added.ok, true);
  assert.equal(added.elder.name, '김영자');
  assert.equal(store.snapshot().selectedElderId, added.elder.elder_id);
  assert.deepEqual(store.addElder('김영자 '), {ok:false, error:'duplicate_name'});
  assert.equal(store.snapshot().elders.length, 1);
});

test('selecting or adding another speaker preserves distinct account and existing speaker identities', () => {
  const store = api.createStore();
  store.login();
  const added = store.addElder('박도현');
  assert.equal(added.ok, true);
  assert.notEqual(added.elder.elder_id, 'preview-self');
  assert.equal(store.snapshot().selectedElderId, added.elder.elder_id);
  assert.equal(store.selectElder('preview-self').ok, true);
  const before = store.snapshot();
  assert.deepEqual(store.selectElder('not-found'), {ok:false, error:'elder_not_found'});
  assert.deepEqual(store.snapshot(), before);
  store.logout();
  assert.equal(store.snapshot().user, null);
  assert.deepEqual(store.snapshot().elders, before.elders);
});

test('issuing an invitation returns its only address without retaining it in snapshots', () => {
  const store = api.createStore();
  const result = issue(store, '  어린 시절의 동네  ');
  assert.equal(result.ok, true);
  assert.match(result.address, /^http:\/\/127\.0\.0\.1:4173\/#invite-preview-\d+-r1$/);
  assert.deepEqual(result.invitation, {
    id:'preview-invite-1', elder_id:'preview-self', topic:'어린 시절의 동네',
    status:'ready', session_id:null, revision:1, preview:true,
  });
  const visible = store.snapshot();
  assert.deepEqual(visible.invitations, [result.invitation]);
  assert.equal(JSON.stringify(visible).includes(result.address), false);
  assert.equal(JSON.stringify(visible).includes('invite-preview-'), false);
  assert.equal(Object.hasOwn(result.invitation, 'address'), false);
  assert.equal(Object.hasOwn(result.invitation, 'token'), false);
});

test('an invitation cannot be issued for an unknown speaker or without a prepared topic', () => {
  const store = api.createStore();
  assert.deepEqual(store.issueInvitation({elderId:'missing', topic:'기억'}), {ok:false, error:'elder_not_found'});
  assert.deepEqual(store.issueInvitation({elderId:'preview-self', topic:'  '}), {ok:false, error:'topic_required'});
  assert.deepEqual(store.issueInvitation({elderId:'preview-self', topic:null}), {ok:false, error:'topic_required'});
  assert.deepEqual(store.snapshot().invitations, []);
});

test('reissue eligibility requires both a permitted state and no session', () => {
  for (const [status, session_id, want] of [
    ['ready', null, true], ['expired', null, true], ['revoked', null, true],
    ['in_progress', null, false], ['completed', null, false],
    ['ready', 'existing-session', false], ['expired', 'existing-session', false],
    ['revoked', 'existing-session', false], ['completed', 'existing-session', false],
  ]) {
    assert.equal(api.canReissue({status, session_id}), want, `${status}/${session_id}`);
    assert.equal(api.createStore().canReissue({status, session_id}), want);
  }
  assert.equal(api.canReissue(null), false);
});

test('cancel eligibility includes a running interview and excludes expired revoked and completed states', () => {
  for (const [status, want] of [['ready', true], ['in_progress', true], ['expired', false], ['revoked', false], ['completed', false]]) {
    assert.equal(api.canRevoke({status}), want, status);
    assert.equal(api.createStore().canRevoke({status}), want);
  }
  assert.equal(api.canRevoke(undefined), false);
});

test('reissue invalidates the previous address and does not leak an address during later lookup', () => {
  const store = api.createStore();
  const first = issue(store);
  assert.equal(store.invitationByReference(first.address).ok, true);
  const next = store.reissue(first.invitation.id);
  assert.equal(next.ok, true);
  assert.equal(next.invitation.id, first.invitation.id);
  assert.equal(next.invitation.revision, 2);
  assert.notEqual(next.address, first.address);
  assert.equal(store.invitationByReference(first.address).error, 'superseded');
  const current = store.invitationByReference(next.address.slice(next.address.indexOf('#')));
  assert.equal(current.ok, true);
  assert.deepEqual(current.invitation, next.invitation);
  assert.equal(Object.hasOwn(current, 'address'), false);
  assert.equal(store.invitationByReference('#invite-preview-99-r1').error, 'invalid_reference');
  assert.equal(store.invitationByReference('arbitrary-input').error, 'invalid_reference');
});

test('starting the same invitation twice keeps one session and prevents reissue', () => {
  const store = api.createStore();
  const issued = issue(store);
  const first = store.startInvitation(issued.invitation.id);
  const again = store.startInvitation(issued.invitation.id);
  assert.equal(first.ok, true);
  assert.equal(first.changed, true);
  assert.equal(first.invitation.status, 'in_progress');
  assert.match(first.invitation.session_id, /^preview-session-/);
  assert.equal(again.ok, true);
  assert.equal(again.changed, false);
  assert.equal(again.invitation.session_id, first.invitation.session_id);
  assert.equal(store.snapshot().invitations.length, 1);
  assert.equal(store.reissue(issued.invitation.id).error, 'cannot_reissue');
});

test('completion is idempotent and a completed session can neither restart cancel nor reissue', () => {
  const store = api.createStore();
  const issued = issue(store);
  assert.equal(store.completeInvitation(issued.invitation.id).error, 'cannot_complete');
  const started = store.startInvitation(issued.invitation.id);
  const completed = store.completeInvitation(issued.invitation.id);
  const repeated = store.completeInvitation(issued.invitation.id);
  assert.equal(completed.ok, true);
  assert.equal(completed.changed, true);
  assert.equal(completed.invitation.status, 'completed');
  assert.equal(completed.invitation.session_id, started.invitation.session_id);
  assert.equal(repeated.ok, true);
  assert.equal(repeated.changed, false);
  assert.deepEqual(repeated.invitation, completed.invitation);
  assert.equal(store.startInvitation(issued.invitation.id).error, 'cannot_start');
  assert.equal(store.revoke(issued.invitation.id).error, 'cannot_revoke');
  assert.equal(store.reissue(issued.invitation.id).error, 'cannot_reissue');
  assert.equal(store.invitationByReference(issued.address).error, 'invitation_completed');
});

test('cancel before starting allows a fresh revision but a cancelled running session stays closed', () => {
  const store = api.createStore();
  const unused = issue(store);
  const cancelled = store.revoke(unused.invitation.id);
  assert.equal(cancelled.invitation.status, 'revoked');
  assert.equal(cancelled.invitation.session_id, null);
  assert.equal(store.invitationByReference(unused.address).error, 'invitation_revoked');
  assert.equal(store.startInvitation(unused.invitation.id).error, 'cannot_start');
  assert.equal(store.reissue(unused.invitation.id).ok, true);
  const running = issue(store);
  const started = store.startInvitation(running.invitation.id);
  const stopped = store.revoke(running.invitation.id);
  assert.equal(stopped.ok, true);
  assert.equal(stopped.invitation.session_id, started.invitation.session_id);
  assert.equal(store.reissue(running.invitation.id).error, 'cannot_reissue');
  assert.equal(store.completeInvitation(running.invitation.id).error, 'cannot_complete');
});

test('review fixtures expose all five statuses without issuing or retaining addresses', () => {
  const store = api.createStore();
  const seeded = store.seedReviewInvitations();
  assert.equal(seeded.ok, true);
  assert.equal(seeded.created, true);
  assert.deepEqual(store.snapshot().invitations.map((inv) => inv.status), ['ready', 'expired', 'revoked', 'in_progress', 'completed']);
  assert.equal(Object.hasOwn(seeded, 'address'), false);
  for (const inv of store.snapshot().invitations) {
    assert.equal(Object.hasOwn(inv, 'address'), false);
    assert.equal(Object.hasOwn(inv, 'token'), false);
  }
  const repeated = store.seedReviewInvitations();
  assert.equal(repeated.created, false);
  assert.equal(store.snapshot().invitations.length, 5);
  const expired = seeded.invitations.find((inv) => inv.status === 'expired');
  assert.equal(store.revoke(expired.id).error, 'cannot_revoke');
  assert.equal(store.startInvitation(expired.id).error, 'cannot_start');
  assert.equal(store.reissue(expired.id).ok, true);
  const next = issue(store);
  assert.equal(next.invitation.id, 'preview-invite-6');
});

test('snapshot and operation results are detached copies of the private store', () => {
  const store = api.createStore();
  const login = store.login();
  const issued = issue(store);
  const snapshot = store.snapshot();
  login.user.name = '바뀐 이름';
  issued.invitation.status = 'completed';
  snapshot.user.name = '침범한 계정';
  snapshot.elders[0].name = '침범한 화자';
  snapshot.invitations[0].revision = 90;
  snapshot.invitations.length = 0;
  const retained = store.snapshot();
  assert.equal(retained.user.name, 'Google Login Mock Data');
  assert.equal(retained.elders[0].name, '나');
  assert.equal(retained.invitations[0].status, 'ready');
  assert.equal(retained.invitations[0].revision, 1);
});

test('unknown invitation operations fail without adding or changing invitations', () => {
  const store = api.createStore();
  for (const action of ['revoke', 'reissue', 'startInvitation', 'completeInvitation']) {
    assert.deepEqual(store[action]('missing'), {ok:false, error:'invitation_not_found'});
  }
  assert.deepEqual(store.snapshot().invitations, []);
});
