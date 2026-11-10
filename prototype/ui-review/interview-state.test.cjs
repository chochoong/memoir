const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const file = require('node:path').join(__dirname,'interview-state.js');
const model = fs.existsSync(file) ? require(file) : {};

test('ON AIR belongs only to the user speaking turn', () => {
  assert.equal(typeof model.visualFor, 'function');
  assert.equal(model.visualFor('listening').onAir, true);
  for (const phase of ['reading','text','paused','processing','idle','unknown']) {
    assert.equal(model.visualFor(phase).onAir, false, phase);
  }
});

test('reading lights the headphones instead of the recording lamp', () => {
  assert.equal(typeof model.visualFor, 'function');
  assert.equal(model.visualFor('reading').headphones, true);
  assert.equal(model.visualFor('listening').headphones, false);
  assert.equal(model.visualFor('text').radioState, 'idle');
});

test('voice controls pause and resume without advancing the question', () => {
  assert.equal(typeof model.nextVoicePhase, 'function');
  assert.equal(model.nextVoicePhase('reading'),'listening');
  assert.equal(model.nextVoicePhase('listening'),'paused');
  assert.equal(model.nextVoicePhase('paused'),'listening');
  assert.equal(model.nextVoicePhase('processing'),'processing');
});

test('server snapshots map verified states without confusing question reading and user speech', () => {
  assert.equal(typeof model.fromSnapshot, 'function');
  for (const [state,phase,closed] of [
    ['SPEAKING','reading',false],
    ['LISTENING','listening',false],
    ['PROCESSING','processing',false],
    ['CLOSED','idle',true],
  ]) {
    assert.deepEqual(model.fromSnapshot({state,turn:3}), {phase,serverState:state,closed});
  }
});

test('unknown or absent server state never invents a listening phase', () => {
  assert.equal(typeof model.fromSnapshot, 'function');
  for (const snapshot of [undefined,null,{},'LISTENING',{state:'listening'},{state:'FUTURE'},{state:null}]) {
    assert.equal(model.fromSnapshot(snapshot), null);
  }
});

test('turn-done sends the turn confirmation endpoint without pretending to finish the session', () => {
  assert.equal(typeof model.commandFor, 'function');
  assert.deepEqual(model.commandFor('turn-done'), {supported:true,method:'POST',path:'/done',scope:'turn'});
  assert.deepEqual(model.commandFor('send-text'), {supported:true,method:'POST',path:'/speech',scope:'turn'});
  assert.deepEqual(model.commandFor('tts-done'), {supported:true,method:'POST',path:'/tts-done',scope:'turn'});
});

test('abort is a session command while pause resume and finish remain unimplemented', () => {
  assert.equal(typeof model.commandFor, 'function');
  assert.deepEqual(model.commandFor('abort'), {supported:true,method:'POST',path:'/abort',scope:'session'});
  for (const action of ['pause','resume','finish','done',null,undefined]) {
    const command = model.commandFor(action);
    assert.equal(command.supported, false, String(action));
    assert.equal(typeof command.reason, 'string');
    assert.ok(command.reason.length > 0);
    assert.equal(command.path, undefined);
    assert.equal(command.method, undefined);
  }
});

test('nonstring actions cannot coerce themselves into a supported server command', () => {
  for (const action of [['abort'],new String('turn-done'),{toString:() => 'tts-done'},Object.create(null)]) {
    assert.deepEqual(model.commandFor(action), {supported:false,reason:'unknown_action'});
  }
});
