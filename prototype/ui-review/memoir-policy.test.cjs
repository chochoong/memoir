'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const modulePath = path.join(__dirname, 'memoir-policy.js');
const policy = fs.existsSync(modulePath) ? require(modulePath) : {};

test('the review still requires three postcards before a draft can start', () => {
  assert.equal(typeof policy.canGenerate, 'function');
  assert.equal(policy.canGenerate(0), false);
  assert.equal(policy.canGenerate(2), false);
  assert.equal(policy.canGenerate(3), true);
  assert.equal(policy.canGenerate(-1), false);
  assert.equal(policy.canGenerate(3.5), false);
});

test('the review lets a sixth and later postcard be selected and previewed', () => {
  assert.equal(typeof policy.canAdd, 'function');
  assert.equal(policy.canAdd(5), true);
  assert.equal(policy.canAdd(100), true);
  assert.equal(policy.canGenerate(6), true);
  assert.equal(policy.canGenerate(100), true);
});

test('the separate legacy bounded policy rejects a sixth postcard', () => {
  assert.equal(typeof policy.canGenerate, 'function');
  assert.equal(policy.canGenerate(3, policy.legacyPolicy), true);
  assert.equal(policy.canGenerate(5, policy.legacyPolicy), true);
  assert.equal(policy.canGenerate(6, policy.legacyPolicy), false);
  assert.equal(policy.canAdd(5, policy.legacyPolicy), false);
  assert.equal(policy.canGenerate(6, policy.reviewPolicy), true);
});

test('invalid policies fall back to the legacy bounded policy', () => {
  assert.equal(typeof policy.normalizePolicy, 'function');
  for (const invalid of [null, {}, {min:0,max:null}, {min:3,max:2}, {min:3,max:Infinity}, {min:'3',max:null}]) {
    const normalized = policy.normalizePolicy(invalid);
    assert.equal(policy.canGenerate(2, normalized), false);
    assert.equal(policy.canGenerate(3, normalized), true);
    assert.equal(policy.canGenerate(6, normalized), false);
  }
  assert.equal(policy.canGenerate(8, policy.normalizePolicy({min:4,max:8})), true);
  assert.equal(policy.canGenerate(9, policy.normalizePolicy({min:4,max:8})), false);
  assert.equal(policy.canGenerate(100, policy.normalizePolicy({min:3,max:null})), true);
});

test('selection keeps UUIDs in click order after removal and reselection', () => {
  assert.equal(typeof policy.orderedSelection, 'function');
  const records = [
    {id:1,session_id:'00000000-0000-4000-8000-000000000001'},
    {id:2,session_id:'00000000-0000-4000-8000-000000000002'},
    {id:3,session_id:'00000000-0000-4000-8000-000000000003'},
    {id:4,session_id:'not-a-session-uuid'},
  ];
  const selected = new Set([3,1,2]);
  selected.delete(1);
  selected.add(1);
  selected.add(99);
  selected.add(4);
  const result = policy.orderedSelection(selected, records);
  assert.deepEqual(result.records.map((record) => record.id), [3,2,1]);
  assert.deepEqual(result.session_ids, [
    '00000000-0000-4000-8000-000000000003',
    '00000000-0000-4000-8000-000000000002',
    '00000000-0000-4000-8000-000000000001',
  ]);
});

const serverMetadata = {memoir_enabled:true,memoir_engine:'single',memoir_max:5,memoir_max_chars:150000};
const sessionIds = [
  'aaaaaaaa-0000-4000-8000-000000000001',
  'bbbbbbbb-0000-4000-8000-000000000002',
  'cccccccc-0000-4000-8000-000000000003',
  'dddddddd-0000-4000-8000-000000000004',
  'eeeeeeee-0000-4000-8000-000000000005',
  'ffffffff-0000-4000-8000-000000000006',
];

test('server metadata makes single-engine bounds available without changing the review policy', () => {
  assert.equal(typeof policy.serverPolicy, 'function');
  assert.deepEqual(policy.serverPolicy({...serverMetadata,memoir_total:23}), {
    available:true,enabled:true,engine:'single',
    explicit:{min:3,max:5,known:true},allExcept:{min:3,max:5,known:true},
    maxChars:150000,total:23,
  });
  assert.equal(policy.canGenerate(6), true);
  assert.equal(policy.canGenerate(6, policy.legacyPolicy), false);
});

test('pipeline null means unlimited all-except but an unknown explicit cap', () => {
  assert.equal(typeof policy.serverPolicy, 'function');
  assert.deepEqual(policy.serverPolicy({...serverMetadata,memoir_engine:'pipeline',memoir_max:null}), {
    available:true,enabled:true,engine:'pipeline',
    explicit:{min:3,max:null,known:false},allExcept:{min:3,max:null,known:true},
    maxChars:150000,total:null,
  });
});

test('missing or malformed server metadata never enables generation', () => {
  assert.equal(typeof policy.serverPolicy, 'function');
  const invalid = [
    undefined,null,[],{},
    {...serverMetadata,memoir_enabled:'true'},
    {...serverMetadata,memoir_engine:'future'},
    {...serverMetadata,memoir_max:undefined},
    {...serverMetadata,memoir_max:null},
    {...serverMetadata,memoir_max:2},
    {...serverMetadata,memoir_max:3.5},
    {...serverMetadata,memoir_max:Infinity},
    {...serverMetadata,memoir_max_chars:-1},
    {...serverMetadata,memoir_total:'23'},
  ];
  for (const metadata of invalid) {
    const result = policy.serverPolicy(metadata);
    assert.equal(result.available, false);
    assert.equal(result.enabled, false);
    assert.equal(result.explicit.known, false);
    assert.equal(result.allExcept.known, false);
  }
});

test('valid disabled metadata remains distinguishable from metadata lookup failure', () => {
  assert.equal(typeof policy.serverPolicy, 'function');
  const result = policy.serverPolicy({...serverMetadata,memoir_enabled:false});
  assert.equal(result.available, true);
  assert.equal(result.enabled, false);
  assert.equal(result.engine, 'single');
});

test('optional totals come only from memoir_total and do not infer from a visible list', () => {
  assert.equal(typeof policy.serverPolicy, 'function');
  const result = policy.serverPolicy({memoir_enabled:true,memoir_engine:'pipeline',memoir_max:8,sessions:sessionIds});
  assert.equal(result.total, null);
  assert.equal(result.maxChars, null);
  assert.deepEqual(result.explicit, {min:3,max:8,known:true});
  assert.deepEqual(result.allExcept, {min:3,max:8,known:true});
});

test('plain binds to the one verified API style while unsupported UI styles stay unsupported', () => {
  assert.equal(typeof policy.styleBinding, 'function');
  assert.deepEqual(policy.styleBinding('plain'), {supported:true,apiStyle:'spoken',code:null});
  for (const value of ['essay','story','letter','spoken','Plain',null,undefined]) {
    assert.deepEqual(policy.styleBinding(value), {supported:false,apiStyle:null,code:'unsupported_style'});
  }
});

test('explicit request uses canonical UUIDs in selection order with the supported style', () => {
  assert.equal(typeof policy.prepareRequest, 'function');
  const ids = [sessionIds[2].toUpperCase(),` ${sessionIds[0]} `,sessionIds[1]];
  const input = {mode:'explicit',sessionIds:ids,elderId:'ignored',excludeSessionIds:[sessionIds[3]],uiStyle:'plain'};
  assert.deepEqual(policy.prepareRequest(input, serverMetadata), {
    ok:true,body:{session_ids:[sessionIds[2],sessionIds[0],sessionIds[1]],style:'spoken'},code:null,
  });
  assert.deepEqual(input.sessionIds, ids);
});

test('explicit mode obeys server minimum and numeric maximum rather than review freedom', () => {
  assert.equal(typeof policy.prepareRequest, 'function');
  assert.deepEqual(policy.prepareRequest({mode:'explicit',sessionIds:sessionIds.slice(0,2),uiStyle:'plain'}, serverMetadata), {
    ok:false,body:null,code:'insufficient_sessions',
  });
  assert.equal(policy.prepareRequest({mode:'explicit',sessionIds:sessionIds.slice(0,5),uiStyle:'plain'}, serverMetadata).ok, true);
  assert.deepEqual(policy.prepareRequest({mode:'explicit',sessionIds,uiStyle:'plain'}, serverMetadata), {
    ok:false,body:null,code:'too_many_sessions',
  });
});

test('explicit mode refuses to bypass a cap hidden by pipeline null metadata', () => {
  assert.equal(typeof policy.prepareRequest, 'function');
  assert.deepEqual(policy.prepareRequest({mode:'explicit',sessionIds:sessionIds.slice(0,3),uiStyle:'plain'}, {
    ...serverMetadata,memoir_engine:'pipeline',memoir_max:null,
  }), {ok:false,body:null,code:'explicit_limit_unknown'});
});

test('explicit UUID validation rejects malformed IDs and duplicates despite case or whitespace', () => {
  assert.equal(typeof policy.prepareRequest, 'function');
  for (const ids of [undefined,{},[1,sessionIds[1],sessionIds[2]],['bad',sessionIds[1],sessionIds[2]]]) {
    assert.deepEqual(policy.prepareRequest({mode:'explicit',sessionIds:ids,uiStyle:'plain'}, serverMetadata), {
      ok:false,body:null,code:'invalid_session_ids',
    });
  }
  assert.deepEqual(policy.prepareRequest({mode:'explicit',sessionIds:[sessionIds[0],` ${sessionIds[0].toUpperCase()} `,sessionIds[1]],uiStyle:'plain'}, serverMetadata), {
    ok:false,body:null,code:'duplicate_session_ids',
  });
});

test('all-except request preserves server-wide scope and never emits visible session IDs', () => {
  assert.equal(typeof policy.prepareRequest, 'function');
  const input = {mode:'all-except',elderId:' elder-one ',excludeSessionIds:[sessionIds[2].toUpperCase()],sessionIds:[sessionIds[0]],uiStyle:'plain'};
  assert.deepEqual(policy.prepareRequest(input, {...serverMetadata,memoir_engine:'pipeline',memoir_max:null,memoir_total:200}), {
    ok:true,body:{elder_id:'elder-one',exclude_session_ids:[sessionIds[2]],style:'spoken'},code:null,
  });
});

test('all-except mode does not claim exclusions belong to the elder or guess a total', () => {
  assert.equal(typeof policy.prepareRequest, 'function');
  const input = {mode:'all-except',elderId:'elder',excludeSessionIds:sessionIds,sessionIds:[],uiStyle:'plain'};
  const metadata = {...serverMetadata,memoir_engine:'pipeline',memoir_max:null};
  assert.equal(policy.prepareRequest(input, {...metadata,memoir_total:3}).ok, true);
  assert.equal(policy.prepareRequest(input, {...metadata,sessions:[]}).ok, true);
  assert.deepEqual(policy.prepareRequest(input, {...metadata,memoir_total:2}), {
    ok:false,body:null,code:'insufficient_sessions',
  });
});

test('all-except mode validates an elder string and unique UUID exclusions', () => {
  assert.equal(typeof policy.prepareRequest, 'function');
  const input = {mode:'all-except',elderId:'elder',excludeSessionIds:[],uiStyle:'plain'};
  for (const elderId of [undefined,null,3,'','   ','a'.repeat(65)]) {
    assert.deepEqual(policy.prepareRequest({...input,elderId}, serverMetadata), {ok:false,body:null,code:'invalid_elder_id'});
  }
  assert.equal(policy.prepareRequest({...input,elderId:'a'.repeat(64)}, serverMetadata).ok, true);
  for (const excludeSessionIds of [null,{},[1],['bad']]) {
    assert.deepEqual(policy.prepareRequest({...input,excludeSessionIds}, serverMetadata), {ok:false,body:null,code:'invalid_exclude_session_ids'});
  }
  assert.deepEqual(policy.prepareRequest({...input,excludeSessionIds:[sessionIds[0],sessionIds[0].toUpperCase()]}, serverMetadata), {
    ok:false,body:null,code:'duplicate_exclude_session_ids',
  });
});

test('unavailable metadata, disabled feature, unsupported style, and unknown mode deny request bodies', () => {
  assert.equal(typeof policy.prepareRequest, 'function');
  const input = {mode:'explicit',sessionIds:sessionIds.slice(0,3),uiStyle:'plain'};
  assert.deepEqual(policy.prepareRequest(input), {ok:false,body:null,code:'metadata_unavailable'});
  assert.deepEqual(policy.prepareRequest(input, {...serverMetadata,memoir_enabled:false}), {ok:false,body:null,code:'memoir_disabled'});
  for (const uiStyle of ['essay','story','letter']) {
    assert.deepEqual(policy.prepareRequest({...input,uiStyle}, serverMetadata), {ok:false,body:null,code:'unsupported_style'});
  }
  assert.deepEqual(policy.prepareRequest({...input,mode:'all'}, serverMetadata), {ok:false,body:null,code:'invalid_mode'});
  assert.deepEqual(policy.prepareRequest(null, serverMetadata), {ok:false,body:null,code:'invalid_mode'});
});

test('sparse UUID arrays cannot leave unvalidated holes in a request body', () => {
  const ids = [sessionIds[0],,sessionIds[1]];
  assert.deepEqual(policy.prepareRequest({mode:'explicit',sessionIds:ids,uiStyle:'plain'}, serverMetadata), {
    ok:false,body:null,code:'invalid_session_ids',
  });
  assert.deepEqual(policy.prepareRequest({mode:'all-except',elderId:'elder',excludeSessionIds:ids,uiStyle:'plain'}, serverMetadata), {
    ok:false,body:null,code:'invalid_exclude_session_ids',
  });
});
