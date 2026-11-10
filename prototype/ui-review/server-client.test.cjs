const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const subjectPath = path.join(__dirname, 'server-client.js');
function subject() {
  const api = fs.existsSync(subjectPath) ? require(subjectPath) : {};
  assert.equal(typeof api.create, 'function', 'the injected server client is not implemented');
  return api;
}
const SESSION = '12345678-1234-4321-8765-123456789abc';
const SESSION2 = '87654321-1234-4321-8765-123456789abc';
const JOB = '0123456789abcdef0123456789abcdef';
const LINK = 'l_0123456789abcdef0123456789abcdef';
const ELDER = 'e_0123456789abcdef0123456789abcdef';
function json(body, status = 200) {
  return new Response(JSON.stringify(body), {status, headers:{'Content-Type':'application/json'}});
}
function fixture(respond = () => json({ok:true})) {
  const calls = [];
  const client = subject().create({fetch:async (url, init) => {
    calls.push({url,init});
    return respond(url,init);
  }});
  return {client,calls};
}

test('creating the client requires fetch injection and never reads a global fetch', () => {
  const api = subject();
  assert.throws(() => api.create(), /fetch/i);
  assert.throws(() => api.create({fetch:null}), /fetch/i);
  let calls = 0;
  api.create({fetch:() => { calls++; }});
  assert.equal(calls, 0);
});

test('browser UMD loads without reading or calling the browser fetch', () => {
  subject();
  const context = {InterviewVisualState:require('./interview-state.js')};
  Object.defineProperty(context, 'fetch', {get() { throw new Error('global fetch was read'); }});
  vm.runInNewContext(fs.readFileSync(subjectPath, 'utf8'), context);
  assert.equal(typeof context.MemoirServerClient.create, 'function');
  assert.throws(() => context.MemoirServerClient.create({}), /fetch/i);
});

test('Google credential uses the exact auth payload, cookie credentials, and raw JSON result', async () => {
  const data = {user:{user_id:'u_example',name:'가족',email:'example@invalid.test'},elders:[]};
  const {client,calls} = fixture(() => json(data));
  assert.deepEqual(await client.googleLogin('offline-example-credential'), data);
  assert.equal(calls[0].url, '/api/auth/google');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.credentials, 'include');
  assert.equal(calls[0].init.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(calls[0].init.body), {credential:'offline-example-credential'});
});

test('GET me sends no body or JSON Content-Type and forwards the abort signal', async () => {
  const {client,calls} = fixture();
  const signal = new AbortController().signal;
  await client.getMe({signal});
  assert.equal(calls[0].url, '/api/auth/me');
  assert.equal(calls[0].init.method, 'GET');
  assert.equal(calls[0].init.signal, signal);
  assert.equal(calls[0].init.body, undefined);
  assert.equal(calls[0].init.headers['Content-Type'], undefined);
});

test('logout accepts a bodyless 204 without attempting JSON parsing', async () => {
  const {client,calls} = fixture(() => new Response(null, {status:204}));
  assert.equal(await client.logout(), null);
  assert.equal(calls[0].url, '/api/auth/logout');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.body, undefined);
  assert.equal(calls[0].init.headers['Content-Type'], undefined);
});

test('elder creation sends only its name and does not turn a UI numeric id into a server id', async () => {
  const {client,calls} = fixture(() => json({elder_id:ELDER,name:'김정희'}, 201));
  assert.equal((await client.createElder({name:' 김정희 '})).elder_id, ELDER);
  assert.deepEqual(JSON.parse(calls[0].init.body), {name:'김정희'});
  assert.equal(calls[0].url, '/api/elders');
  await assert.rejects(client.createElder({name:''}), error => error.code === 'invalid_request');
  await assert.rejects(client.listSessions({elderId:7}), error => error.code === 'invalid_request');
  assert.equal(calls.length, 1);
});

test('sessions default to the full server list limit and encode filters as query values', async () => {
  const {client,calls} = fixture();
  await client.listSessions();
  assert.equal(calls[0].url, '/api/sessions?limit=100');
  await client.listSessions({limit:25,elderId:'opaque/id & value',hasPostcard:true});
  assert.equal(calls[1].url, '/api/sessions?limit=25&elder_id=opaque%2Fid+%26+value&has_postcard=true');
  for (const limit of [0,101,1.5,'20']) {
    await assert.rejects(client.listSessions({limit}), error => error.code === 'invalid_request');
  }
  assert.equal(calls.length, 2);
});

test('session creation forwards the server preparation fields without inventing a session id', async () => {
  const {client,calls} = fixture(() => json({session_id:SESSION,state:'SPEAKING',closed_session_ids:[]}));
  const body = {title:'어린 시절',seed:'가족이 적은 설명',theme:'family',topic:'고향',elder_id:ELDER};
  assert.equal((await client.createSession(body)).session_id, SESSION);
  assert.equal(calls[0].url, '/api/sessions');
  assert.deepEqual(JSON.parse(calls[0].init.body), body);
});

test('live snapshot and stored record use their distinct routes and reject UI numeric ids', async () => {
  const {client,calls} = fixture();
  await client.getSnapshot({sessionId:SESSION});
  await client.getRecord(SESSION);
  assert.equal(calls[0].url, '/api/sessions/' + SESSION);
  assert.equal(calls[1].url, '/api/sessions/' + SESSION + '/record');
  await assert.rejects(client.getRecord(3), error => error.code === 'invalid_request');
  await assert.rejects(client.getSnapshot({sessionId:'../other'}), error => error.code === 'invalid_request');
  assert.equal(calls.length, 2);
});

test('assignElder associates an existing owner session using the exact PUT contract', async () => {
  const assigned = {session_id:SESSION,elder_id:ELDER};
  const {client,calls} = fixture(() => json(assigned));
  assert.equal(typeof client.assignElder, 'function', 'assignElder is not implemented');
  const signal = new AbortController().signal;
  assert.deepEqual(await client.assignElder(SESSION, ELDER, {signal}), assigned);
  assert.equal(calls[0].url, '/api/sessions/' + SESSION + '/elder');
  assert.equal(calls[0].init.method, 'PUT');
  assert.equal(calls[0].init.credentials, 'include');
  assert.equal(calls[0].init.signal, signal);
  assert.deepEqual(JSON.parse(calls[0].init.body), {elder_id:ELDER});
});

test('assignElder preserves a server conflict and never invents a guest assignment route', async () => {
  const body = {detail:'이미 다른 분의 이야기로 정해진 기록이에요.',code:'elder_already_set'};
  const {client,calls} = fixture(() => json(body,409));
  assert.equal(typeof client.assignElder, 'function', 'assignElder is not implemented');
  await assert.rejects(client.assignElder(SESSION, ELDER), error => {
    assert.equal(error.status, 409);
    assert.equal(error.code, 'elder_already_set');
    assert.deepEqual(error.body, body);
    assert.equal(error.detail, body.detail);
    return true;
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/sessions/' + SESSION + '/elder');
});

test('assignElder rejects local numeric ids before any request', async () => {
  const {client,calls} = fixture();
  assert.equal(typeof client.assignElder, 'function', 'assignElder is not implemented');
  await assert.rejects(client.assignElder(12, ELDER), error => error.code === 'invalid_request');
  await assert.rejects(client.assignElder(SESSION, 12), error => error.code === 'invalid_request');
  assert.equal(calls.length, 0);
});

test('postcard generation is an explicit POST and its returned image URL remains raw JSON', async () => {
  const postcard = {url:'/api/sessions/' + SESSION + '/postcard?v=version',title:'고향',text:'기억',style:'spoken'};
  const {client,calls} = fixture(() => json(postcard));
  assert.deepEqual(await client.createPostcard(SESSION, {style:'spoken'}), postcard);
  assert.equal(calls[0].url, '/api/sessions/' + SESSION + '/postcard');
  assert.equal(calls[0].init.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].init.body), {style:'spoken'});
  await assert.rejects(client.createPostcard(SESSION, {style:'novel'}), error => error.code === 'unsupported_style');
  assert.equal(calls.length, 1);
});

test('memoir start sends the explicit raw mode asynchronously without enforcing UI count policy', async () => {
  const job = {job_id:JOB,status:'running',stage:'analysis',run:{session_ids:[SESSION]}};
  const {client,calls} = fixture(() => json(job, 202));
  assert.deepEqual(await client.createMemoir({session_ids:[SESSION],style:'spoken'}), job);
  assert.equal(calls[0].url, '/api/memoirs');
  assert.equal(calls[0].init.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].init.body), {session_ids:[SESSION],style:'spoken'});
});

test('memoir all-except preserves an empty exclusion array as all records for that elder', async () => {
  const {client,calls} = fixture();
  const body = {elder_id:ELDER,exclude_session_ids:[],style:'spoken'};
  await client.createMemoir(body);
  assert.deepEqual(JSON.parse(calls[0].init.body), body);
});

test('memoir validates only supported style and unambiguous server mode before fetching', async () => {
  const {client,calls} = fixture();
  for (const body of [null,[],{}, {session_ids:'bad'}, {elder_id:ELDER},
    {session_ids:[SESSION],exclude_session_ids:[],elder_id:ELDER}, {session_ids:[19]}]) {
    await assert.rejects(client.createMemoir(body), error => error.code === 'invalid_request');
  }
  await assert.rejects(client.createMemoir({session_ids:[SESSION],style:'novel'}), error => error.code === 'unsupported_style');
  assert.equal(calls.length, 0);
});

test('memoir latest, get, and cancel distinguish the 32-hex job id from a session UUID', async () => {
  const {client,calls} = fixture(() => json({job_id:JOB,status:'failed',code:'cancelled'}));
  await client.latestMemoir();
  await client.getMemoir(JOB);
  assert.equal((await client.cancelMemoir(JOB)).code, 'cancelled');
  assert.deepEqual(calls.map(call => [call.url,call.init.method]), [
    ['/api/memoirs/latest','GET'], ['/api/memoirs/' + JOB,'GET'], ['/api/memoirs/' + JOB,'DELETE'],
  ]);
  await assert.rejects(client.getMemoir(SESSION), error => error.code === 'invalid_request');
  assert.equal(calls[2].init.body, undefined);
});

test('interview commands use the existing visual contract suffixes and speech JSON only', async () => {
  const {client,calls} = fixture();
  await client.interviewCommand({sessionId:SESSION,action:'turn-done'});
  await client.interviewCommand({sessionId:SESSION,action:'tts-done'});
  await client.interviewCommand({sessionId:SESSION,action:'abort'});
  await client.interviewCommand({sessionId:SESSION,action:'send-text',text:'그때는 즐거웠어요.'});
  assert.deepEqual(calls.map(call => call.url), [
    '/api/sessions/' + SESSION + '/done','/api/sessions/' + SESSION + '/tts-done',
    '/api/sessions/' + SESSION + '/abort','/api/sessions/' + SESSION + '/speech',
  ]);
  calls.slice(0,3).forEach(call => assert.equal(call.init.body, undefined));
  assert.deepEqual(JSON.parse(calls[3].init.body), {text:'그때는 즐거웠어요.'});
});

test('guest snapshot and commands use only the cookie-scoped invitation session route', async () => {
  const {client,calls} = fixture();
  await client.getSnapshot({guest:true});
  await client.interviewCommand({guest:true,action:'send-text',text:'기억나요.'});
  assert.equal(calls[0].url, '/api/i/session');
  assert.equal(calls[1].url, '/api/i/session/speech');
  assert.equal(calls[1].init.credentials, 'include');
  assert.deepEqual(JSON.parse(calls[1].init.body), {text:'기억나요.'});
});

for (const action of ['finish','pause','resume','unknown']) {
  test('unsupported interview action ' + action + ' cannot produce any request', async () => {
    const {client,calls} = fixture();
    await assert.rejects(client.interviewCommand({sessionId:SESSION,action}), error =>
      error.code === 'unsupported_command' && error.kind === 'validation');
    assert.equal(calls.length, 0);
  });
}

test('401 preserves auth detail and invokes the injected unauthorized callback', async () => {
  const errors = [];
  const api = subject();
  const client = api.create({fetch:async () => json({detail:'로그인이 끝났어요',code:'session_expired'},401),
    onUnauthorized:error => errors.push(error)});
  await assert.rejects(client.getMe(), error => error instanceof api.ApiError &&
    error.status === 401 && error.code === 'session_expired' && error.detail === '로그인이 끝났어요');
  assert.equal(errors.length, 1);
  assert.equal(errors[0].body.code, 'session_expired');
});

test('a 401 body AbortError cannot invoke the shared unauthorized callback', async () => {
  let unauthorized = 0;
  const cause = new Error('body read cancelled');
  cause.name = 'AbortError';
  const client = subject().create({fetch:async () => ({status:401,ok:false,
    headers:new Headers({'Content-Type':'application/json'}),text:async () => { throw cause; }}),
  onUnauthorized:() => { unauthorized++; }});
  await assert.rejects(client.getMe(), error => error.status === 401 && error.code === 'aborted' &&
    error.kind === 'abort' && error.cause === cause);
  assert.equal(unauthorized, 0);
});

test('aborting during a 401 body read skips auth reset while preserving the original HTTP failure', async () => {
  let unauthorized = 0;
  let release;
  const controller = new AbortController();
  const client = subject().create({fetch:async () => ({status:401,ok:false,
    headers:new Headers({'Content-Type':'application/json'}),text:() => new Promise(resolve => { release = resolve; })}),
  onUnauthorized:() => { unauthorized++; }});
  const pending = client.getMe({signal:controller.signal});
  await Promise.resolve();
  controller.abort();
  release(JSON.stringify({detail:'로그인이 끝났어요',code:'session_expired'}));
  await assert.rejects(pending, error => error.status === 401 && error.code === 'session_expired' &&
    error.detail === '로그인이 끝났어요');
  assert.equal(unauthorized, 0);
});

test('isCurrent is checked after the 401 body resolves so a superseded request cannot reset auth', async () => {
  let unauthorized = 0;
  let release;
  let current = true;
  let checks = 0;
  const client = subject().create({fetch:async () => ({status:401,ok:false,
    headers:new Headers({'Content-Type':'application/json'}),text:() => new Promise(resolve => { release = resolve; })}),
  onUnauthorized:() => { unauthorized++; }});
  const pending = client.getMe({isCurrent:() => { checks++; return current; }});
  await Promise.resolve();
  assert.equal(checks, 0);
  current = false;
  release(JSON.stringify({detail:{message:'expired'},code:'session_expired'}));
  await assert.rejects(pending, error => error.status === 401 && error.code === 'session_expired' &&
    error.detail.message === 'expired');
  assert.equal(checks, 1);
  assert.equal(unauthorized, 0);
});

test('a throwing isCurrent predicate cannot mask the original 401 or trigger auth reset', async () => {
  let unauthorized = 0;
  const client = subject().create({fetch:async () => json({detail:'expired',code:'session_expired'},401),
    onUnauthorized:() => { unauthorized++; }});
  await assert.rejects(client.getMe({isCurrent:() => { throw new Error('scope is gone'); }}), error =>
    error.status === 401 && error.code === 'session_expired' && error.detail === 'expired');
  assert.equal(unauthorized, 0);
});

test('a current request can invoke the 401 callback and nonfunction predicates fail before transport', async () => {
  let unauthorized = 0;
  let calls = 0;
  const client = subject().create({fetch:async () => { calls++; return json({detail:'expired',code:'session_expired'},401); },
    onUnauthorized:() => { unauthorized++; }});
  await assert.rejects(client.getMe({isCurrent:() => true}), error => error.code === 'session_expired');
  assert.equal(unauthorized, 1);
  await assert.rejects(client.getMe({isCurrent:true}), error => error.code === 'invalid_request');
  assert.equal(calls, 1);
});

test('409 busy preserves the existing running job id without starting or adopting another job', async () => {
  const {client,calls} = fixture(() => json({code:'busy',detail:'만드는 중',job_id:JOB},409));
  await assert.rejects(client.createMemoir({session_ids:[SESSION,SESSION2]}), error =>
    error.status === 409 && error.code === 'busy' && error.job_id === JOB && error.body.job_id === JOB);
  assert.equal(calls.length, 1);
});

test('404 job_not_found remains a typed failure rather than an empty successful document', async () => {
  const {client} = fixture(() => json({detail:'찾을 수 없어요',code:'job_not_found'},404));
  await assert.rejects(client.latestMemoir(), error => error.status === 404 && error.code === 'job_not_found');
});

test('FastAPI nested detail objects and 422 validation arrays retain their original structure', async () => {
  const detail = [{type:'missing',loc:['body','name'],msg:'Field required',input:{}}];
  const {client} = fixture(() => json({detail},422));
  await assert.rejects(client.getMe(), error => {
    assert.equal(error.status, 422);
    assert.deepEqual(error.detail, detail);
    assert.deepEqual(error.body, {detail});
    return true;
  });
  const nested = {code:'nested_busy',message:'진행 중',job_id:JOB};
  const next = fixture(() => json({detail:nested},409)).client;
  await assert.rejects(next.getMe(), error => error.code === 'nested_busy' && error.job_id === JOB &&
    error.detail.message === '진행 중');
});

test('non-JSON HTML and malformed JSON have different typed response failures', async () => {
  const html = fixture(() => new Response('<h1>Unavailable</h1>', {status:503,headers:{'Content-Type':'text/html'}}));
  await assert.rejects(html.client.getMe(), error => error.status === 503 &&
    error.code === 'non_json_response' && error.kind === 'invalid_response' && error.body === '<h1>Unavailable</h1>');
  const malformed = fixture(() => new Response('{oops', {status:200,headers:{'Content-Type':'application/json'}}));
  await assert.rejects(malformed.client.getMe(), error => error.status === 200 &&
    error.code === 'invalid_json' && error.kind === 'invalid_response');
});

test('network failure and AbortError remain distinguishable and no request is retried', async () => {
  let calls = 0;
  const api = subject();
  const network = api.create({fetch:async () => { calls++; throw new TypeError('offline'); }});
  await assert.rejects(network.getMe(), error => error instanceof api.ApiError &&
    error.status === 0 && error.code === 'network_error' && error.kind === 'network');
  const aborted = api.create({fetch:async () => { const error = new Error('stop'); error.name = 'AbortError'; throw error; }});
  await assert.rejects(aborted.getMe(), error => error.code === 'aborted' && error.kind === 'abort');
  assert.equal(calls, 1);
});

test('an already aborted signal cannot cause a fetch side effect', async () => {
  const {client,calls} = fixture();
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(client.getMe({signal:controller.signal}), error => error.code === 'aborted');
  assert.equal(calls.length, 0);
});

test('link manager methods match the exact create/list/revoke/reissue routes', async () => {
  const {client,calls} = fixture();
  const body = {elder_id:ELDER,title:'고향',seed:'가족 설명',theme:'family',topic:'어린 시절',photo_id:null};
  await client.createLink(body);
  await client.listLinks({elderId:ELDER,limit:50});
  await client.revokeLink(LINK);
  await client.reissueLink(LINK);
  assert.deepEqual(calls.map(call => [call.url,call.init.method]), [
    ['/api/links','POST'],['/api/links?limit=50&elder_id=' + ELDER,'GET'],
    ['/api/links/' + LINK + '/revoke','POST'],['/api/links/' + LINK + '/reissue','POST'],
  ]);
  assert.deepEqual(JSON.parse(calls[0].init.body), body);
  assert.equal(calls[2].init.body, undefined);
});

test('invitation preview/start put a token only in the explicit header and preserve raw start state', async () => {
  const token = 'offline-example_link-token';
  const {client,calls} = fixture(() => json({state:'in_progress',session_id:SESSION}));
  await client.previewInvitation(token);
  assert.equal((await client.startInvitation(token, {topic:'고향'})).state, 'in_progress');
  assert.deepEqual(calls.map(call => call.url), ['/api/i/preview','/api/i/start']);
  assert.equal(calls[0].init.headers['x-interview-token'], token);
  assert.equal(calls[1].init.headers['x-interview-token'], token);
  assert.deepEqual(JSON.parse(calls[1].init.body), {topic:'고향'});
});
