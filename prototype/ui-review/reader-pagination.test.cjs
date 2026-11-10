'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const file=require('node:path').join(__dirname,'reader-pagination.js');
const pager=fs.existsSync(file)?require(file):{};
const capacity=(size)=>(blocks)=>blocks.reduce((sum,block)=>sum+Array.from(block.text).length,0)<=size;

test('pagination preserves every character and order across long Korean paragraphs and emoji',()=>{
  assert.equal(typeof pager.paginate,'function');
  const paragraphs=['가나다라🍀'.repeat(87),'둘째 기억입니다. '.repeat(31),'마지막 문장.'];
  const pages=pager.paginate(paragraphs,capacity(93));
  assert.ok(pages.length>5);
  paragraphs.forEach((text,section)=>assert.equal(pages.flat().filter(b=>b.section===section).map(b=>b.text).join(''),text));
  assert.ok(pages.every(page=>capacity(93)(page)));
});

test('repagination locates the same passage after changing type size or viewport',()=>{
  const paragraphs=['첫 장의 기억'.repeat(70),'함께한 기억'.repeat(80)];
  const location={section:1,offset:.61};
  for(const size of [47,123,520]){
    const pages=pager.paginate(paragraphs,capacity(size));
    const page=pages[pager.pageForLocation(pages,location,paragraphs)];
    const character=Math.floor(Array.from(paragraphs[1]).length*.61);
    assert.ok(page.some(b=>b.section===1&&b.start<=character&&b.end>character));
  }
});

test('tiny space or empty text cannot loop forever or lose a final character',()=>{
  assert.deepEqual(pager.paginate([],capacity(1)),[]);
  const pages=pager.paginate(['🍀끝'],()=>false);
  assert.equal(pages.flat().map(b=>b.text).join(''),'🍀끝');
  assert.equal(pages.length,2);
});

test('an exact page boundary restores to that page without floating point drift',()=>{
  const paragraphs=['가'.repeat(100)];
  const pages=pager.paginate(paragraphs,capacity(29));
  pages.forEach((page,index)=>assert.equal(pager.pageForLocation(pages,{section:0,offset:page[0].start/100},paragraphs),index));
});

test('bookmarks on different pages of a long paragraph remain separate',()=>{
  const paragraphs=['가'.repeat(10000)],pages=pager.paginate(paragraphs,capacity(250));
  assert.equal(pager.samePassage({section:0,offset:0},{section:0,offset:.05},paragraphs,pages),false);
  assert.equal(pager.samePassage({section:0,offset:.05},{section:0,offset:.051},paragraphs,pages),true);
  assert.equal(pager.samePassage({section:0,offset:0},{section:0,offset:.05},paragraphs),false);
});

test('five text pages plus a cover form three complete spreads with a final 100 percent',()=>{
  assert.equal(typeof pager.viewState,'function');
  assert.deepEqual(pager.viewState(0,5,2),{start:0,end:1,total:6,previous:null,next:2,percent:0});
  assert.deepEqual(pager.viewState(3,5,2),{start:2,end:3,total:6,previous:0,next:4,percent:50});
  assert.deepEqual(pager.viewState(5,5,2),{start:4,end:5,total:6,previous:2,next:null,percent:100});
});

test('six text pages plus a cover end with a single real page and no phantom next page',()=>{
  assert.equal(typeof pager.viewState,'function');
  assert.deepEqual(pager.viewState(6,6,2),{start:6,end:6,total:7,previous:4,next:null,percent:100});
  assert.equal(pager.viewState(4,6,2).next,6);
  assert.deepEqual(pager.viewState(99,6,2),{start:6,end:6,total:7,previous:4,next:null,percent:100});
  assert.equal(pager.viewState(-1,6,2).start,0);
});

test('a cover-only book has one complete view and cannot navigate',()=>{
  assert.equal(typeof pager.viewState,'function');
  assert.equal(typeof pager.viewAtPercent,'function');
  assert.deepEqual(pager.viewState(0,0,2),{start:0,end:0,total:1,previous:null,next:null,percent:100});
  assert.equal(pager.viewAtPercent(0,0,2),0);
  assert.equal(pager.viewAtPercent(100,0,2),0);
});

test('single-page navigation remains the default and has the same end boundary',()=>{
  assert.equal(typeof pager.viewState,'function');
  assert.deepEqual(pager.viewState(2,5),{start:2,end:2,total:6,previous:1,next:3,percent:40});
  assert.deepEqual(pager.viewState(5,5),{start:5,end:5,total:6,previous:4,next:null,percent:100});
});

test('the progress slider maps to the closest view and round-trips the last spread',()=>{
  assert.equal(typeof pager.viewAtPercent,'function');
  assert.equal(pager.viewAtPercent(24,5,2),0);
  assert.equal(pager.viewAtPercent(25,5,2),2);
  assert.equal(pager.viewAtPercent(74,5,2),2);
  assert.equal(pager.viewAtPercent(75,5,2),4);
  assert.equal(pager.viewAtPercent(100,5,2),4);
  assert.equal(pager.viewAtPercent(100,6,2),6);
  assert.equal(pager.viewAtPercent(-20,6,2),0);
  assert.equal(pager.viewAtPercent(120,6,2),6);
  for(const size of [1,2])for(const last of [0,5,6]){
    for(let start=0;start<=last;start+=size){
      const state=pager.viewState(start,last,size);
      assert.equal(pager.viewAtPercent(state.percent,last,size),state.start);
    }
  }
});

test('a right-page target shares its spread with the left page across section boundaries',()=>{
  assert.equal(typeof pager.sameView,'function');
  const paragraphs=['가나다라','마바사아','자차카타'];
  const pages=pager.paginate(paragraphs,capacity(4));
  const left={section:1,offset:0},right={section:2,offset:.5};
  const target=pager.pageForLocation(pages,right,paragraphs)+1;
  assert.equal(target,3);
  assert.equal(pager.viewState(target,pages.length,2).start,2);
  assert.equal(pager.sameView(left,right,paragraphs,pages,2),true);
  assert.equal(pager.sameView(left,right,paragraphs,pages),false);
  assert.equal(pager.samePassage(left,right,paragraphs,pages),false);
  assert.equal(pager.sameView(null,right,paragraphs,pages,2),false);
});

test('the cover offset keeps the first and second text pages on different spreads',()=>{
  assert.equal(typeof pager.sameView,'function');
  const paragraphs=['가나다라','마바사아'],pages=pager.paginate(paragraphs,capacity(4));
  const first={section:0,offset:0},second={section:1,offset:0};
  assert.equal(pager.viewState(pager.pageForLocation(pages,first,paragraphs)+1,pages.length,2).start,0);
  assert.equal(pager.viewState(pager.pageForLocation(pages,second,paragraphs)+1,pages.length,2).start,2);
  assert.equal(pager.sameView(first,second,paragraphs,pages,2),false);
});
