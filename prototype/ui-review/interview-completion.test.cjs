const test = require('node:test');
const assert = require('node:assert/strict');
const {createStore} = require('./interview-completion.js');

test('a postcard preserves the interview start time even when completion and publication are later', () => {
  let clock='2026-11-09T01:00:00.000Z';
  const store=createStore({now:()=>clock});
  const interviewId=store.beginInterview();
  clock='2026-11-09T02:00:00.000Z';
  const {story}=store.completeInterview({interviewId,answers:['기억한 이야기']});
  clock='2026-11-09T03:00:00.000Z';
  const {record}=store.makePostcard(story.id,[]);
  assert.equal(story.created_at,'2026-11-09T01:00:00.000Z');
  assert.equal(record.created_at,'2026-11-09T01:00:00.000Z');
});

test('blank completion leaves the conversation available for a real answer', () => {
  const store = createStore();
  const interviewId = store.beginInterview();
  const blank = store.completeInterview({interviewId, answers:[' ', '\n'], pendingText:'\t\n'});
  assert.deepEqual(blank, {completed:false, created:false, story:null});
  assert.deepEqual(store.pendingStories(), []);
  const completed = store.completeInterview({interviewId, answers:[], pendingText:'내가 자란 동네'});
  assert.equal(completed.completed, true);
  assert.equal(completed.created, true);
});

test('completion copies submitted and pending text exactly without mutating the interview', () => {
  const store = createStore();
  const interviewId = store.beginInterview();
  const answers = ['  첫 기억\n다음 줄  ', '<script>내 이야기</script>\n\n두 번째 문단'];
  const pendingText = '  아직 남기지 않은 답변\n마지막 줄  ';
  const original = [...answers];
  const {story} = store.completeInterview({interviewId, answers, pendingText});
  assert.deepEqual(answers, original);
  assert.deepEqual(story.answers, original);
  assert.equal(story.pendingText, pendingText);
  assert.equal(story.body, [...original, pendingText].join('\n\n'));
  answers[0] = '나중에 바뀐 입력';
  answers.length = 0;
  assert.deepEqual(story.answers, original);
  assert.equal(store.getStory(story.id).body, [...original, pendingText].join('\n\n'));
  assert.ok(Object.isFrozen(story));
  assert.ok(Object.isFrozen(story.answers));
});

test('duplicate completion returns the same story even after the interview inputs are cleared', () => {
  const store = createStore();
  const interviewId = store.beginInterview();
  const first = store.completeInterview({interviewId, answers:['남긴 답변'], pendingText:'작성 중 답변'});
  const duplicate = store.completeInterview({interviewId, answers:[], pendingText:''});
  const stale = store.completeInterview({interviewId, answers:['뒤늦은 중복 입력'], pendingText:''});
  assert.equal(duplicate.completed, true);
  assert.equal(duplicate.created, false);
  assert.strictEqual(duplicate.story, first.story);
  assert.strictEqual(stale.story, first.story);
  assert.deepEqual(store.pendingStories(), [first.story]);
});

test('new conversations remain separate and whitespace-only pending text adds no paragraph', () => {
  const store = createStore();
  const firstId = store.beginInterview();
  const secondId = store.beginInterview();
  const first = store.completeInterview({interviewId:firstId, answers:['첫 이야기'], pendingText:' \n '}).story;
  const second = store.completeInterview({interviewId:secondId, answers:[], pendingText:'다음 이야기'}).story;
  assert.notEqual(first.id, second.id);
  assert.notEqual(first.session_id, second.session_id);
  assert.equal(first.body, '첫 이야기');
  assert.equal(first.pendingText, '');
  assert.equal(second.body, '다음 이야기');
  assert.equal(store.pendingStories().length, 2);
});

test('explicit postcard creation uses max numeric record ID plus one and preserves the full body', () => {
  const store = createStore();
  const interviewId = store.beginInterview();
  const story = store.completeInterview({interviewId, answers:['  첫 답변\n그다음 줄  '], pendingText:'<b>내 말</b>'}).story;
  const records = Object.freeze([Object.freeze({id:3, body:'기존 엽서'}), Object.freeze({id:42, body:'다른 엽서'})]);
  const result = store.makePostcard(story.id, records);
  assert.equal(result.created, true);
  assert.equal(result.record.id, 43);
  assert.equal(result.record.session_id, story.session_id);
  assert.equal(result.record.body, story.body);
  assert.equal(result.story.linkedRecordId, 43);
  assert.deepEqual(records, [{id:3, body:'기존 엽서'}, {id:42, body:'다른 엽서'}]);
  assert.deepEqual(store.pendingStories(), []);
  assert.equal(store.getStory(story.id).body, story.body);
});

test('repeated postcard creation links one postcard and returns the existing postcard', () => {
  const store = createStore();
  const interviewId = store.beginInterview();
  const story = store.completeInterview({interviewId, answers:['한 번만 엽서로 만들 이야기']}).story;
  const records = [{id:9, body:'기존 기록'}];
  const first = store.makePostcard(story.id, records);
  if (first.created) records.unshift(first.record);
  const repeated = store.makePostcard(story.id, records);
  if (repeated.created) records.unshift(repeated.record);
  assert.equal(repeated.created, false);
  assert.strictEqual(repeated.record, first.record);
  assert.equal(records.length, 2);
  assert.equal(records.filter((record) => record.session_id === story.session_id).length, 1);
  assert.equal(store.getStory(story.id).linkedRecordId, first.record.id);
});

test('separate explicit creations keep unique IDs and stable conversation sessions', () => {
  const store = createStore();
  const records = [];
  for (const [index, text] of ['첫 이야기', '두 번째 이야기'].entries()) {
    const interviewId = store.beginInterview();
    const story = store.completeInterview({interviewId, pendingText:text}).story;
    assert.equal(records.length, index);
    assert.equal(store.pendingStories().length, 1);
    const result = store.makePostcard(story.id, records);
    records.unshift(result.record);
    assert.match(result.record.session_id, /^[a-f\d]{8}-[a-f\d]{4}-4[a-f\d]{3}-[89ab][a-f\d]{3}-[a-f\d]{12}$/i);
    assert.equal(result.record.body, text);
  }
  assert.deepEqual(records.map((record) => record.id), [2, 1]);
  assert.notEqual(records[0].session_id, records[1].session_id);
});

test('an unknown story cannot create a postcard', () => {
  const store = createStore();
  assert.deepEqual(store.makePostcard('missing', []), {created:false, story:null, record:null});
});
