(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./memoir-policy.js'), require('./service-contract.js'));
  } else {
    root.MemoirGenerationController = factory(root.MemoirSelectionPolicy, root.MemoirServiceContract);
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function (policy, contract) {
  'use strict';

  // Caller owns the UI and refresh cadence. This module has no DOM, storage,
  // authentication, transport, or timers. Client promises resolve raw job JSON.
  // latest/busy belong to an account, not an elder: they are never auto-adopted.
  const uuid = /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i;
  const jobId = /^[a-f\d]{32}$/i;
  function copy(value) {
    if (Array.isArray(value)) return value.map(copy);
    if (value && typeof value === 'object') {
      return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, copy(entry)]));
    }
    return value;
  }
  function problem(code) {
    return {status:0,kind:'validation',code,detail:code};
  }
  function ids(value) {
    if (!Array.isArray(value) || value.length < 3) throw problem('invalid_job_response');
    const normalized = Array.from(value, id => {
      if (typeof id !== 'string' || !uuid.test(id)) throw problem('invalid_job_response');
      return id.toLowerCase();
    });
    if (new Set(normalized).size !== normalized.length) throw problem('invalid_job_response');
    return normalized;
  }
  function sameIds(left, right) {
    return left.length === right.length && left.every(id => right.includes(id));
  }
  function errorView(error) {
    const status = Number.isInteger(error?.status) ? error.status : 0;
    return {
      status,
      code:typeof error?.code === 'string' ? error.code : status === 401 ? 'unauthorized' : 'request_failed',
      detail:copy(error?.detail ?? error?.message ?? null),
      kind:typeof error?.kind === 'string' ? error.kind : status ? 'http' : 'network',
    };
  }

  function create({client, onChange} = {}) {
    for (const method of ['createMemoir','getMemoir','cancelMemoir']) {
      if (typeof client?.[method] !== 'function') throw new TypeError(`client.${method} must be a function`);
    }
    let elderId = null;
    let metadata = null;
    let epoch = 0;
    let operation = 0;
    let active = null;
    const empty = () => ({
      phase:'idle',pending:null,elderId,request:null,job:null,document:null,
      canRead:false,error:null,existingJobId:null,scope:'none',
    });
    let state = empty();
    function getState() { return copy(state); }
    function publish(patch) {
      state = {...state,...patch};
      // Observers receive detached snapshots and cannot change controller state.
      if (typeof onChange === 'function') onChange(getState());
      return getState();
    }
    function reset() {
      epoch += 1; operation += 1; active = null;
      state = empty();
      return publish({});
    }
    function setContext(context = {}) {
      const next = typeof context.elderId === 'string' ? context.elderId.trim() : null;
      const changed = next !== elderId;
      elderId = next;
      metadata = copy(context.metadata ?? null);
      return changed ? reset() : publish({elderId});
    }
    function current(token) { return token.epoch === epoch && token.operation === operation; }
    function token() { return {epoch,operation:++operation}; }
    function blocked(code) {
      active = null;
      state = empty();
      return publish({phase:'blocked',error:problem(code)});
    }
    function fail(error, action, request) {
      const detail = errorView(error);
      if (detail.status === 401 && detail.kind !== 'abort' && detail.code !== 'aborted') {
        epoch += 1; operation += 1; metadata = null; active = null;
        state = empty();
        return publish({phase:'error',error:detail});
      }
      if (detail.status === 404 && detail.code === 'job_not_found' && action !== 'start') {
        active = null;
        return publish({phase:'expired',pending:null,job:null,document:null,canRead:false,error:detail,scope:'none'});
      }
      if (action === 'start' && detail.status === 409 && detail.code === 'busy') {
        const pointer = error?.job_id ?? error?.body?.job_id;
        active = null;
        return publish({
          phase:'busy',pending:null,job:null,document:null,canRead:false,error:detail,
          request,existingJobId:typeof pointer === 'string' && jobId.test(pointer) ? pointer : null,
          scope:'unverified',
        });
      }
      return publish({phase:'error',pending:null,document:null,canRead:false,error:detail});
    }
    function selectionScope(body) {
      if (!Array.isArray(metadata?.sessions)) return 'session_scope_unverified';
      for (const id of body.session_ids) {
        const rows = metadata.sessions.filter(row => typeof row?.session_id === 'string' && row.session_id.toLowerCase() === id);
        if (rows.length !== 1) return 'session_scope_unverified';
        const row = rows[0];
        if (row.elder_id !== elderId) return 'speaker_mismatch';
        if (typeof row.closed_at !== 'string' || !row.closed_at.trim() || row.has_words !== true) return 'session_ineligible';
      }
      return null;
    }
    function accept(response, context, starting = false) {
      const raw = copy(response);
      if (!raw || typeof raw !== 'object' || typeof raw.job_id !== 'string' || !jobId.test(raw.job_id)
        || !['running','done','failed'].includes(raw.status)) throw problem('invalid_job_response');
      if ((context.jobId && raw.job_id !== context.jobId) || raw.style !== 'spoken'
        || (raw.elder_id !== undefined && raw.elder_id !== context.elderId)) throw problem('job_scope_mismatch');
      if (starting && raw.status !== 'running') throw problem('invalid_job_response');
      const actualIds = ids(raw.run?.session_ids);
      if (context.runIds && !sameIds(actualIds,context.runIds)) throw problem('job_scope_mismatch');
      if (starting) {
        if (context.request.mode === 'explicit' && !sameIds(actualIds,context.request.sessionIds)) throw problem('job_scope_mismatch');
        if (context.request.mode === 'all-except' && actualIds.some(id => context.request.excludeSessionIds.includes(id))) throw problem('job_scope_mismatch');
      }
      if (raw.status === 'done') {
        if (raw.result?.style !== 'spoken' || (raw.result.elder_id !== undefined && raw.result.elder_id !== context.elderId)
          || !sameIds(ids(raw.result?.run?.session_ids),actualIds)) throw problem('job_scope_mismatch');
      }
      let job;
      try {
        job = contract.jobView(raw,{elder_id:context.elderId,uiStyle:context.request.uiStyle});
      } catch (_) {
        throw problem('invalid_job_response');
      }
      active = {...context,jobId:raw.job_id,runIds:actualIds,job};
      let phase = job.status;
      if (job.status === 'done' && !job.canRead) phase = raw.result.status === 'insufficient_material' ? 'insufficient_material' : 'incomplete';
      if (job.status === 'failed' && job.code === 'cancelled') phase = 'cancelled';
      if (!job.canRead) job.document = null;
      return publish({
        phase,pending:null,request:context.request,job,document:job.canRead ? job.document : null,
        canRead:job.canRead,error:job.status === 'failed' ? {status:200,kind:'job',code:job.code,detail:copy(job.detail)} : null,
        existingJobId:null,scope:'request',
      });
    }
    async function start(input = {}) {
      if (state.pending || active?.job.status === 'running') return getState();
      if (!elderId || elderId.length > 64) return blocked('invalid_elder_id');
      const prepared = policy.prepareRequest({...copy(input),elderId},copy(metadata));
      if (!prepared.ok) return blocked(prepared.code);
      if (input.mode === 'explicit') {
        const code = selectionScope(prepared.body);
        if (code) return blocked(code);
      }
      const request = {
        mode:input.mode,uiStyle:input.uiStyle,
        sessionIds:copy(prepared.body.session_ids ?? []),
        excludeSessionIds:copy(prepared.body.exclude_session_ids ?? []),
      };
      const context = {elderId,request,jobId:null,runIds:null};
      active = null;
      state = empty();
      const turn = token();
      publish({phase:'submitting',pending:'start',request});
      try {
        const raw = await client.createMemoir(copy(prepared.body),{isCurrent:() => current(turn)});
        if (!current(turn)) return getState();
        return accept(raw,context,true);
      } catch (error) {
        return current(turn) ? fail(error,'start',request) : getState();
      }
    }
    async function refresh() {
      if (!active || active.job.status !== 'running' || state.pending) return getState();
      const context = active;
      const turn = token();
      publish({pending:'refresh',error:null});
      try {
        const raw = await client.getMemoir(context.jobId,{isCurrent:() => current(turn)});
        if (!current(turn)) return getState();
        return accept(raw,context);
      } catch (error) {
        return current(turn) ? fail(error,'refresh',context.request) : getState();
      }
    }
    async function cancel() {
      if (state.pending === 'start') {
        reset();
        // A server job id is not available yet, so this is not a DELETE success.
        return publish({error:{status:0,kind:'local',code:'submission_abandoned',detail:'응답 추적만 중단했습니다. 서버의 작업 취소는 확인되지 않았습니다.'}});
      }
      if (!active || active.job.status !== 'running' || state.pending === 'cancel') return getState();
      const context = active;
      const turn = token();
      publish({phase:'cancelling',pending:'cancel',document:null,canRead:false,error:null});
      try {
        const raw = await client.cancelMemoir(context.jobId,{isCurrent:() => current(turn)});
        if (!current(turn)) return getState();
        return accept(raw,context);
      } catch (error) {
        return current(turn) ? fail(error,'cancel',context.request) : getState();
      }
    }

    return Object.freeze({setContext,start,refresh,cancel,reset,getState});
  }
  return {create};
});
