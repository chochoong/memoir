(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MemoirSelectionPolicy = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Static review spike only. Legacy frontend selection defaults to 3–5 cards.
  // Server metadata and request mode can differ. This module sends no requests.
  const legacyPolicy = Object.freeze({min:3,max:5});
  const reviewPolicy = Object.freeze({min:3,max:null});

  function normalizePolicy(value) {
    if (!value || !Number.isInteger(value.min) || value.min < 1
      || (value.max !== null && (!Number.isInteger(value.max) || value.max < value.min))) {
      return {...legacyPolicy};
    }
    return {min:value.min,max:value.max};
  }

  function canGenerate(count, value = reviewPolicy) {
    const policy = normalizePolicy(value);
    return Number.isInteger(count) && count >= policy.min && (policy.max === null || count <= policy.max);
  }

  function canAdd(count, value = reviewPolicy) {
    const policy = normalizePolicy(value);
    return Number.isInteger(count) && count >= 0 && (policy.max === null || count < policy.max);
  }

  function orderedSelection(selectedIds, records) {
    const uuid = /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i;
    const chosen = [...new Set(selectedIds)].map((id) => records.find((record) => record.id === id))
      .filter((record) => record && typeof record.session_id === 'string' && uuid.test(record.session_id));
    return {records:chosen,session_ids:chosen.map((record) => record.session_id)};
  }

  function serverPolicy(metadata) {
    const unavailable = {
      available:false,enabled:false,engine:null,
      explicit:{min:3,max:null,known:false},allExcept:{min:3,max:null,known:false},
      maxChars:null,total:null,
    };
    if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) return unavailable;
    const engine = metadata.memoir_engine;
    const max = metadata.memoir_max;
    const has = (key) => Object.prototype.hasOwnProperty.call(metadata, key);
    const numericMax = Number.isSafeInteger(max) && max >= 3;
    if (typeof metadata.memoir_enabled !== 'boolean'
      || (engine !== 'single' && engine !== 'pipeline')
      || (!numericMax && !(engine === 'pipeline' && max === null))
      || (has('memoir_max_chars') && (!Number.isSafeInteger(metadata.memoir_max_chars) || metadata.memoir_max_chars <= 0))
      || (has('memoir_total') && (!Number.isSafeInteger(metadata.memoir_total) || metadata.memoir_total < 0))) {
      return unavailable;
    }
    return {
      available:true,enabled:metadata.memoir_enabled,engine,
      // pipeline null describes all-except only; the explicit cap is not exposed.
      explicit:{min:3,max,known:numericMax},allExcept:{min:3,max,known:true},
      maxChars:has('memoir_max_chars') ? metadata.memoir_max_chars : null,
      total:has('memoir_total') ? metadata.memoir_total : null,
    };
  }

  function styleBinding(uiStyle) {
    // Local backend app/session/style.py currently supports only spoken.
    return uiStyle === 'plain'
      ? {supported:true,apiStyle:'spoken',code:null}
      : {supported:false,apiStyle:null,code:'unsupported_style'};
  }

  function checkedIds(value, field) {
    const uuid = /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i;
    if (!Array.isArray(value)) return {code:`invalid_${field}`};
    const ids = [];
    for (const id of value) {
      if (typeof id !== 'string' || !uuid.test(id.trim())) return {code:`invalid_${field}`};
      ids.push(id.trim().toLowerCase());
    }
    if (new Set(ids).size !== ids.length) return {code:`duplicate_${field}`};
    return {ids};
  }

  function prepareRequest(input, metadata) {
    const deny = (code) => ({ok:false,body:null,code});
    const limits = serverPolicy(metadata);
    if (!limits.available) return deny('metadata_unavailable');
    if (!limits.enabled) return deny('memoir_disabled');
    if (!input || (input.mode !== 'explicit' && input.mode !== 'all-except')) return deny('invalid_mode');
    const style = styleBinding(input.uiStyle);
    if (!style.supported) return deny(style.code);

    if (input.mode === 'explicit') {
      const selected = checkedIds(input.sessionIds, 'session_ids');
      if (selected.code) return deny(selected.code);
      if (selected.ids.length < limits.explicit.min) return deny('insufficient_sessions');
      if (!limits.explicit.known) return deny('explicit_limit_unknown');
      if (selected.ids.length > limits.explicit.max) return deny('too_many_sessions');
      return {ok:true,body:{session_ids:selected.ids,style:style.apiStyle},code:null};
    }

    const elder = typeof input.elderId === 'string' ? input.elderId.trim() : '';
    if (!elder || elder.length > 64) return deny('invalid_elder_id');
    const excluded = checkedIds(input.excludeSessionIds === undefined ? [] : input.excludeSessionIds, 'exclude_session_ids');
    if (excluded.code) return deny(excluded.code);
    // Only the server can establish which exclusions belong to this elder.
    // A visible page and its selected IDs cannot establish the remaining total.
    if (limits.total !== null && limits.total < limits.allExcept.min) return deny('insufficient_sessions');
    return {ok:true,body:{elder_id:elder,exclude_session_ids:excluded.ids,style:style.apiStyle},code:null};
  }

  return {legacyPolicy,reviewPolicy,normalizePolicy,canGenerate,canAdd,orderedSelection,serverPolicy,styleBinding,prepareRequest};
});
