'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {create:createClient}=require('./server-client.js');
const {create:createController}=require('./memoir-controller.js');
const sessionIds=[1,2,3].map(n=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`);
const jobId='a'.repeat(32);
const metadata={memoir_engine:'single',memoir_max:5,memoir_enabled:true,memoir_max_chars:30000,memoir_total:3,
  sessions:sessionIds.map((id,i)=>({session_id:id,elder_id:'elder-real',created_at:`2026-10-0${i+1}T01:00:00Z`,closed_at:`2026-10-0${i+1}T02:00:00Z`,has_words:true}))};
const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
const envelope=(extra={})=>({job_id:jobId,status:'running',style:'spoken',run:{session_ids:sessionIds},elapsed:0,stage:'analysis',chapter:null,chapters:null,...extra});

test('real client and controller preserve selected UUIDs, server chapter order and provenance through the job lifecycle',async()=>{
  const calls=[];
  const fetch=async(route,init)=>{
    calls.push({route,init});
    assert.equal(init.credentials,'include');
    if(calls.length===1){
      assert.equal(route,'/api/sessions?limit=100&elder_id=elder-real');
      return json(metadata);
    }
    if(calls.length===2){
      assert.equal(route,'/api/memoirs');
      assert.equal(init.method,'POST');
      assert.deepEqual(JSON.parse(init.body),{session_ids:[sessionIds[2],sessionIds[0],sessionIds[1]],style:'spoken'});
      return json(envelope(),202);
    }
    assert.equal(route,`/api/memoirs/${jobId}`);
    assert.equal(init.method,'GET');
    assert.equal(init.body,undefined);
    return json(envelope({status:'done',stage:'complete',result:{status:'ready',title:'서버에서 온 책',style:'spoken',
      chapters:[{no:1,title:'먼저 나눈 기억',status:'ready',paragraphs:[{sentences:[{text:'서버가 정한 첫 문장',turns:[1]}]}]},
        {no:2,title:'그 다음 기억',status:'ready',paragraphs:[{sentences:[{text:'서버가 정한 둘째 문장',turns:[4]}]}]}],
      sources:[{sentence:0,turns:[1]},{sentence:1,turns:[4]}],verification:{state:'not_run'},run:{session_ids:sessionIds,chapters_requested:2}}}));
  };
  const client=createClient({fetch});
  const controller=createController({client});
  controller.setContext({elderId:'elder-real',metadata:await client.listSessions({elderId:'elder-real'})});
  await controller.start({mode:'explicit',sessionIds:[sessionIds[2],sessionIds[0],sessionIds[1]],uiStyle:'plain'});
  assert.equal(controller.getState().phase,'running');
  const done=await controller.refresh();
  assert.equal(done.canRead,true);
  assert.equal(done.document.elder_id,'elder-real');
  assert.deepEqual(done.document.body,['서버가 정한 첫 문장','서버가 정한 둘째 문장']);
  assert.deepEqual(done.document.sections.map(s=>s.chapterTitle),['먼저 나눈 기억','그 다음 기억']);
  assert.deepEqual(done.document.sourceResult.sources,[{sentence:0,turns:[1]},{sentence:1,turns:[4]}]);
  assert.equal(done.document.verification.state,'not_run');
  assert.equal(done.document.preview,false);
  assert.equal(done.document.storage,'tab-memory');
  assert.equal(calls.length,3);
});

test('pipeline explicit limits and unsupported styles stop before fetch while a deliberate all-except request uses the existing route',async()=>{
  const bodies=[];
  const client=createClient({fetch:async(route,init)=>{
    assert.equal(route,'/api/memoirs');
    bodies.push(JSON.parse(init.body));
    return json(envelope(),202);
  }});
  const controller=createController({client});
  controller.setContext({elderId:'elder-real',metadata:{...metadata,memoir_engine:'pipeline',memoir_max:null}});
  assert.equal((await controller.start({mode:'explicit',sessionIds,uiStyle:'plain'})).error.code,'explicit_limit_unknown');
  assert.equal((await controller.start({mode:'all-except',excludeSessionIds:[],uiStyle:'essay'})).error.code,'unsupported_style');
  assert.equal(bodies.length,0);
  assert.equal((await controller.start({mode:'all-except',excludeSessionIds:[],uiStyle:'plain'})).phase,'running');
  assert.deepEqual(bodies,[{elder_id:'elder-real',exclude_session_ids:[],style:'spoken'}]);
});

test('an account-wide busy response stays unassigned and never triggers latest or opens a document',async()=>{
  const routes=[];
  const client=createClient({fetch:async(route)=>{
    routes.push(route);
    return json({detail:'이미 자서전을 엮고 있습니다',code:'busy',job_id:'b'.repeat(32)},409);
  }});
  const controller=createController({client});
  controller.setContext({elderId:'elder-real',metadata});
  const state=await controller.start({mode:'explicit',sessionIds,uiStyle:'plain'});
  assert.equal(state.phase,'busy');
  assert.equal(state.existingJobId,'b'.repeat(32));
  assert.equal(state.scope,'unverified');
  assert.equal(state.document,null);
  assert.equal(state.canRead,false);
  assert.deepEqual(routes,['/api/memoirs']);
});

test('a late 401 cannot run the shared auth callback for a newly selected speaker, while a current 401 clears context',async()=>{
  let release;
  let calls=0;
  let unauthorized=0;
  let controller;
  const expired=()=>json({detail:'로그인이 필요합니다',code:'session_expired'},401);
  const client=createClient({
    fetch:async()=>++calls===1?new Promise(resolve=>{release=resolve;}):expired(),
    onUnauthorized(){unauthorized++;controller.setContext({elderId:null,metadata:null});},
  });
  controller=createController({client});
  controller.setContext({elderId:'elder-real',metadata});
  const old=controller.start({mode:'explicit',sessionIds,uiStyle:'plain'});
  controller.setContext({elderId:'elder-next',metadata:{...metadata,sessions:metadata.sessions.map(row=>({...row,elder_id:'elder-next'}))}});
  release(expired());
  await old;
  assert.equal(unauthorized,0);
  assert.equal(controller.getState().elderId,'elder-next');
  await controller.start({mode:'explicit',sessionIds,uiStyle:'plain'});
  assert.equal(unauthorized,1);
  assert.equal(controller.getState().elderId,null);
  assert.equal(controller.getState().document,null);
});
