(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.RolePreviewState = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Tab-memory fixtures only. IDs and hash references are visibly synthetic;
  // they do not authenticate anyone and are never sent to an API or storage.
  function canRevoke(invitation) {
    return !!invitation && ['ready', 'in_progress'].includes(invitation.status);
  }

  function canReissue(invitation) {
    return !!invitation && !invitation.session_id && ['ready', 'expired', 'revoked'].includes(invitation.status);
  }

  function createStore({emptySpeakers = false} = {}) {
    let user = null;
    const elders = emptySpeakers ? [] : [{elder_id:'preview-self', name:'나'}];
    let selectedElderId = elders.length ? elders[0].elder_id : null;
    const invitations = [];
    let elderCount = 0;
    let invitationCount = 0;
    let sessionCount = 0;
    let fixtureIds = null;

    const copy = (value) => ({...value});
    const success = (data = {}) => ({ok:true, error:null, ...data});
    function failure(error, invitation) {
      return invitation ? {ok:false, error, invitation:copy(invitation)} : {ok:false, error};
    }
    const findInvitation = (id) => invitations.find((invitation) => invitation.id === id);
    const nextSessionId = () => `preview-session-${++sessionCount}`;

    function snapshot() {
      return {
        user:user ? copy(user) : null,
        elders:elders.map(copy),
        selectedElderId,
        invitations:invitations.map(copy),
      };
    }

    function login() {
      user = {user_id:'preview-user', name:'Google Login Mock Data'};
      return success({user:copy(user)});
    }

    function logout() {
      user = null;
      return success({user:null});
    }

    function addElder(name) {
      if (typeof name !== 'string' || !name.trim()) return failure('invalid_name');
      const trimmed = name.trim();
      if (elders.some((elder) => elder.name === trimmed)) return failure('duplicate_name');
      const elder = {elder_id:`preview-elder-${++elderCount}`, name:trimmed};
      elders.push(elder);
      selectedElderId = elder.elder_id;
      return success({elder:copy(elder)});
    }

    function selectElder(id) {
      const elder = elders.find((candidate) => candidate.elder_id === id);
      if (!elder) return failure('elder_not_found');
      selectedElderId = elder.elder_id;
      return success({elder:copy(elder)});
    }

    function newInvitation(elderId, topic, status = 'ready') {
      const invitation = {
        id:`preview-invite-${++invitationCount}`,
        elder_id:elderId,
        topic,
        status,
        session_id:['in_progress', 'completed'].includes(status) ? nextSessionId() : null,
        revision:1,
        preview:true,
      };
      invitations.push(invitation);
      return invitation;
    }

    function issuedResult(invitation) {
      const number = invitation.id.slice('preview-invite-'.length);
      // Deliberately return, but never retain, the example address.
      return success({
        invitation:copy(invitation),
        address:`http://127.0.0.1:4173/#invite-preview-${number}-r${invitation.revision}`,
      });
    }

    function issueInvitation({elderId, topic} = {}) {
      if (!elders.some((elder) => elder.elder_id === elderId)) return failure('elder_not_found');
      if (typeof topic !== 'string' || !topic.trim()) return failure('topic_required');
      return issuedResult(newInvitation(elderId, topic.trim()));
    }

    function revoke(id) {
      const invitation = findInvitation(id);
      if (!invitation) return failure('invitation_not_found');
      if (!canRevoke(invitation)) return failure('cannot_revoke', invitation);
      invitation.status = 'revoked';
      // Preserve an existing session so cancelling an active interview can
      // never make that same invitation eligible for reissue.
      return success({changed:true, invitation:copy(invitation)});
    }

    function reissue(id) {
      const invitation = findInvitation(id);
      if (!invitation) return failure('invitation_not_found');
      if (!canReissue(invitation)) return failure('cannot_reissue', invitation);
      invitation.revision += 1;
      invitation.status = 'ready';
      return issuedResult(invitation);
    }

    function startInvitation(id) {
      const invitation = findInvitation(id);
      if (!invitation) return failure('invitation_not_found');
      if (invitation.status === 'in_progress') return success({changed:false, invitation:copy(invitation)});
      if (invitation.status !== 'ready') return failure('cannot_start', invitation);
      invitation.status = 'in_progress';
      invitation.session_id = nextSessionId();
      return success({changed:true, invitation:copy(invitation)});
    }

    function completeInvitation(id) {
      const invitation = findInvitation(id);
      if (!invitation) return failure('invitation_not_found');
      if (invitation.status === 'completed') return success({changed:false, invitation:copy(invitation)});
      if (invitation.status !== 'in_progress') return failure('cannot_complete', invitation);
      invitation.status = 'completed';
      return success({changed:true, invitation:copy(invitation)});
    }

    function invitationByReference(reference) {
      if (typeof reference !== 'string') return failure('invalid_reference');
      const hash = reference.trim().replace(/^http:\/\/127\.0\.0\.1:4173\//, '');
      const match = /^#?invite-preview-([1-9]\d*)-r([1-9]\d*)$/.exec(hash);
      if (!match) return failure('invalid_reference');
      const invitation = findInvitation(`preview-invite-${match[1]}`);
      if (!invitation) return failure('invalid_reference');
      if (Number(match[2]) !== invitation.revision) return failure('superseded', invitation);
      if (!['ready', 'in_progress'].includes(invitation.status)) {
        return failure(`invitation_${invitation.status}`, invitation);
      }
      return success({invitation:copy(invitation)});
    }

    function seedReviewInvitations() {
      if (fixtureIds) return success({created:false, invitations:fixtureIds.map((id) => copy(findInvitation(id)))});
      if (!selectedElderId) return failure('elder_not_found');
      // An explicit review action, unrelated to issuing a usable invitation.
      const fixtures = ['ready', 'expired', 'revoked', 'in_progress', 'completed']
        .map((status) => newInvitation(selectedElderId, '어린 시절의 동네', status));
      fixtureIds = fixtures.map((invitation) => invitation.id);
      return success({created:true, invitations:fixtures.map(copy)});
    }

    return Object.freeze({
      snapshot, login, logout, addElder, selectElder,
      issueInvitation, revoke, reissue, startInvitation, completeInvitation,
      invitationByReference, seedReviewInvitations, canRevoke, canReissue,
    });
  }

  return Object.freeze({createStore, canRevoke, canReissue});
});
