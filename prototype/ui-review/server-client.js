(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./interview-state.js'));
  else root.MemoirServerClient = factory(root.InterviewVisualState);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (interviewState) {
  'use strict';

  // This module never chooses a host, reads a token from storage, or starts a
  // request on load. Only a caller-supplied fetch can perform network I/O.
  class ApiError extends Error {
    constructor({status = 0, code, detail, body = null, kind = 'http', cause}) {
      super(typeof detail === 'string' ? detail : (code || 'Request failed'));
      this.name = 'ApiError';
      this.status = status;
      this.code = code;
      this.detail = detail;
      this.body = body;
      this.kind = kind;
      if (cause !== undefined) this.cause = cause;
      const nested = body && typeof body.detail === 'object' && body.detail !== null ? body.detail : null;
      const jobId = body && (body.job_id || (nested && nested.job_id));
      if (typeof jobId === 'string') this.job_id = jobId;
    }
  }

  const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  function invalid(detail, code = 'invalid_request') {
    throw new ApiError({code, detail, kind:'validation'});
  }
  function object(value, label) {
    if (!isObject(value)) invalid(label + ' must be an object');
    return value;
  }
  function text(value, label, {max = Infinity, empty = false, trim = false} = {}) {
    if (typeof value !== 'string') invalid(label + ' must be text');
    const result = trim ? value.trim() : value;
    if ((!empty && !result.trim()) || result.length > max) invalid(label + ' is invalid');
    return result;
  }
  function opaqueId(value, label) {
    return text(value, label, {max:64,trim:true});
  }
  function sessionId(value) {
    if (typeof value !== 'string' || !/^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i.test(value.trim())) {
      invalid('session_id must be a server UUID');
    }
    return value.trim().toLowerCase();
  }
  function jobId(value) {
    if (typeof value !== 'string' || !/^[a-f\d]{32}$/i.test(value)) invalid('job_id must be a server 32-hex id');
    return value.toLowerCase();
  }
  function linkId(value) {
    if (typeof value !== 'string' || !/^l_[a-f\d]{32}$/i.test(value)) invalid('link_id must be a server link id');
    return value.toLowerCase();
  }
  function ids(value, label) {
    if (!Array.isArray(value)) invalid(label + ' must be an array');
    const out = [];
    for (let i = 0; i < value.length; i++) out.push(sessionId(value[i]));
    return out;
  }
  function style(value) {
    // app/session/style.py: only omitted/None and spoken are supported.
    if (value !== undefined && value !== null && value !== 'spoken') invalid('Unsupported server style', 'unsupported_style');
    return value;
  }
  function countLimit(value = 100) {
    if (!Number.isInteger(value) || value < 1 || value > 100) invalid('limit must be an integer from 1 to 100');
    return value;
  }
  function listQuery(value = {}, withPostcard = false) {
    object(value, 'list options');
    const query = new URLSearchParams({limit:String(countLimit(value.limit))});
    if (value.elderId !== undefined && value.elderId !== null) query.set('elder_id', opaqueId(value.elderId, 'elder_id'));
    if (withPostcard && value.hasPostcard !== undefined) {
      if (typeof value.hasPostcard !== 'boolean') invalid('hasPostcard must be boolean');
      query.set('has_postcard', String(value.hasPostcard));
    }
    return '?' + query.toString();
  }
  function preparation(value, forLink) {
    object(value, 'preparation');
    const out = {};
    if (forLink) out.elder_id = opaqueId(value.elder_id, 'elder_id');
    if (!forLink || own(value, 'title')) out.title = text(value.title, 'title', {max:forLink ? 100 : Infinity,empty:true});
    for (const [key, max] of [['seed',forLink ? 4000 : Infinity],['topic',100]]) {
      if (own(value, key)) out[key] = text(value[key], key, {max,empty:true});
    }
    if (own(value, 'theme')) {
      if (value.theme !== null && !['family','self','hobby'].includes(value.theme)) invalid('theme is unsupported');
      out.theme = value.theme;
    }
    if (own(value, 'photo_id')) out.photo_id = value.photo_id === null ? null : opaqueId(value.photo_id, 'photo_id');
    if (!forLink) {
      if (own(value, 'elder_id')) out.elder_id = value.elder_id === null ? null : opaqueId(value.elder_id, 'elder_id');
      if (own(value, 'pace')) out.pace = text(value.pace, 'pace', {empty:true});
      if (own(value, 'max_turn')) {
        if (!Number.isInteger(value.max_turn) || value.max_turn < 0) invalid('max_turn must be a nonnegative integer');
        out.max_turn = value.max_turn;
      }
    }
    return out;
  }
  function memoirBody(value) {
    object(value, 'memoir body');
    style(value.style);
    const explicit = own(value, 'session_ids');
    const allExcept = own(value, 'exclude_session_ids');
    // Reject an ambiguous caller request instead of silently preferring the
    // server's exclude_session_ids branch. Count/eligibility stays in policy.
    if (explicit === allExcept) invalid('Choose one server memoir request mode');
    const out = explicit
      ? {session_ids:ids(value.session_ids, 'session_ids')}
      : {elder_id:opaqueId(value.elder_id, 'elder_id'),exclude_session_ids:ids(value.exclude_session_ids, 'exclude_session_ids')};
    if (own(value, 'style')) out.style = value.style;
    return out;
  }
  function invitationToken(value) {
    if (typeof value !== 'string' || !/^[A-Za-z\d_-]{1,256}$/.test(value)) invalid('Invalid invitation token');
    return value;
  }
  function sessionPath(value) {
    object(value, 'session');
    if (value.guest !== undefined && typeof value.guest !== 'boolean') invalid('guest must be boolean');
    return value.guest === true ? '/api/i/session' : '/api/sessions/' + sessionId(value.sessionId);
  }
  function transportError(cause, status = 0) {
    const aborted = cause && cause.name === 'AbortError';
    return new ApiError({status,code:aborted ? 'aborted' : 'network_error',
      detail:aborted ? 'Request aborted' : 'Network request failed',kind:aborted ? 'abort' : 'network',cause});
  }

  function create(config) {
    if (!config || typeof config.fetch !== 'function') throw new TypeError('An explicit fetch implementation is required');
    if (config.onUnauthorized !== undefined && typeof config.onUnauthorized !== 'function') throw new TypeError('onUnauthorized must be a function');
    const fetchImpl = config.fetch;
    const onUnauthorized = config.onUnauthorized;

    async function fail(error, options) {
      let notify = error.status === 401 && error.kind !== 'abort' && error.code !== 'aborted' && !!onUnauthorized;
      if (notify && options.isCurrent !== undefined) {
        // Evaluate only after the body has settled: a speaker/context change
        // while the request was pending must not reset a newer auth scope.
        try { notify = options.isCurrent() === true; } catch (_) { notify = false; }
      }
      if (notify && !(options.signal && options.signal.aborted)) {
        // Keep auth side effects synchronous. A callback failure must not
        // replace the original API error returned to the request's owner.
        try { await onUnauthorized(error); } catch (_) { /* preserve API error */ }
      }
      throw error;
    }
    async function request(route, method, body, options = {}, extraHeaders) {
      object(options, 'request options');
      if (options.isCurrent !== undefined && typeof options.isCurrent !== 'function') invalid('isCurrent must be a synchronous predicate');
      if (options.signal && options.signal.aborted) throw transportError({name:'AbortError'});
      const headers = {...extraHeaders};
      const init = {method,credentials:'include',headers};
      if (options.signal !== undefined) init.signal = options.signal;
      if (body !== undefined) {
        headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify(body);
      }
      let response;
      try { response = await fetchImpl(route, init); }
      catch (cause) { throw transportError(cause); }
      if (!response || !Number.isInteger(response.status) || typeof response.text !== 'function') {
        throw new ApiError({code:'invalid_response',detail:'Invalid fetch response',kind:'invalid_response'});
      }
      if (response.status === 204 && response.ok) return null;
      let raw;
      try { raw = await response.text(); }
      catch (cause) { return fail(transportError(cause, response.status), options); }
      const contentType = response.headers && response.headers.get('content-type') || '';
      if (!/^application\/(?:[\w!#$&^.+-]+\+)?json(?:\s*;|\s*$)/i.test(contentType)) {
        return fail(new ApiError({status:response.status,code:'non_json_response',
          detail:'Expected a JSON response',body:raw,kind:'invalid_response'}), options);
      }
      let parsed;
      try { parsed = JSON.parse(raw); }
      catch (cause) {
        return fail(new ApiError({status:response.status,code:'invalid_json',
          detail:'The server returned malformed JSON',body:raw,kind:'invalid_response',cause}), options);
      }
      if (!response.ok) {
        const nested = isObject(parsed) && isObject(parsed.detail) ? parsed.detail : null;
        const code = isObject(parsed) && typeof parsed.code === 'string' ? parsed.code
          : nested && typeof nested.code === 'string' ? nested.code : 'http_' + response.status;
        const detail = isObject(parsed) && own(parsed, 'detail') ? parsed.detail : parsed;
        return fail(new ApiError({status:response.status,code,detail,body:parsed}), options);
      }
      return parsed;
    }

    return Object.freeze({
      async googleLogin(credential, options) {
        return request('/api/auth/google', 'POST', {credential:text(credential, 'credential', {max:4096})}, options);
      },
      async getMe(options) { return request('/api/auth/me', 'GET', undefined, options); },
      async logout(options) { return request('/api/auth/logout', 'POST', undefined, options); },
      async createElder(body, options) {
        object(body, 'elder');
        return request('/api/elders', 'POST', {name:text(body.name, 'name', {max:40,trim:true})}, options);
      },
      async createSession(body, options) { return request('/api/sessions', 'POST', preparation(body, false), options); },
      async listSessions(query, options) { return request('/api/sessions' + listQuery(query, true), 'GET', undefined, options); },
      async getSnapshot(session, options) { return request(sessionPath(session), 'GET', undefined, options); },
      async getRecord(id, options) { return request('/api/sessions/' + sessionId(id) + '/record', 'GET', undefined, options); },
      async assignElder(id, elderId, options) {
        return request('/api/sessions/' + sessionId(id) + '/elder', 'PUT', {elder_id:opaqueId(elderId, 'elder_id')}, options);
      },
      async createPostcard(id, body, options) {
        const route = '/api/sessions/' + sessionId(id) + '/postcard';
        let payload;
        if (body !== undefined) {
          object(body, 'postcard body');
          style(body.style);
          payload = own(body, 'style') ? {style:body.style} : {};
        }
        return request(route, 'POST', payload, options);
      },
      async createMemoir(body, options) { return request('/api/memoirs', 'POST', memoirBody(body), options); },
      async latestMemoir(options) { return request('/api/memoirs/latest', 'GET', undefined, options); },
      async getMemoir(id, options) { return request('/api/memoirs/' + jobId(id), 'GET', undefined, options); },
      async cancelMemoir(id, options) { return request('/api/memoirs/' + jobId(id), 'DELETE', undefined, options); },
      async interviewCommand(input, options) {
        object(input, 'interview command');
        if (!interviewState || typeof interviewState.commandFor !== 'function') invalid('InterviewVisualState is required', 'missing_interview_contract');
        const command = interviewState.commandFor(input.action);
        if (!command.supported) invalid(command.reason, 'unsupported_command');
        const body = input.action === 'send-text' ? {text:text(input.text, 'speech text', {empty:true})} : undefined;
        return request(sessionPath(input) + command.path, command.method, body, options);
      },
      async createLink(body, options) { return request('/api/links', 'POST', preparation(body, true), options); },
      async listLinks(query, options) { return request('/api/links' + listQuery(query), 'GET', undefined, options); },
      async revokeLink(id, options) { return request('/api/links/' + linkId(id) + '/revoke', 'POST', undefined, options); },
      async reissueLink(id, options) { return request('/api/links/' + linkId(id) + '/reissue', 'POST', undefined, options); },
      async previewInvitation(token, options) {
        return request('/api/i/preview', 'GET', undefined, options, {'x-interview-token':invitationToken(token)});
      },
      async startInvitation(token, body, options) {
        let payload = body;
        if (body !== undefined && body !== null) {
          object(body, 'invitation start');
          payload = own(body, 'topic') ? {topic:body.topic === null ? null : text(body.topic, 'topic', {max:60,empty:true})} : {};
        }
        // The server's raw state here is link state (e.g. in_progress), not FSM
        // state. Read getSnapshot({guest:true}) before interpreting the FSM.
        return request('/api/i/start', 'POST', payload, options, {'x-interview-token':invitationToken(token)});
      },
    });
  }

  return {create,ApiError};
});
