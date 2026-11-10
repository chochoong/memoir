const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const file = path.join(__dirname, 'memoir-controller.js');
const controller = fs.existsSync(file) ? require(file) : {};

const IDS = [
  '00000000-0000-4000-8000-000000000001',
  '00000000-0000-4000-8000-000000000002',
  '00000000-0000-4000-8000-000000000003',
];
const OTHER = '00000000-0000-4000-8000-000000000004';
const JOB = '11111111111111111111111111111111';
const SECOND_JOB = '22222222222222222222222222222222';
const copy = value => JSON.parse(JSON.stringify(value));
function metadata() {
  return {
    memoir_enabled:true, memoir_engine:'single', memoir_max:5, memoir_total:3,
    sessions:IDS.map(session_id => ({session_id,elder_id:'elder-a',closed_at:'2026-11-09T00:00:00Z',has_words:true})),
  };
}
function running(ids = IDS) {
  return {job_id:JOB,status:'running',style:'spoken',stage:'analysis',chapter:0,chapters:0,elapsed:0,run:{session_ids:[...ids]}};
}
function done(ids = IDS) {
  return {job_id:JOB,status:'done',style:'spoken',elapsed:12,run:{session_ids:[...ids]},result:{
    status:'ready',title:'기억을 모은 책',body:'첫 번째 기억.\n두 번째 기억.',sources:[],to_confirm:[],style:'spoken',run:{session_ids:[...ids]},
  }};
}
function failed(code = 'invalid_model_output') {
  return {job_id:JOB,status:'failed',style:'spoken',elapsed:12,run:{session_ids:[...IDS]},code,detail:'서버 안내'};
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve=yes; reject=no;});
  return {promise,resolve,reject};
}
function setup(overrides = {}, onChange) {
  assert.equal(typeof controller.create, 'function', 'controller factory is available');
  const calls = [];
  const client = {
    async createMemoir(body) {calls.push(['create',copy(body)]); return running();},
    async getMemoir(id) {calls.push(['get',id]); return done();},
    async cancelMemoir(id) {calls.push(['cancel',id]); return failed('cancelled');},
    async latestMemoir() {throw new Error('latest must not be adopted implicitly');},
    ...overrides,
  };
  const instance = controller.create({client,onChange});
  instance.setContext({elderId:'elder-a',metadata:metadata()});
  return {instance,calls};
}
const startInput = () => ({mode:'explicit',sessionIds:[...IDS],uiStyle:'plain'});

test('starts only a policy-approved request and binds the accepted run to its elder', async () => {
  const {instance,calls}=setup();
  const state=await instance.start(startInput());
  assert.deepEqual(calls,[['create',{session_ids:IDS,style:'spoken'}]]);
  assert.equal(state.phase,'running');
  assert.equal(state.elderId,'elder-a');
  assert.equal(state.request.uiStyle,'plain');
  assert.equal(state.canRead,false);
  assert.equal(state.document,null);
  assert.equal(state.job.job_id,JOB);
});

for (const [name,change,want] of [
  ['missing metadata',context => {context.metadata=null;},'metadata_unavailable'],
  ['disabled generation',context => {context.metadata.memoir_enabled=false;},'memoir_disabled'],
  ['missing session ownership',context => {context.metadata.sessions.pop();},'session_scope_unverified'],
  ['another elder session',context => {context.metadata.sessions[0].elder_id='elder-b';},'speaker_mismatch'],
  ['an open session',context => {context.metadata.sessions[0].closed_at=null;},'session_ineligible'],
  ['a session without words',context => {context.metadata.sessions[0].has_words=false;},'session_ineligible'],
]) {
  test(`blocks ${name} before transport`, async () => {
    const {instance,calls}=setup();
    const context={elderId:'elder-a',metadata:metadata()}; change(context);
    instance.setContext(context);
    const result=await instance.start(startInput());
    assert.equal(result.phase,'blocked');
    assert.equal(result.error.code,want);
    assert.equal(result.canRead,false);
    assert.equal(calls.length,0);
  });
}

test('unsupported UI styles remain local examples and never become server styles', async () => {
  const {instance,calls}=setup();
  for (const uiStyle of ['essay','poetic','warm','spoken','unknown']) {
    const result=await instance.start({...startInput(),uiStyle});
    assert.equal(result.error.code,'unsupported_style');
  }
  assert.equal(calls.length,0);
});

test('copies caller selection, metadata, snapshots and events instead of sharing mutable state', async () => {
  const pending=deferred(),events=[];
  const {instance}=setup({createMemoir:() => pending.promise}, state => {
    events.push(state);
    if(state.request)state.request.uiStyle='tampered-event';
  });
  const context={elderId:'elder-a',metadata:metadata()};
  instance.setContext(context);
  context.metadata.sessions[0].elder_id='elder-b';
  const input=startInput();
  const operation=instance.start(input);
  input.sessionIds[0]=OTHER; input.uiStyle='essay';
  pending.resolve(running()); await operation;
  const exposed=instance.getState(); exposed.request.sessionIds.length=0; exposed.job.run.session_ids.length=0;
  assert.equal(instance.getState().request.uiStyle,'plain');
  assert.deepEqual(instance.getState().request.sessionIds,IDS);
  assert.deepEqual(instance.getState().job.run.session_ids,IDS);
  assert.ok(events.some(state => state.phase==='submitting'));
});

test('refresh explicitly opens only a complete result for the captured run', async () => {
  const {instance,calls}=setup(); await instance.start(startInput());
  assert.equal(calls.length,1,'no automatic poll');
  const state=await instance.refresh();
  assert.deepEqual(calls[1],['get',JOB]);
  assert.equal(state.phase,'done'); assert.equal(state.canRead,true);
  assert.equal(state.document.elder_id,'elder-a');
  assert.equal(state.document.job_id,JOB);
  assert.equal(state.document.uiStyle,'plain');
  assert.deepEqual(state.document.body,['첫 번째 기억.','두 번째 기억.']);
});

test('all-except accepts server-derived unseen sessions but rejects exclusions in its accepted run', async () => {
  const actual=[...IDS,OTHER];
  const {instance,calls}=setup({async createMemoir(body) {calls.push(['create',copy(body)]); return running(actual);},async getMemoir() {return done(actual);}});
  const limits={...metadata(),memoir_engine:'pipeline',memoir_max:null,memoir_total:104,sessions:[]};
  instance.setContext({elderId:'elder-a',metadata:limits});
  const state=await instance.start({mode:'all-except',excludeSessionIds:[],uiStyle:'plain'});
  assert.equal(state.phase,'running');
  assert.deepEqual(calls[0],['create',{elder_id:'elder-a',exclude_session_ids:[],style:'spoken'}]);
  assert.equal((await instance.refresh()).canRead,true);
  instance.reset();
  const excluded=await instance.start({mode:'all-except',excludeSessionIds:[OTHER],uiStyle:'plain'});
  assert.equal(excluded.canRead,false); assert.equal(excluded.error.code,'job_scope_mismatch');
});

for (const [name,mutate] of [
  ['another job',raw => {raw.job_id=SECOND_JOB;}],
  ['a changed run',raw => {raw.run.session_ids[0]=OTHER;}],
  ['a mismatched result run',raw => {raw.result.run.session_ids[0]=OTHER;}],
  ['a missing result run',raw => {delete raw.result.run;}],
  ['an unsupported response style',raw => {raw.style='essay';}],
  ['an explicitly mismatched elder',raw => {raw.elder_id='elder-b';}],
]) {
  test(`does not expose a document after ${name}`, async () => {
    const raw=done(); mutate(raw);
    const {instance}=setup({async getMemoir() {return raw;}}); await instance.start(startInput());
    const state=await instance.refresh();
    assert.equal(state.phase,'error'); assert.equal(state.canRead,false); assert.equal(state.document,null);
  });
}

test('invalid, partial, insufficient and cancelled results never become readable books', async () => {
  const responses=[
    {...done(),result:{status:'ready',title:'',body:'',style:'spoken',run:{session_ids:IDS}}},
    {...done(),result:{...done().result,status:'partial'}},
    {...done(),result:{status:'insufficient_material',title:'',body:'',style:'spoken',sources:[],to_confirm:[],run:{session_ids:IDS}}},
    failed('cancelled'),
    failed('incomplete'),
  ];
  for (const raw of responses) {
    const {instance}=setup({async getMemoir() {return raw;}}); await instance.start(startInput());
    const state=await instance.refresh();
    assert.equal(state.canRead,false); assert.equal(state.document,null);
    assert.notEqual(state.phase,'done');
  }
});

test('busy preserves only an unverified pointer and never fetches or cancels another job', async () => {
  const {instance,calls}=setup({async createMemoir() {throw {status:409,code:'busy',job_id:SECOND_JOB,detail:'다른 작업 진행 중'};}});
  const state=await instance.start(startInput());
  assert.equal(state.phase,'busy'); assert.equal(state.existingJobId,SECOND_JOB);
  assert.equal(state.canRead,false); assert.equal(state.job,null); assert.equal(state.document,null);
  await instance.refresh(); await instance.cancel();
  assert.equal(calls.length,0);
});

test('switching elders and resetting invalidate late starts and late refreshes', async () => {
  const first=deferred();
  const {instance}=setup({createMemoir:() => first.promise});
  const starting=instance.start(startInput());
  instance.setContext({elderId:'elder-b',metadata:metadata()});
  first.resolve(running()); await starting;
  assert.equal(instance.getState().elderId,'elder-b'); assert.equal(instance.getState().phase,'idle');
  assert.equal(instance.getState().job,null);
  const response=deferred();
  const another=setup({getMemoir:() => response.promise}).instance;
  await another.start(startInput()); const refreshing=another.refresh(); another.reset();
  response.resolve(done()); await refreshing;
  assert.equal(another.getState().phase,'idle'); assert.equal(another.getState().document,null);
});

test('401 clears a completed or pending document and invalidates context metadata', async () => {
  const {instance}=setup({async cancelMemoir() {throw {status:401,code:'unauthorized',detail:'로그인 필요'};}});
  await instance.start(startInput());
  const state=await instance.cancel();
  assert.equal(state.phase,'error'); assert.equal(state.error.status,401);
  assert.equal(state.request,null); assert.equal(state.job,null); assert.equal(state.document,null);
  assert.equal((await instance.start(startInput())).error.code,'metadata_unavailable');
});

test('job 404 is expiration, without adopting latest or retrying generation', async () => {
  const {instance,calls}=setup({async getMemoir() {calls.push(['get',JOB]); throw {status:404,code:'job_not_found',detail:'다시 만들어 주세요'};}});
  await instance.start(startInput()); const state=await instance.refresh();
  assert.equal(state.phase,'expired'); assert.equal(state.error.code,'job_not_found');
  assert.equal(state.canRead,false); assert.equal(state.document,null); assert.equal(state.job,null);
  await instance.refresh(); await instance.cancel();
  assert.deepEqual(calls.map(call => call[0]),['create','get']);
});

test('deduplicates starts and cancellation while a cancel response wins an older refresh', async () => {
  const creation=deferred(),refresh=deferred(),cancellation=deferred();
  let creates=0,gets=0,cancels=0;
  const {instance}=setup({
    createMemoir() {creates+=1; return creation.promise;},
    getMemoir() {gets+=1; return refresh.promise;},
    cancelMemoir() {cancels+=1; return cancellation.promise;},
  });
  const starting=instance.start(startInput()); await instance.start(startInput());
  assert.equal(creates,1); creation.resolve(running()); await starting;
  const refreshing=instance.refresh(); await instance.refresh();
  assert.equal(gets,1);
  const cancelling=instance.cancel(); await instance.cancel();
  assert.equal(cancels,1);
  cancellation.resolve(failed('cancelled')); await cancelling;
  refresh.resolve(done()); await refreshing;
  assert.equal(instance.getState().phase,'cancelled'); assert.equal(instance.getState().document,null);
});

test('cancelling before a job id only abandons tracking and suppresses the late create response', async () => {
  const pending=deferred(); let deletes=0;
  const {instance}=setup({createMemoir:() => pending.promise,async cancelMemoir() {deletes+=1; return failed('cancelled');}});
  const starting=instance.start(startInput());
  const stopped=await instance.cancel();
  assert.equal(stopped.error.code,'submission_abandoned'); assert.equal(deletes,0);
  pending.resolve(running()); await starting;
  assert.equal(instance.getState().job,null); assert.equal(instance.getState().canRead,false);
});

test('passes a live scope predicate to transport before authentication callbacks can run', async () => {
  const creating=deferred(),reading=deferred(),deleting=deferred();
  const options={};
  const {instance}=setup({
    createMemoir(body, requestOptions) {options.create=requestOptions; return creating.promise;},
    getMemoir(id, requestOptions) {options.get=requestOptions; return reading.promise;},
    cancelMemoir(id, requestOptions) {options.cancel=requestOptions; return deleting.promise;},
  });
  const starting=instance.start(startInput());
  assert.equal(typeof options.create?.isCurrent,'function');
  assert.equal(options.create.isCurrent(),true);
  creating.resolve(running()); await starting;
  const refreshing=instance.refresh();
  assert.equal(options.create.isCurrent(),false);
  assert.equal(options.get.isCurrent(),true);
  const cancelling=instance.cancel();
  assert.equal(options.get.isCurrent(),false);
  assert.equal(options.cancel.isCurrent(),true);
  instance.setContext({elderId:'elder-b',metadata:metadata()});
  assert.equal(options.cancel.isCurrent(),false);
  reading.reject({status:401,kind:'http',code:'unauthorized'});
  deleting.reject({status:401,kind:'http',code:'unauthorized'});
  await Promise.all([refreshing,cancelling]);
  assert.equal(instance.getState().elderId,'elder-b');
  assert.equal(instance.getState().phase,'idle');
  assert.equal(instance.getState().error,null);
});

test('a body-read abort carrying HTTP 401 does not clear authentication context', async () => {
  const {instance}=setup({async getMemoir() {throw {status:401,kind:'abort',code:'aborted'};}});
  await instance.start(startInput());
  const state=await instance.refresh();
  assert.equal(state.phase,'error');
  assert.equal(state.error.kind,'abort');
  assert.equal(state.job?.job_id,JOB);
  instance.reset();
  assert.equal((await instance.start(startInput())).phase,'running','metadata remains usable after an abort');
});
