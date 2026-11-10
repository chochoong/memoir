'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const modulePath = path.join(__dirname, 'service-contract.js');
const contract = fs.existsSync(modulePath) ? require(modulePath) : {};

function readyResult() {
  return {
    status:'ready', style:'spoken', title:'살아온 이야기',
    chapters:[
      {no:1,title:'고향',status:'ready',paragraphs:[
        {sentences:[{text:'강가에서 자랐다.',turns:[1]},{text:'봄이면 꽃이 폈다.',turns:[2,3]}]},
        {sentences:[{text:'그때를 돌아본다.',turns:[]}]},
      ]},
      {no:2,title:'첫 직장',status:'ready',paragraphs:[
        {sentences:[{text:'기차를 타고 떠났다.',turns:[4]}]},
      ]},
    ],
    body:'강가에서 자랐다.\n봄이면 꽃이 폈다.\n그때를 돌아본다.\n기차를 타고 떠났다.',
    sources:[{sentence:0,turns:[1]},{sentence:1,turns:[2,3]},{sentence:2,turns:[]},{sentence:3,turns:[4]}],
    verification:{state:'passed',notes:['원문 검증']}, to_confirm:[],
    run:{session_ids:['session-a','session-b'],chapters_requested:2},
  };
}

test('postcard text and server identifiers stay separate from presentation choices', () => {
  assert.equal(typeof contract.postcardView, 'function');
  const session = {session_id:'session-a',elder_id:'elder-a',created_at:'2026-10-01T01:00:00Z'};
  const card = {title:'강가의 봄',text:'엽서의 본문',created_at:'2026-10-02T01:00:00Z',style:'spoken'};
  const presentation = {id:7,category:'어린 시절',icon:'flower',date:'2026.10.02',description:'표지 설명'};
  const view = contract.postcardView(session, card, presentation);
  assert.equal(view.id, 7);
  assert.equal(view.body, '엽서의 본문');
  assert.equal(view.title, '강가의 봄');
  assert.equal(view.session_id, 'session-a');
  assert.equal(view.elder_id, 'elder-a');
  assert.equal(view.created_at, '2026-10-02T01:00:00Z');
  assert.equal(view.date, '2026.10.02');
  assert.deepEqual(view.presentation, presentation);
  assert.deepEqual(view.sourceSession, session);
  assert.deepEqual(view.sourcePostcard, card);
  assert.equal(contract.postcardView(session, card).id, 'session-a');
  view.sourceSession.elder_id = 'changed';
  view.sourcePostcard.text = 'changed';
  view.presentation.category = 'changed';
  assert.equal(session.elder_id, 'elder-a');
  assert.equal(card.text, '엽서의 본문');
  assert.equal(presentation.category, '어린 시절');
});

test('postcard adaptation cannot invent missing server facts or accept nontext content', () => {
  assert.equal(typeof contract.postcardView, 'function');
  const view = contract.postcardView({session_id:'s',elder_id:null}, {title:'제목',text:'본문'});
  assert.equal(view.elder_id, null);
  assert.equal(view.created_at, undefined);
  assert.equal(view.date, undefined);
  assert.throws(() => contract.postcardView({}, {text:'본문'}), TypeError);
  assert.throws(() => contract.postcardView({session_id:'s'}, {text:{body:'잘못된 본문'}}), TypeError);
});

test('legacy postcards display the available session title and retain the original creation timestamp', () => {
  const session = {session_id:'legacy-session',postcard_title:null,title:'어머니의 고향 이야기',created_at:'2026-09-01T01:00:00Z'};
  const postcard = {text:'오래된 엽서 본문'};
  const view = contract.postcardView(session, postcard);
  assert.equal(view.title, '어머니의 고향 이야기');
  assert.equal(view.created_at, '2026-09-01T01:00:00Z');
  assert.deepEqual(view.sourceSession, session);
  assert.deepEqual(view.sourcePostcard, postcard);
  assert.equal(Object.hasOwn(postcard, 'title'), false);
  assert.equal(Object.hasOwn(postcard, 'created_at'), false);
});

test('postcard display title follows current title, saved postcard title, session title, then neutral copy', () => {
  const session = {session_id:'s',postcard_title:'저장된 엽서 제목',title:'인터뷰 제목',created_at:'session-time'};
  assert.equal(contract.postcardView(session, {title:'새 엽서 제목',text:'본문'}).title, '새 엽서 제목');
  for (const title of [undefined,null,'','  ']) {
    assert.equal(contract.postcardView(session, {title,text:'본문'}).title, '저장된 엽서 제목');
  }
  assert.equal(contract.postcardView({...session,postcard_title:''}, {text:'본문'}).title, '인터뷰 제목');
  const neutral = contract.postcardView({session_id:'s',postcard_title:null,title:' '}, {text:'본문'});
  assert.equal(neutral.title, '제목 없는 이야기');
  assert.equal(neutral.sourcePostcard.title, undefined);
});

test('postcard timestamp falls back to the session timestamp only when absent or null', () => {
  const session = {session_id:'s',created_at:'session-time'};
  assert.equal(contract.postcardView(session, {text:'본문'}).created_at, 'session-time');
  assert.equal(contract.postcardView(session, {text:'본문',created_at:'postcard-time'}).created_at, 'postcard-time');
  assert.equal(contract.postcardView(session, {text:'본문',created_at:null}).created_at, 'session-time');
});

test('chapter paragraphs retain titles and sentence turns while producing readable paragraph text', () => {
  assert.equal(typeof contract.memoirView, 'function');
  const result = readyResult();
  const document = contract.memoirView(result, {elder_id:'elder-a',job_id:'job-a',uiStyle:'natural',preview:true});
  assert.deepEqual(document.body, ['강가에서 자랐다. 봄이면 꽃이 폈다.','그때를 돌아본다.','기차를 타고 떠났다.']);
  assert.deepEqual(document.sections, [
    {text:'강가에서 자랐다. 봄이면 꽃이 폈다.',chapterTitle:'고향',chapterNo:1,paragraphIndex:0,sentences:[{text:'강가에서 자랐다.',turns:[1]},{text:'봄이면 꽃이 폈다.',turns:[2,3]}]},
    {text:'그때를 돌아본다.',chapterTitle:'고향',chapterNo:1,paragraphIndex:1,sentences:[{text:'그때를 돌아본다.',turns:[]}]},
    {text:'기차를 타고 떠났다.',chapterTitle:'첫 직장',chapterNo:2,paragraphIndex:0,sentences:[{text:'기차를 타고 떠났다.',turns:[4]}]},
  ]);
  assert.equal(document.title, '살아온 이야기');
  assert.equal(document.canRead, true);
  assert.equal(document.elder_id, 'elder-a');
  assert.equal(document.job_id, 'job-a');
  assert.equal(document.uiStyle, 'natural');
  assert.equal(document.style, 'spoken');
  assert.equal(document.preview, true);
  assert.equal(document.storage, 'tab-memory');
  assert.equal(document.edited, false);
  assert.equal(document.sourceAlignment, 'original');
  assert.deepEqual(document.sources, result.sources);
  assert.deepEqual(document.sourceResult, result);
  assert.deepEqual(document.verification, {state:'passed',notes:['원문 검증']});
  assert.equal(Object.hasOwn(document, 'book_id'), false);
});

test('adapted document, source snapshot, context and caller result do not share mutable arrays', () => {
  assert.equal(typeof contract.memoirView, 'function');
  const result = readyResult();
  const original = structuredClone(result);
  const document = contract.memoirView(result);
  document.sections[0].sentences[0].turns.push(99);
  document.sources[0].turns.push(98);
  document.verification.notes.push('changed');
  assert.deepEqual(result, original);
  assert.deepEqual(document.sourceResult, original);
  document.sourceResult.chapters[0].paragraphs[0].sentences[0].text = 'changed';
  assert.equal(result.chapters[0].paragraphs[0].sentences[0].text, '강가에서 자랐다.');
});

test('legacy body lines become paragraphs without manufacturing sentence provenance', () => {
  assert.equal(typeof contract.memoirView, 'function');
  const result = {status:'ready',title:'오래된 결과',body:' 첫 문단 \r\n\n 두 번째 문단\n',sources:[{sentence:0,turns:[8]}]};
  const document = contract.memoirView(result);
  assert.deepEqual(document.body, [' 첫 문단 ',' 두 번째 문단']);
  assert.deepEqual(document.sections, [
    {text:' 첫 문단 ',chapterTitle:null,chapterNo:null,paragraphIndex:0,sentences:[{text:' 첫 문단 ',turns:[]}]},
    {text:' 두 번째 문단',chapterTitle:null,chapterNo:null,paragraphIndex:1,sentences:[{text:' 두 번째 문단',turns:[]}]},
  ]);
  assert.deepEqual(document.sources, [{sentence:0,turns:[8]}]);
  assert.deepEqual(document.verification, {state:'not_run'});
  assert.equal(document.canRead, true);
});

test('generation completion never upgrades failed, not-run or absent model verification', () => {
  assert.equal(typeof contract.memoirView, 'function');
  for (const state of ['failed','not_run','needs_review']) {
    const result = readyResult();
    result.verification = {state};
    const document = contract.memoirView(result);
    assert.equal(document.canRead, true);
    assert.equal(document.verification.state, state);
    assert.equal(document.approved, undefined);
  }
  const result = readyResult();
  delete result.verification;
  assert.equal(contract.memoirView(result).verification.state, 'not_run');
});

test('valid insufficient or partial results cannot open as complete books', () => {
  assert.equal(typeof contract.memoirView, 'function');
  const insufficient = contract.memoirView({status:'insufficient_material',title:'',body:'',chapters:[],sources:[],run:{session_ids:[]}});
  assert.equal(insufficient.canRead, false);
  assert.deepEqual(insufficient.body, []);
  for (const status of ['partial','incomplete','failed','needs_context','needs_confirmation']) {
    const result = readyResult();
    result.status = status;
    assert.equal(contract.memoirView(result).canRead, false, status);
  }
  const failedChapter = readyResult();
  failedChapter.chapters[1].status = 'failed';
  assert.equal(contract.memoirView(failedChapter).canRead, false);
});

test('malformed or sparse nested results cannot silently lose content and become readable', () => {
  assert.equal(typeof contract.memoirView, 'function');
  const variants = [
    null, {}, {status:'ready',title:'제목',body:''}, {status:'ready',title:'제목',body:42},
    {status:'ready',title:'제목',chapters:[],body:'fallback text'},
    {status:'ready',title:'제목',chapters:[null]},
    {status:'ready',title:'제목',chapters:new Array(1)},
  ];
  const mutate = [
    r => { r.chapters[0].paragraphs = [null]; },
    r => { r.chapters[0].paragraphs = new Array(1); },
    r => { r.chapters[0].paragraphs[0].sentences = [null]; },
    r => { r.chapters[0].paragraphs[0].sentences = new Array(1); },
    r => { r.chapters[0].paragraphs[0].sentences[0].text = ''; },
    r => { r.chapters[0].paragraphs[0].sentences[0].turns = '1'; },
    r => { r.sources = [null]; },
    r => { r.title = {}; },
    r => { r.chapters[0].title = null; },
    r => { r.chapters[0].no = 'first'; },
  ];
  mutate.forEach(change => {const r = readyResult(); change(r); variants.push(r);});
  for (const result of variants) assert.throws(() => contract.memoirView(result), TypeError);
});

test('an actual edit invalidates displayed provenance while preserving the original server result', () => {
  assert.equal(typeof contract.editMemoir, 'function');
  const document = contract.memoirView(readyResult(), {elder_id:'elder-a',job_id:'job-a',preview:true});
  const before = structuredClone(document);
  const edited = contract.editMemoir(document, {title:'내가 고친 제목',body:['새로운 첫 문단','새로운 둘째 문단']});
  assert.deepEqual(document, before);
  assert.deepEqual(edited.sourceResult, before.sourceResult);
  assert.equal(edited.title, '내가 고친 제목');
  assert.deepEqual(edited.body, ['새로운 첫 문단','새로운 둘째 문단']);
  assert.equal(edited.edited, true);
  assert.equal(edited.sourceAlignment, 'stale');
  assert.deepEqual(edited.verification, {state:'not_run'});
  assert.deepEqual(edited.sources, []);
  assert.equal(edited.sections.length, 2);
  assert.ok(edited.sections.every(section => section.sentences.every(sentence => sentence.turns.length === 0)));
  assert.ok(edited.sections.every(section => section.chapterTitle === null && section.chapterNo === null));
  assert.equal(edited.elder_id, 'elder-a');
  assert.equal(edited.job_id, 'job-a');
  edited.sourceResult.sources[0].turns.push(88);
  assert.deepEqual(document.sourceResult.sources[0].turns, [1]);
});

test('title-only edits invalidate verification and unchanged submissions preserve alignment', () => {
  assert.equal(typeof contract.editMemoir, 'function');
  const document = contract.memoirView(readyResult());
  const unchanged = contract.editMemoir(document, {title:document.title,body:document.body.slice()});
  assert.deepEqual(unchanged, document);
  assert.equal(unchanged.sourceAlignment, 'original');
  const edited = contract.editMemoir(document, {title:'수정 제목',body:document.body});
  assert.equal(edited.verification.state, 'not_run');
  assert.deepEqual(edited.sources, []);
  assert.ok(edited.sections.every(section => section.sentences.every(sentence => sentence.turns.length === 0)));
});

test('edited textarea content normalizes paragraphs but cannot make a nonready result readable', () => {
  assert.equal(typeof contract.editMemoir, 'function');
  const document = contract.memoirView(readyResult());
  const edited = contract.editMemoir(document, {title:'제목',body:' 첫 문단\n\n둘째 문단 '});
  assert.deepEqual(edited.body, [' 첫 문단','둘째 문단 ']);
  const empty = contract.editMemoir(document, {title:'제목',body:[]});
  assert.equal(empty.canRead, false);
  const restored = contract.editMemoir(empty, {title:'제목',body:['복구한 문단']});
  assert.equal(restored.canRead, true);
  assert.equal(restored.sourceAlignment, 'stale');
  assert.equal(restored.verification.state, 'not_run');
  const result = readyResult();
  result.status = 'partial';
  assert.equal(contract.editMemoir(contract.memoirView(result), {title:'제목',body:['새 글']}).canRead, false);
  assert.throws(() => contract.editMemoir(document, {title:'제목',body:[{}]}), TypeError);
});

test('running jobs expose progress and never expose their incidental result as a finished document', () => {
  assert.equal(typeof contract.jobView, 'function');
  const response = {job_id:'job-a',status:'running',stage:'chapter',chapter:1,chapters:2,elapsed:4.5,run:{session_ids:['s']},result:readyResult()};
  const job = contract.jobView(response);
  assert.equal(job.status, 'running');
  assert.equal(job.job_id, 'job-a');
  assert.equal(job.stage, 'chapter');
  assert.equal(job.chapter, 1);
  assert.equal(job.chapters, 2);
  assert.equal(job.elapsed, 4.5);
  assert.equal(job.canRead, false);
  assert.equal(job.document, null);
  job.run.session_ids.push('changed');
  assert.deepEqual(response.run.session_ids, ['s']);
});

test('done jobs expose an adapted document with temporary job identity and speaker context', () => {
  assert.equal(typeof contract.jobView, 'function');
  const result = readyResult();
  const job = contract.jobView({job_id:'job-a',status:'done',result}, {job_id:'stale-job',elder_id:'elder-a',uiStyle:'natural',preview:true});
  assert.equal(job.status, 'done');
  assert.equal(job.canRead, true);
  assert.equal(job.document.job_id, 'job-a');
  assert.equal(job.document.elder_id, 'elder-a');
  assert.equal(job.document.uiStyle, 'natural');
  assert.deepEqual(job.document.sourceResult, result);
  assert.deepEqual(job.result, result);
  assert.equal(job.document.book_id, undefined);
  const partial = readyResult();
  partial.status = 'partial';
  assert.equal(contract.jobView({job_id:'j',status:'done',result:partial}).canRead, false);
});

test('failed jobs retain failure details and invalid done responses fail closed', () => {
  assert.equal(typeof contract.jobView, 'function');
  const failed = contract.jobView({job_id:'j',status:'failed',code:'incomplete',detail:'일부 장 실패'});
  assert.equal(failed.status, 'failed');
  assert.equal(failed.canRead, false);
  assert.equal(failed.code, 'incomplete');
  assert.equal(failed.detail, '일부 장 실패');
  assert.equal(failed.document, null);
  const invalid = [null,{}, {status:'done',job_id:'j'}, {status:'done',job_id:'j',result:null}, {status:'done',job_id:'j',result:{status:'ready',title:'제목',body:''}}, {status:'success',job_id:'j',result:readyResult()}, {status:'done',result:readyResult()}];
  for (const response of invalid) assert.throws(() => contract.jobView(response), TypeError);
});

test('the static browser can adapt a result through the same UMD interface', () => {
  assert.ok(fs.existsSync(modulePath), 'service contract module is available');
  const browser = {window:{}};
  browser.globalThis = browser.window;
  vm.runInNewContext(fs.readFileSync(modulePath, 'utf8'), browser);
  const document = browser.window.MemoirServiceContract.memoirView(readyResult());
  assert.equal(document.canRead, true);
  assert.equal(document.sections[2].chapterTitle, '첫 직장');
});
