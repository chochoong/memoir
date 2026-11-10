'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const contractFile=path.join(__dirname,'service-contract.js');
const contract=fs.existsSync(contractFile)?require(contractFile):{};
const sourceResult=()=>({status:'ready',title:'서버 제목',style:'spoken',
  chapters:[{no:1,title:'첫 장',status:'ready',paragraphs:[{sentences:[{text:'첫 문장',turns:[2]}]}]},
    {no:2,title:'다음 장',status:'ready',paragraphs:[{sentences:[{text:'다음 문장',turns:[5]}]}]}],
  sources:[{sentence:0,turns:[2]},{sentence:1,turns:[5]}],verification:{state:'failed'}});

function shelfFixture(document) {
  let elderId='preview-self';
  const state={title:document.title,body:[...document.body],style:'plain',draftElderId:elderId,document};
  const content={innerHTML:''},screen={querySelector:()=>content,addEventListener(){}};
  const window={MemoirReaderState:require('./ebook-state.js'),MemoirServiceContract:contract,
    matchMedia:()=>({matches:false,addEventListener(){}}),addEventListener(){}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'library-view.js'),'utf8'),{
    window,document:{querySelector:()=>screen,activeElement:null},localStorage:{getItem:()=>null},
    initialBody:['예시 글'],location:{hash:'#library'},currentElderId:()=>elderId,
    state,navigate(){},toast(){},escapeText:value=>String(value),
  });
  return {state,window,selectElder:value=>{elderId=value;},html:()=>content.innerHTML};
}

test('a saved local book reopens with its chapters, original sources and verification status',()=>{
  assert.equal(typeof contract.memoirView,'function');
  const doc=contract.memoirView(sourceResult(),{elder_id:'preview-self',job_id:'preview-job-1',uiStyle:'plain',preview:true});
  const shelf=shelfFixture(doc);
  shelf.window.MemoirLibrary.saveDraft();
  shelf.state.document=null;shelf.state.body=['다른 책'];
  shelf.window.MemoirLibrary.openBook('volume-4');
  assert.equal(shelf.state.document.sections[1].chapterTitle,'다음 장');
  assert.deepEqual(shelf.state.document.sourceResult.sources,sourceResult().sources);
  assert.equal(shelf.state.document.verification.state,'failed');
  assert.equal(shelf.state.document.job_id,'preview-job-1');
  assert.notEqual(shelf.state.document.book_id,shelf.state.document.job_id);
  shelf.state.document.sourceResult.title='외부 수정';
  shelf.window.MemoirLibrary.openBook('volume-4');
  assert.equal(shelf.state.document.sourceResult.title,'서버 제목');
});

test('edited books keep the original result but never reuse its sources as edited-text evidence',()=>{
  assert.equal(typeof contract.editMemoir,'function');
  const original=contract.memoirView(sourceResult(),{elder_id:'preview-self',uiStyle:'plain',preview:true});
  const edited=contract.editMemoir(original,{title:'고친 제목',body:['수정한 글']});
  const shelf=shelfFixture(edited);
  shelf.window.MemoirLibrary.saveDraft();shelf.state.document=null;
  shelf.window.MemoirLibrary.openBook('volume-4');
  assert.equal(shelf.state.document.sourceAlignment,'stale');
  assert.equal(shelf.state.document.verification.state,'not_run');
  assert.deepEqual(shelf.state.document.sources,[]);
  assert.equal(shelf.state.document.sourceResult.title,'서버 제목');
  shelf.selectElder('other');shelf.window.MemoirLibrary.render();
  assert.doesNotMatch(shelf.html(),/volume-4/);
});

test('the shelf refuses to save another speaker draft or a nonreadable result',()=>{
  assert.equal(typeof contract.memoirView,'function');
  const doc=contract.memoirView(sourceResult(),{elder_id:'preview-self',uiStyle:'plain'});
  const shelf=shelfFixture(doc);shelf.selectElder('other');
  shelf.window.MemoirLibrary.saveDraft();shelf.selectElder('preview-self');shelf.window.MemoirLibrary.render();
  assert.doesNotMatch(shelf.html(),/volume-4/);
  shelf.state.document={...doc,canRead:false};shelf.window.MemoirLibrary.saveDraft();
  assert.doesNotMatch(shelf.html(),/volume-4/);
});

function appFixture(){
  const nodes=new Map(),timers=[];
  function node(selector){
    if(!nodes.has(selector))nodes.set(selector,{value:'',dataset:{},hidden:false,open:false,
      classList:{add(){},remove(){},toggle(){}},setAttribute(){},focus(){},
      addEventListener(type,callback){this[type]=callback;},showModal(){this.open=true;},close(){this.open=false;}});
    return nodes.get(selector);
  }
  const window={MemoirServiceContract:contract,MemoirPreviewService:require('./preview-service.js'),
    MemoirSelectionPolicy:require('./memoir-policy.js'),InterviewCompletion:require('./interview-completion.js'),
    InterviewVisualState:require('./interview-state.js'),createRadioIllustration:()=>'',
    addEventListener(){},dispatchEvent(){},scrollTo(){}};
  const context=vm.createContext({window,document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},
    location:{hash:'#home',search:''},URLSearchParams,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},
    setTimeout:(callback,delay)=>{timers.push({callback,delay});return timers.length;},clearTimeout(){}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'app.js'),'utf8'),context);
  return {context,node,timers,run:source=>vm.runInContext(source,context)};
}

test('starting another selection preserves the current document until a new result succeeds',()=>{
  const app=appFixture();
  const before=app.run('({title:state.title,body:[...state.body],source:state.document.sourceResult})');
  app.run('startMemoirFromPostcards()');
  assert.equal(app.run('state.title'),before.title);
  assert.deepEqual(app.run('state.document.sourceResult'),before.source);
  assert.deepEqual(app.run('state.body'),before.body);
});

test('changing speakers during preview generation cannot relabel or open the captured draft',()=>{
  const app=appFixture();
  app.run('state.selected=new Set([1,2,3]);');
  app.node('#generate-draft').click();
  app.context.window.RolePreview={currentElderId:()=> 'other'};
  app.timers.find(timer=>timer.delay===850).callback();
  assert.equal(app.run('state.document.elder_id'),'preview-self');
  assert.equal(app.run('state.draftElderId'),'preview-self');
  assert.equal(app.run('state.generating'),false);
  assert.equal(app.context.location.hash,'#home');
});
