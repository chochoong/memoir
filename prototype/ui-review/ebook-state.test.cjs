'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const modulePath = path.join(__dirname, 'ebook-state.js');
const model = fs.existsSync(modulePath) ? require(modulePath) : {};

test('invalid or older saved preferences recover to readable defaults', () => {
  assert.equal(typeof model.normalizePreferences, 'function');
  assert.deepEqual(model.normalizePreferences(null), {
    fontSize: 24, lineHeight: 1.9, theme: 'white', fontFamily: 'serif', turnStyle:'slide', reduceMotion:false, fitToScreen:false,
  });
  assert.deepEqual(model.normalizePreferences({fontSize:'wrong',lineHeight:null,theme:'unknown',fontFamily:'remote-font'}), model.normalizePreferences(null));
});

test('saved preferences cannot put text size or spacing outside the controls', () => {
  assert.equal(typeof model.normalizePreferences, 'function');
  assert.deepEqual(model.normalizePreferences({fontSize:99,lineHeight:0.1,theme:'night',fontFamily:'sans'}), {
    fontSize: 32, lineHeight: 1.6, theme: 'night', fontFamily: 'sans', turnStyle:'slide', reduceMotion:false, fitToScreen:false,
  });
  assert.equal(model.normalizePreferences({fontSize:0}).fontSize, 18);
});

test('turn style is a saved reading preference and unknown styles recover quietly',()=>{
  assert.equal(model.normalizePreferences({turnStyle:'paper',reduceMotion:true}).turnStyle,'paper');
  assert.equal(model.normalizePreferences({turnStyle:'paper',reduceMotion:true}).reduceMotion,true);
  assert.equal(model.normalizePreferences({turnStyle:'scroll'}).turnStyle,'scroll');
  assert.equal(model.normalizePreferences({turnStyle:'unknown',reduceMotion:'false'}).turnStyle,'slide');
  assert.equal(model.normalizePreferences({reduceMotion:'false'}).reduceMotion,false);
});

test('screen fitting is opt-in and survives saved preference normalization',()=>{
  assert.equal(model.normalizePreferences({}).fitToScreen,false);
  assert.equal(model.normalizePreferences({fitToScreen:true}).fitToScreen,true);
  const saved=JSON.parse(JSON.stringify(model.normalizePreferences({fitToScreen:true,fontSize:28})));
  assert.equal(model.normalizePreferences(saved).fitToScreen,true);
  for(const fitToScreen of [false,'true','false',1,0,null,{},[]]){
    assert.equal(model.normalizePreferences({fitToScreen}).fitToScreen,false);
  }
});

test('a saved reading location is clamped to the current book', () => {
  assert.equal(typeof model.normalizeLocation, 'function');
  assert.deepEqual(model.normalizeLocation({section:40,offset:2},3), {section:2,offset:1});
  assert.deepEqual(model.normalizeLocation({section:-1,offset:-0.2},3), {section:0,offset:0});
  assert.deepEqual(model.normalizeLocation({section:'bad',offset:Infinity},3), {section:0,offset:0});
});

test('editing any paragraph creates a different progress key without storing the text', () => {
  assert.equal(typeof model.bookKey, 'function');
  const first=model.bookKey('나의 책',['첫 기억','둘째 기억']);
  assert.equal(first,model.bookKey('나의 책',['첫 기억','둘째 기억']));
  assert.notEqual(first,model.bookKey('나의 책',['첫 기억','바뀐 기억']));
  assert.match(first,/^book-[a-f0-9]+$/);
  assert.equal(first.includes('기억'),false);
});

test('only a valid saved text position can offer to continue reading', () => {
  const sections = ['첫 기억', '둘째 기억'];
  assert.equal(typeof model.hasResumableProgress, 'function');
  for (const location of [{section:0,offset:0}, {section:1,offset:.42}, {section:1,offset:1}]) {
    assert.equal(model.hasResumableProgress({location,atStart:false,bookmarks:[]}, sections), true);
  }
  for (const value of [null, {}, {bookmarks:[{section:1,offset:.42}]},
    {location:{section:0,offset:0},atStart:true},
    {location:{section:1,offset:.42}},
    {location:{section:1,offset:.42},atStart:'false'}]) {
    assert.equal(model.hasResumableProgress(value, sections), false);
  }
  assert.equal(model.hasResumableProgress({location:{section:0,offset:0},atStart:false}, []), false);
});

test('corrupt saved locations are rejected instead of being clamped into resume positions', () => {
  const sections = ['첫 기억', '둘째 기억'];
  assert.equal(typeof model.hasResumableProgress, 'function');
  for (const location of [null, {},
    {section:-1,offset:.4}, {section:2,offset:.4}, {section:.5,offset:.4},
    {section:'1',offset:.4}, {section:Infinity,offset:.4}, {section:NaN,offset:.4},
    {section:1,offset:-.01}, {section:1,offset:1.01}, {section:1,offset:'0.4'},
    {section:1,offset:Infinity}, {section:1,offset:NaN}]) {
    assert.equal(model.hasResumableProgress({location,atStart:false}, sections), false);
  }
});

function libraryFixture(getItem, body = ['  첫 기억  ', '   ', '둘째 기억']) {
  let selectedElderId='preview-self';
  const navigations=[];
  const content = {innerHTML:''};
  const screen = {querySelector:() => content, addEventListener() {}};
  const listeners = new Map();
  const window = {
    MemoirReaderState:model,
    MemoirServiceContract:require('./service-contract.js'),
    matchMedia:() => ({matches:false,addEventListener() {}}),
    addEventListener:(type, listener) => listeners.set(type, listener),
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'library-view.js'), 'utf8'), {
    window, document:{querySelector:() => screen, activeElement:null},
    localStorage:{getItem}, initialBody:body, location:{hash:'#library'},
    currentElderId:()=>selectedElderId,
    state:{},navigate:(screen)=>navigations.push(screen),
    escapeText:(value) => String(value),
  });
  return {
    label:() => content.innerHTML.split('<span class="ml-read-label">')[1].split(' <span')[0],
    revisit:() => listeners.get('memoir:screen')({detail:{screen:'library'}}),
    html:()=>content.innerHTML,
    selectElder:(id)=>{selectedElderId=id;window.MemoirLibrary.render();},
    openBook:(id)=>window.MemoirLibrary.openBook(id),
    navigations,
  };
}

test('bookshelf labels use the same untrimmed text key and refresh after reading', () => {
  const key = 'naemalssami.ui-review.reader.progress.v2.' + model.bookKey(
    '그 시절의 골목, 오래 남은 마음', ['  첫 기억  ', '둘째 기억']);
  let saved = null;
  const shelf = libraryFixture((requestedKey) => requestedKey === key ? saved : null);
  assert.equal(shelf.label(), '읽기');
  saved = JSON.stringify({location:{section:0,offset:0},atStart:false,bookmarks:[]});
  shelf.revisit();
  assert.equal(shelf.label(), '이어 읽기');
  const editedShelf = libraryFixture((requestedKey) => requestedKey === key ? saved : null,
    ['  첫 기억  ', '   ', '바뀐 기억']);
  assert.equal(editedShelf.label(), '읽기');
});

test('switching speakers hides other memoirs and cannot open their books by an old ID',()=>{
  const shelf=libraryFixture(()=>null);
  assert.match(shelf.html(),/data-library-book="volume-1"/);
  shelf.selectElder('preview-elder-1');
  assert.doesNotMatch(shelf.html(),/data-library-book=/);
  shelf.openBook('volume-1');
  assert.equal(shelf.navigations.length,0);
  shelf.selectElder('preview-self');
  shelf.openBook('volume-1');
  assert.deepEqual(shelf.navigations,['reader']);
});

test('bookshelf keeps the reading label for cover-only, corrupt, or unavailable storage', () => {
  for (const stored of [null, '{broken', 'null', '{}',
    JSON.stringify({location:{section:0,offset:0},atStart:true,bookmarks:[]}),
    JSON.stringify({location:{section:50,offset:.5},atStart:false,bookmarks:[]})]) {
    assert.equal(libraryFixture(() => stored).label(), '읽기');
  }
  assert.equal(libraryFixture(() => {throw new Error('Storage is blocked');}).label(), '읽기');
});

test('bookmark matching is local to the section and nearby reading position', () => {
  assert.equal(typeof model.sameLocation, 'function');
  assert.equal(model.sameLocation({section:1,offset:.4},{section:1,offset:.45}),true);
  assert.equal(model.sameLocation({section:1,offset:.4},{section:2,offset:.4}),false);
  assert.equal(model.sameLocation({section:1,offset:.4},{section:1,offset:.9}),false);
});

test('switching to desktop cannot replace the last visible mobile reading location', () => {
  assert.equal(typeof model.locationFromBounds, 'function');
  assert.deepEqual(model.locationFromBounds([
    {top:0,height:0},{top:0,height:0},{top:0,height:0},
  ],{section:1,offset:.42}), {section:1,offset:.42});
});

test('a visible chapter determines the reading position at the text anchor', () => {
  assert.equal(typeof model.locationFromBounds, 'function');
  assert.deepEqual(model.locationFromBounds([
    {top:-500,height:400},{top:80,height:400},{top:600,height:400},
  ],{section:0,offset:0}), {section:1,offset:.06});
});

test('structured chapters show one heading while legacy paragraphs keep their memory headings',()=>{
  assert.equal(typeof model.chapterHeading,'function');
  assert.deepEqual(model.chapterHeading({chapterTitle:'실제 장 제목',chapterNo:2,paragraphIndex:0},3),{title:'실제 장 제목',number:2,show:true});
  assert.deepEqual(model.chapterHeading({chapterTitle:'실제 장 제목',chapterNo:2,paragraphIndex:1},4),{title:'실제 장 제목',number:2,show:false});
  assert.deepEqual(model.chapterHeading({chapterTitle:null,paragraphIndex:1},1),{title:'두 번째 기억',number:2,show:true});
});

test('the contents keeps the chapter selected when reading its second or later paragraph',()=>{
  assert.equal(typeof model.contentsIndex,'function');
  const sections=[{chapterTitle:'첫 장',chapterNo:1,paragraphIndex:0},
    {chapterTitle:'다음 장',chapterNo:2,paragraphIndex:0},{chapterTitle:'다음 장',chapterNo:2,paragraphIndex:1}];
  assert.equal(model.contentsIndex(sections,2),1);
  assert.equal(model.contentsIndex(sections,0),0);
  assert.equal(model.contentsIndex([{chapterTitle:null},{chapterTitle:null}],1),1);
  assert.equal(model.contentsIndex(undefined,2),2);
});
