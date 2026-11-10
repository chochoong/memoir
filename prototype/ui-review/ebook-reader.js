(function () {
  'use strict';
  // One reader for PC and mobile. No network, memoir text stays in tab memory.
  const model=window.MemoirReaderState, pager=window.MemoirPagination;
  const query=(selector)=>document.querySelector(selector);
  const queryAll=(selector)=>[...document.querySelectorAll(selector)];
  const preferencesKey='naemalssami.ui-review.reader.preferences.v1';
  const progressPrefix=model.progressPrefix;
  const sheets=queryAll('.ebook-sheet');
  const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
  let preferences=model.normalizePreferences(readStored(preferencesKey));
  let active=false, paged=false, spread=false, key='', sections=[], pages=[], pageIndex=0;
  let reading={location:{section:0,offset:0},atStart:true,bookmarks:[]};
  let previousScreen=location.hash.slice(1)||'home', returnScreen='library';
  let saveTimer, layoutFrame, scrollFrame, turnAnimation, turnOverlay, swipeStart, dragAnimation, lastSwipe=0;
  let restoring=false, activation=0;
  const measure=document.createElement('article');
  measure.className='ebook-content ebook-measure';
  measure.setAttribute('aria-hidden','true');measure.inert=true;
  query('#ebook-reader').append(measure);

  function readStored(storageKey){try{return JSON.parse(localStorage.getItem(storageKey));}catch{return null;}}
  function writeStored(storageKey,value){try{localStorage.setItem(storageKey,JSON.stringify(value));}catch{/* Current session works when storage is unavailable. */}}
  function headingFor(index){return model.chapterHeading(state.document?.sections?.[index],index);}
  function labelFor(index){return headingFor(index).title;}
  function textNodeFor(index){return query(`#ebook-content [data-section-index="${index}"] p`);}
  function codeUnitAt(text,character){return Array.from(text).slice(0,character).join('').length;}

  function currentLocation(){
    if(paged)return {...reading.location};
    const nodes=queryAll('#ebook-content .ebook-section');
    if(!nodes.length)return {...reading.location};
    let node=nodes[0];
    nodes.forEach(item=>{if(item.getBoundingClientRect().top<=104)node=item;});
    const section=Number(node.dataset.sectionIndex), paragraph=node.querySelector('p');
    const text=paragraph?.firstChild;
    if(!text)return {section,offset:0};
    const characters=Array.from(text.textContent);
    let low=0,high=characters.length-1,best=0;
    while(low<=high){
      const middle=Math.floor((low+high)/2),range=document.createRange();
      range.setStart(text,codeUnitAt(text.textContent,middle));
      range.setEnd(text,codeUnitAt(text.textContent,middle+1));
      if(range.getBoundingClientRect().top<=106){best=middle;low=middle+1;}else high=middle-1;
    }
    return {section,offset:characters.length?best/characters.length:0};
  }
  function saveProgress(){
    clearTimeout(saveTimer);
    if(!active||!key||restoring)return;
    reading.location=currentLocation();
    if(!paged)reading.atStart=window.scrollY<8;
    writeStored(progressPrefix+key,reading);
  }
  function scrollToLocation(value,atStart=false){
    const location=model.normalizeLocation(value,sections.length);
    reading.location=location;reading.atStart=atStart;
    if(paged){
      const index=atStart?0:pager.pageForLocation(pages,location,sections)+1;
      renderPage(index,false,false);return;
    }
    const paragraph=textNodeFor(location.section),text=paragraph?.firstChild;
    let top=0;
    if(!atStart&&text){
      const index=pager.characterAtOffset(text.textContent,location.offset);
      const range=document.createRange();range.setStart(text,codeUnitAt(text.textContent,Math.max(0,index)));range.setEnd(text,codeUnitAt(text.textContent,Math.max(0,index)+1));
      top=window.scrollY+range.getBoundingClientRect().top-104;
    }
    window.scrollTo({top:Math.max(0,top),behavior:'instant'});updateProgress();
  }
  function progressPercent(){
    if(paged)return Math.round(pager.viewState(pageIndex,pages.length,spread?2:1).percent);
    const distance=Math.max(0,document.documentElement.scrollHeight-window.innerHeight);
    return distance?Math.max(0,Math.min(100,Math.round(window.scrollY/distance*100))):100;
  }
  function bookmarkIndex(){const location=currentLocation();return reading.bookmarks.findIndex(bookmark=>paged?pager.sameView(bookmark,location,sections,pages,spread?2:1):pager.samePassage(bookmark,location,sections));}
  function updateBookmarkButton(){
    const selected=bookmarkIndex()!==-1,button=query('#ebook-toggle-bookmark');
    button.setAttribute('aria-pressed',String(selected));
    button.setAttribute('aria-label',selected?'현재 위치의 책갈피 해제':'현재 위치에 책갈피 추가');
  }
  function updateProgress(){
    if(!active||restoring)return;
    if(!paged){reading.location=currentLocation();reading.atStart=window.scrollY<8;}
    const percent=progressPercent();
    query('#ebook-progress').value=percent;
    query('#ebook-progress').setAttribute('aria-valuetext',`${percent}% 읽음`);
    query('#ebook-percent').textContent=`${percent}%`;
    query('#ebook-chapter-current').textContent=reading.atStart?'나의 작은 자서전':labelFor(reading.location.section);
    updateBookmarkButton();
  }
  function applyAppearance(){
    document.body.dataset.readerTheme=preferences.theme;
    document.body.dataset.readerFit=preferences.fitToScreen?'screen':'book';
    const paperAvailable=innerWidth>=1100&&innerHeight>=560;
    const effectiveTurn=preferences.turnStyle==='paper'&&!paperAvailable?'slide':preferences.turnStyle;
    document.body.dataset.readerTurn=effectiveTurn;
    document.body.style.setProperty('--ebook-font-size',`${preferences.fontSize}px`);
    document.body.style.setProperty('--ebook-line-height',preferences.lineHeight);
    document.body.style.setProperty('--ebook-font-family',preferences.fontFamily==='serif'?'"Batang", "바탕", Georgia, serif':'"Malgun Gothic", "Apple SD Gothic Neo", sans-serif');
    queryAll('[data-reader-theme-choice]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.readerThemeChoice===preferences.theme)));
    queryAll('[data-reader-font]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.readerFont===preferences.fontFamily)));
    queryAll('button[data-reader-turn]').forEach(button=>{button.setAttribute('aria-pressed',String(button.dataset.readerTurn===effectiveTurn));button.hidden=button.dataset.readerTurn==='paper'&&!paperAvailable;});
    query('#ebook-reduce-motion').checked=preferences.reduceMotion;
    query('#ebook-fit-screen').checked=preferences.fitToScreen;
    query('#ebook-font-size').value=preferences.fontSize;query('#ebook-font-value').textContent=preferences.fontSize;
    query('#ebook-line-height').value=Math.round(preferences.lineHeight*10);query('#ebook-line-value').textContent=preferences.lineHeight.toFixed(1);
    query('#ebook-font-down').disabled=preferences.fontSize<=18;query('#ebook-font-up').disabled=preferences.fontSize>=32;
  }
  function blockHTML(block){
    const heading=headingFor(block.section);
    return `<section class="ebook-section" data-section-index="${block.section}">${block.start===0&&heading.show?`<span class="ebook-chapter-label">${String(heading.number).padStart(2,'0')}</span><h2>${escapeText(heading.title)}</h2>`:''}<p>${escapeText(block.text)}</p></section>`;
  }
  function coverHTML(){return `<div class="ebook-cover-page"><span class="ebook-eyebrow">나의 작은 자서전</span><h1 class="ebook-title" id="ebook-title" tabindex="-1">${escapeText(state.title)}</h1><span class="ebook-cover-rule" aria-hidden="true"></span><p class="ebook-byline">내말싸미에서 엮은 나의 이야기</p><p class="ebook-cover-caption">말로 남긴 기억이, 한 권의 책으로.</p></div>`;}
  function resetSwipe(spring=false){
    const swipe=swipeStart,viewport=query('#ebook-viewport'),stage=query('#ebook-stage');swipeStart=null;
    if(dragAnimation)dragAnimation.cancel();dragAnimation=null;
    if(!swipe)return;
    if(swipe.locked)lastSwipe=Date.now();
    if(stage.hasPointerCapture?.(swipe.id))stage.releasePointerCapture(swipe.id);
    if(!swipe.styles)return;
    const from=viewport.style.transform;
    Object.assign(viewport.style,swipe.styles);
    if(spring&&swipe.x&&!preferences.reduceMotion&&!reducedMotion.matches){
      const base=swipe.styles.transform&&swipe.styles.transform!=='none'?`${swipe.styles.transform} `:'';
      const animation=viewport.animate([{transform:from},{offset:.8,transform:`${base}translateX(${-swipe.x*.035}px) scale(1)`},{transform:swipe.styles.transform||'none'}],{duration:280,easing:'cubic-bezier(.22,.8,.3,1)'});
      dragAnimation=animation;
      animation.finished.then(()=>{if(dragAnimation===animation)dragAnimation=null;}).catch(()=>{});
    }
  }
  function cancelTurn(){resetSwipe();if(turnAnimation)turnAnimation.cancel();turnAnimation=null;if(turnOverlay)turnOverlay.remove();turnOverlay=null;}
  function animateTurn(oldHTML,direction){
    if(preferences.reduceMotion||reducedMotion.matches)return;
    const content=query('#ebook-content');
    if(document.body.dataset.readerTurn==='paper'&&spread){
      const overlay=document.createElement('div');
      overlay.className=`ebook-content ebook-flip-sheet${direction<0?' turn-back':''}`;overlay.setAttribute('aria-hidden','true');overlay.inert=true;
      const backHTML=query(direction>0?'#ebook-content':'#ebook-right-content').innerHTML;
      overlay.innerHTML=`<div class="ebook-turn-face ebook-turn-front">${oldHTML}</div><div class="ebook-turn-face ebook-turn-back">${backHTML}</div>`;
      overlay.querySelectorAll('[id]').forEach(node=>node.removeAttribute('id'));
      overlay.style.transformOrigin=direction>0?'left center':'right center';
      query('#ebook-viewport').append(overlay);turnOverlay=overlay;
      turnAnimation=overlay.animate([{transform:'perspective(1800px) rotateY(0deg)',filter:'brightness(1)'},{offset:.5,transform:`perspective(1800px) rotateY(${direction>0?-90:90}deg)`,filter:'brightness(.91)'},{transform:`perspective(1800px) rotateY(${direction>0?-180:180}deg)`,filter:'brightness(1)'}],{duration:420,easing:'cubic-bezier(.25,.65,.3,1)',fill:'forwards'});
      const animation=turnAnimation;
      animation.finished.then(()=>{overlay.remove();if(turnAnimation===animation){turnAnimation=null;turnOverlay=null;}}).catch(()=>overlay.remove());
    }else{
      turnAnimation=query('#ebook-viewport').animate([{transform:`translateX(${direction*22}px)`,opacity:.45},{transform:'translateX(0)',opacity:1}],{duration:170,easing:'ease-out'});
    }
  }
  function renderPage(index,animate=false,record=true){
    cancelTurn();
    const view=pager.viewState(index,pages.length,spread?2:1),direction=view.start>=pageIndex?1:-1;
    const content=query('#ebook-content'),right=query('#ebook-right-content');
    const oldHTML=spread&&direction>0?right.innerHTML:content.innerHTML;
    const pageHTML=(number)=>number===0?coverHTML():pages[number-1]?pages[number-1].map(blockHTML).join(''):'<div class="ebook-blank-page"><span aria-hidden="true">✧</span><p>우리의 이야기는 계속됩니다.</p></div>';
    pageIndex=view.start;content.innerHTML=pageHTML(pageIndex);
    right.innerHTML=spread?pageHTML(pageIndex+1):'';
    if(record){const first=pages[pageIndex-1]?.[0];reading.location=first?{section:first.section,offset:first.start/Array.from(sections[first.section]).length}:{section:0,offset:0};reading.atStart=pageIndex===0;}
    query('#ebook-page-label').textContent=`${view.start+1}${view.end>view.start?`–${view.end+1}`:''} / ${view.total}쪽`;
    query('#ebook-page-previous').disabled=view.previous===null;query('#ebook-page-next').disabled=view.next===null;
    if(animate&&oldHTML)animateTurn(oldHTML,direction);
    updateProgress();
  }
  function renderScroll(){query('#ebook-content').innerHTML=`${coverHTML()}<div class="ebook-divider" aria-hidden="true"></div>${sections.map((text,section)=>blockHTML({section,start:0,text})).join('')}<div class="ebook-endmark"><span>✧</span><p>당신의 이야기는 계속됩니다.</p></div>`;}
  function relayout(location=reading.location,atStart=reading.atStart){
    if(!active)return;
    restoring=true;cancelTurn();
    applyAppearance();
    paged=preferences.turnStyle!=='scroll'&&innerHeight>=560&&innerWidth>=260;
    spread=paged&&innerWidth>=1100;
    document.body.classList.toggle('ebook-paged',paged);
    document.body.classList.toggle('ebook-spread',spread);
    query('#ebook-right-content').hidden=!spread;
    query('#ebook-right-content').innerHTML='';
    query('#ebook-content').setAttribute('aria-label',spread?'왼쪽 페이지 본문':'자서전 본문');
    query('#ebook-page-controls').hidden=!paged;
    query('#ebook-mode-note').textContent=preferences.turnStyle!=='scroll'&&!paged?'화면이 낮을 때는 글이 잘리지 않도록 세로로 읽어요.':innerWidth<1100?'모바일과 한 페이지 보기에서는 옆넘김과 스크롤을 사용해요.':'종이책 효과는 좌우 두 페이지가 보일 때만 사용할 수 있어요.';
    query('#ebook-content').innerHTML='';
    if(paged){
      window.scrollTo({top:0,behavior:'instant'});
      const viewport=query('#ebook-viewport');
      measure.style.width=`${query('#ebook-content').clientWidth}px`;measure.style.height=`${viewport.clientHeight}px`;
      pages=pager.paginate(sections,(blocks)=>{measure.innerHTML=blocks.map(blockHTML).join('');return measure.scrollHeight<=measure.clientHeight+1;});
      measure.innerHTML='';
    }else renderScroll();
    scrollToLocation(location,atStart);
    restoring=false;updateProgress();
  }
  function changeAppearance(changes){
    const location=currentLocation(),atStart=paged?reading.atStart:window.scrollY<8;
    preferences=model.normalizePreferences({...preferences,...changes});applyAppearance();writeStored(preferencesKey,preferences);
    cancelAnimationFrame(layoutFrame);layoutFrame=requestAnimationFrame(()=>{relayout(location,atStart);saveProgress();});
  }
  function showChrome(visible){
    document.body.classList.toggle('ebook-chrome-hidden',!visible);
    query('#ebook-topbar').inert=!visible;query('#ebook-bottom-bar').inert=!visible;
    query('#ebook-show-tools').hidden=visible;
  }
  function closeSheets(){sheets.forEach(sheet=>{if(sheet.open)sheet.close();});}
  function openSheet(id){cancelTurn();showChrome(true);closeSheets();if(id==='ebook-toc')renderContents();if(id==='ebook-bookmarks')renderBookmarks();query(`#${id}`).showModal();if(id==='ebook-settings')query('.ebook-settings-body').scrollTop=0;}
  function renderContents(){const current=model.contentsIndex(state.document?.sections,currentLocation().section);query('#ebook-toc-list').innerHTML=sections.map((paragraph,index)=>({index,heading:headingFor(index)})).filter(({heading})=>heading.show).map(({index,heading})=>`<button class="ebook-list-item" data-reader-section="${index}" ${index===current?'aria-current="location"':''}><span><small>${String(heading.number).padStart(2,'0')}</small><strong>${escapeText(heading.title)}</strong></span>${icons('chevron')}</button>`).join('');}
  function renderBookmarks(){
    const list=query('#ebook-bookmark-list');
    if(!reading.bookmarks.length){list.innerHTML=`<div class="ebook-empty">${icons('bookmark')}<h3>아직 책갈피가 없어요.</h3><p>이 창을 닫고 읽는 화면 오른쪽 위의 책갈피 모양을 눌러주세요.<br>현재 위치를 책갈피에 추가할 수 있어요.</p></div>`;return;}
    list.innerHTML=reading.bookmarks.map((bookmark,index)=>`<div class="ebook-bookmark-row"><button class="ebook-list-item" data-reader-bookmark="${index}"><span><small>책갈피 ${index+1}</small><strong>${escapeText(labelFor(bookmark.section))}</strong><span>${escapeText(Array.from(sections[bookmark.section]||'').slice(Math.floor(Array.from(sections[bookmark.section]||'').length*bookmark.offset)).join('').slice(0,45))}…</span></span>${icons('chevron')}</button><button class="ebook-icon-button" data-reader-delete-bookmark="${index}" aria-label="${index+1}번 책갈피 삭제">${icons('close')}</button></div>`).join('');
  }
  function setMode(screen){
    if(screen!=='reader'){
      if(active)saveProgress();active=false;activation++;restoring=false;closeSheets();cancelTurn();showChrome(true);
      document.body.classList.remove('ebook-mode','ebook-paged','ebook-spread');return;
    }
    const nextSections=state.body.filter(paragraph=>paragraph.trim()),nextKey=model.bookKey(state.title,nextSections);
    if(active&&key===nextKey)return;
    sections=nextSections;key=nextKey;
    const stored=readStored(progressPrefix+key);
    reading={location:model.normalizeLocation(stored?.location,sections.length),atStart:stored?.atStart!==false,bookmarks:Array.isArray(stored?.bookmarks)?stored.bookmarks.slice(0,50).map(bookmark=>model.normalizeLocation(bookmark,sections.length)):[]};
    active=true;restoring=true;const turn=++activation;
    document.body.classList.add('ebook-mode');query('#ebook-book-title').textContent=state.title;applyAppearance();showChrome(true);
    requestAnimationFrame(()=>{if(!active||turn!==activation)return;relayout();query('#ebook-content').focus({preventScroll:true});});
  }
  function turnPage(direction){if(!active||!paged)return;const view=pager.viewState(pageIndex,pages.length,spread?2:1),next=direction>0?view.next:view.previous;if(next===null)return;renderPage(next,true);saveProgress();}

  window.addEventListener('memoir:before-screen',event=>{if(active)saveProgress();if(event.detail.screen!=='reader')setMode(event.detail.screen);});
  window.addEventListener('memoir:screen',event=>{const screen=event.detail.screen;if(screen==='reader'&&previousScreen!=='reader')returnScreen=previousScreen;setMode(screen);previousScreen=screen;});
  window.addEventListener('pagehide',saveProgress);
  window.addEventListener('resize',()=>{if(!active)return;const location={...reading.location},atStart=reading.atStart;cancelAnimationFrame(layoutFrame);layoutFrame=requestAnimationFrame(()=>relayout(location,atStart));});
  document.fonts?.ready.then(()=>{if(active)relayout({...reading.location},reading.atStart);});
  window.addEventListener('scroll',()=>{if(!active||paged||restoring)return;cancelAnimationFrame(scrollFrame);scrollFrame=requestAnimationFrame(updateProgress);clearTimeout(saveTimer);saveTimer=setTimeout(saveProgress,180);},{passive:true});
  query('#ebook-exit').addEventListener('click',()=>navigate(returnScreen));
  query('#ebook-open-settings').addEventListener('click',()=>openSheet('ebook-settings'));
  query('#ebook-open-toc').addEventListener('click',()=>openSheet('ebook-toc'));
  query('#ebook-open-bookmarks').addEventListener('click',()=>openSheet('ebook-bookmarks'));
  queryAll('[data-close-reader-sheet]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
  queryAll('[data-reader-theme-choice]').forEach(button=>button.addEventListener('click',()=>changeAppearance({theme:button.dataset.readerThemeChoice})));
  queryAll('[data-reader-font]').forEach(button=>button.addEventListener('click',()=>changeAppearance({fontFamily:button.dataset.readerFont})));
  queryAll('button[data-reader-turn]').forEach(button=>button.addEventListener('click',()=>changeAppearance({turnStyle:button.dataset.readerTurn})));
  query('#ebook-reduce-motion').addEventListener('change',event=>changeAppearance({reduceMotion:event.target.checked}));
  query('#ebook-fit-screen').addEventListener('change',event=>changeAppearance({fitToScreen:event.target.checked}));
  query('#ebook-font-size').addEventListener('input',event=>changeAppearance({fontSize:Number(event.target.value)}));
  query('#ebook-line-height').addEventListener('input',event=>changeAppearance({lineHeight:Number(event.target.value)/10}));
  query('#ebook-font-down').addEventListener('click',()=>changeAppearance({fontSize:preferences.fontSize-1}));
  query('#ebook-font-up').addEventListener('click',()=>changeAppearance({fontSize:preferences.fontSize+1}));
  query('#ebook-progress').addEventListener('input',event=>{
    if(paged)renderPage(pager.viewAtPercent(Number(event.target.value),pages.length,spread?2:1),false);
    else{const distance=Math.max(0,document.documentElement.scrollHeight-window.innerHeight);window.scrollTo({top:distance*Number(event.target.value)/100,behavior:'instant'});updateProgress();}
    saveProgress();
  });
  query('#ebook-toggle-bookmark').addEventListener('click',()=>{const index=bookmarkIndex();if(index>=0)reading.bookmarks.splice(index,1);else if(reading.bookmarks.length<50)reading.bookmarks.push(currentLocation());else{toast('책갈피는 최대 50개까지 남길 수 있어요.');return;}saveProgress();updateBookmarkButton();toast(index>=0?'책갈피를 지웠어요.':'이곳에 책갈피를 남겼어요.');});
  query('#ebook-toc-list').addEventListener('click',event=>{const button=event.target.closest('[data-reader-section]');if(!button)return;closeSheets();scrollToLocation({section:Number(button.dataset.readerSection),offset:0});saveProgress();});
  query('#ebook-bookmark-list').addEventListener('click',event=>{const remove=event.target.closest('[data-reader-delete-bookmark]');if(remove){reading.bookmarks.splice(Number(remove.dataset.readerDeleteBookmark),1);saveProgress();updateBookmarkButton();renderBookmarks();return;}const button=event.target.closest('[data-reader-bookmark]');if(button){const bookmark=reading.bookmarks[Number(button.dataset.readerBookmark)];closeSheets();scrollToLocation(bookmark);saveProgress();}});
  query('#ebook-page-previous').addEventListener('click',()=>turnPage(-1));query('#ebook-page-next').addEventListener('click',()=>turnPage(1));
  const swipeIgnored='button,a,input,textarea,select,label,[contenteditable]:not([contenteditable="false"]),[role="button"]';
  query('#ebook-stage').addEventListener('pointerdown',event=>{
    if(!event.isPrimary){resetSwipe();return;}
    if(!active||!paged||event.button!==0||event.target.closest(swipeIgnored)||sheets.some(sheet=>sheet.open)||window.getSelection()?.toString())return;
    // A mouse drag over text keeps native selection; touch and pen still swipe.
    if(event.pointerType==='mouse'&&event.target.closest('p,h1,h2,h3,h4,h5,h6,span'))return;
    if(event.pointerType==='mouse'&&event.cancelable)event.preventDefault();
    cancelTurn();
    swipeStart={id:event.pointerId,startX:event.clientX,startY:event.clientY,lastX:event.clientX,lastTime:event.timeStamp,velocity:0,locked:false,x:0};
  });
  query('#ebook-stage').addEventListener('pointermove',event=>{
    const swipe=swipeStart;if(!swipe||event.pointerId!==swipe.id)return;
    if(!active||!paged||(event.pointerType==='mouse'&&event.buttons!==1)||window.getSelection()?.toString()){resetSwipe(true);return;}
    const dx=event.clientX-swipe.startX,dy=event.clientY-swipe.startY,elapsed=event.timeStamp-swipe.lastTime;
    if(elapsed>0)swipe.velocity=(event.clientX-swipe.lastX)/elapsed;
    swipe.lastX=event.clientX;swipe.lastTime=event.timeStamp;
    if(!swipe.locked){
      if(Math.abs(dy)>10&&Math.abs(dy)>Math.abs(dx)){resetSwipe();return;}
      if(Math.abs(dx)<10||Math.abs(dx)<Math.abs(dy)*1.5)return;
      swipe.locked=true;query('#ebook-stage').setPointerCapture?.(swipe.id);
    }
    if(event.cancelable)event.preventDefault();
    if(preferences.reduceMotion||reducedMotion.matches)return;
    const viewport=query('#ebook-viewport'),view=pager.viewState(pageIndex,pages.length,spread?2:1);
    if(!swipe.styles){swipe.styles={transform:viewport.style.transform,transition:viewport.style.transition,willChange:viewport.style.willChange};viewport.style.transition='none';viewport.style.willChange='transform';}
    const boundary=dx<0?view.next===null:view.previous===null,width=viewport.clientWidth||1,limit=Math.min(width*.28,160),distance=Math.abs(dx);
    swipe.x=boundary?36*dx/(distance+100):Math.sign(dx)*(distance<=limit?distance:limit+(distance-limit)*.12);
    const base=swipe.styles.transform&&swipe.styles.transform!=='none'?`${swipe.styles.transform} `:'';
    viewport.style.transform=`${base}translateX(${swipe.x}px) scale(${1-Math.min(Math.abs(swipe.x)/width,.3)*.02})`;
  },{passive:false});
  query('#ebook-stage').addEventListener('pointerup',event=>{
    const swipe=swipeStart;if(!swipe||event.pointerId!==swipe.id)return;
    const dx=event.clientX-swipe.startX,dy=event.clientY-swipe.startY,elapsed=event.timeStamp-swipe.lastTime;
    const velocity=elapsed>100?0:event.clientX!==swipe.lastX&&elapsed>0?(event.clientX-swipe.lastX)/elapsed:swipe.velocity;
    const horizontal=(swipe.locked||Math.abs(dx)>10)&&Math.abs(dx)>Math.abs(dy)*1.5;
    const selected=window.getSelection()?.toString(),direction=dx<0?1:-1,view=pager.viewState(pageIndex,pages.length,spread?2:1);
    const commit=active&&paged&&!selected&&horizontal&&(Math.abs(dx)>55||(Math.abs(dx)>18&&Math.abs(velocity)>.45&&Math.sign(velocity)===Math.sign(dx)))&&(direction>0?view.next:view.previous)!==null;
    if(horizontal||swipe.locked)lastSwipe=Date.now();
    resetSwipe(!commit);
    if(commit)turnPage(direction);
  });
  query('#ebook-stage').addEventListener('pointercancel',()=>resetSwipe(true));
  query('#ebook-stage').addEventListener('lostpointercapture',event=>{if(swipeStart?.id===event.pointerId)resetSwipe(true);});
  window.addEventListener('pointerup',event=>{if(swipeStart?.id===event.pointerId)resetSwipe(true);});
  window.addEventListener('pointercancel',event=>{if(swipeStart?.id===event.pointerId)resetSwipe(true);});
  reducedMotion.addEventListener?.('change',()=>{if(reducedMotion.matches)cancelTurn();});
  query('#ebook-viewport').addEventListener('click',event=>{
    if(Date.now()-lastSwipe<400||event.target.closest(swipeIgnored)||window.getSelection()?.toString())return;
    if(paged){
      const rect=query('#ebook-viewport').getBoundingClientRect(),edge=Math.min(rect.width*.12,100),x=event.clientX-rect.left;
      if(x<=edge){turnPage(-1);return;}
      if(x>=rect.width-edge){turnPage(1);return;}
    }
    showChrome(document.body.classList.contains('ebook-chrome-hidden'));
  });
  query('#ebook-show-tools').addEventListener('click',()=>showChrome(true));
  document.addEventListener('keydown',event=>{if(!active||sheets.some(sheet=>sheet.open)||(event.target.closest('input,textarea,button,select')&&!event.target.closest('[inert]')))return;if(event.key==='Escape')showChrome(true);if(paged&&['ArrowRight','PageDown','ArrowLeft','PageUp'].includes(event.key)){event.preventDefault();turnPage(['ArrowRight','PageDown'].includes(event.key)?1:-1);}});
  sheets.forEach(sheet=>sheet.addEventListener('click',event=>{if(event.target!==sheet)return;const rect=sheet.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)sheet.close();}));
  applyAppearance();setMode(location.hash.slice(1)||'home');
})();
