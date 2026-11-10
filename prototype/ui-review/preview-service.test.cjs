'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const file = path.join(__dirname, 'preview-service.js');
const preview = fs.existsSync(file) ? require(file) : {};
const records = () => [1, 2, 3].map((n) => ({
  id:n, session_id:`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`,
  elder_id:'preview-self', title:`이야기 ${n}`, body:`  원문 ${n}  \n\n다음 문단 ${n}`,
  created_at:`2026-10-0${n}T01:00:00Z`,
}));

test('preview postcards pass the raw server text through the shared view adapter', () => {
  assert.equal(typeof preview.postcard, 'function');
  const session = {session_id:records()[0].session_id, elder_id:'preview-self', title:'회차 제목',
    created_at:'2026-10-28T01:00:00Z', postcard:{title:'엽서 제목', text:'  실제 필드 text  ', caption:'사진 설명', style:'spoken'}};
  const view = preview.postcard(session, {id:7,category:'family',icon:'home',date:'예시 날짜'});
  assert.equal(view.id,7);
  assert.equal(view.session_id,session.session_id);
  assert.equal(view.body,'  실제 필드 text  ');
  assert.equal(view.sourcePostcard.caption,'사진 설명');
  assert.equal(view.sourceSession.category,undefined);
});

test('the preview job keeps click-time records and speaker when inputs later change', () => {
  assert.equal(typeof preview.createMemoirJob,'function');
  const input=records(), context={elder_id:'preview-self',title:'원래 제목',uiStyle:'essay'};
  const running=preview.createMemoirJob(input,context);
  assert.equal(running.status,'running');
  input[0].body='나중에 바뀐 글';context.elder_id='other';context.title='다른 제목';
  const done=preview.completeMemoirJob(running);
  assert.equal(done.job_id,running.job_id);
  assert.equal(done.status,'done');
  assert.equal(done.result.title,'원래 제목');
  assert.equal(done.result.chapters[0].paragraphs[0].sentences[0].text,'  원문 1  ');
  assert.deepEqual(done.result.run.session_ids,records().map(r=>r.session_id));
  assert.equal(done.result.verification.state,'not_run');
  assert.equal(done.result.style,'spoken');
  assert.deepEqual(done.result.sources,[]);
  done.result.title='외부 변경';
  assert.equal(preview.completeMemoirJob(running).result.title,'원래 제목');
});

test('preview requests reject mixed speakers and missing source sessions before creating a job', () => {
  assert.equal(typeof preview.createMemoirJob,'function');
  const mixed=records();mixed[1].elder_id='other';
  assert.throws(()=>preview.createMemoirJob(mixed,{elder_id:'preview-self'}),/speaker/);
  const missing=records();missing[0].session_id='';
  assert.throws(()=>preview.createMemoirJob(missing,{elder_id:'preview-self'}),/session/);
  assert.throws(()=>preview.completeMemoirJob({job_id:'not-a-preview-job'}),/job/);
});

test('preview chapters follow session creation time rather than clicks or postcard publication time', () => {
  const input=records();
  input[0].sourceSession={created_at:'2026-10-03T01:00:00Z'};
  input[1].sourceSession={created_at:'2026-10-01T01:00:00Z'};
  input[2].sourceSession={created_at:'2026-10-02T01:00:00Z'};
  const job=preview.createMemoirJob([input[2],input[0],input[1]],{elder_id:'preview-self'});
  const result=preview.completeMemoirJob(job).result;
  assert.deepEqual(result.chapters.map(ch=>ch.title),['이야기 2','이야기 3','이야기 1']);
  assert.deepEqual(result.run.session_ids,[input[1].session_id,input[2].session_id,input[0].session_id]);
});

test('a missing or ambiguous session start never fabricates an order for the preview memoir', () => {
  const missing=records(); delete missing[0].created_at;
  assert.throws(()=>preview.createMemoirJob(missing,{elder_id:'preview-self'}),/session.*time/);
  const same=records(); same[1].created_at='2026-10-01T10:00:00+09:00';
  assert.throws(()=>preview.createMemoirJob(same,{elder_id:'preview-self'}),/session.*time/);
});

test('different microsecond timestamps remain distinct session starts', () => {
  const input=records();
  ['000300','000100','000200'].forEach((fraction,index)=>{input[index].created_at=`2026-10-01T01:00:00.${fraction}+00:00`;});
  const job=preview.createMemoirJob(input,{elder_id:'preview-self'});
  assert.deepEqual(preview.completeMemoirJob(job).result.chapters.map(ch=>ch.title),['이야기 2','이야기 3','이야기 1']);
});
