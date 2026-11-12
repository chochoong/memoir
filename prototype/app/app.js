'use strict';

// Standalone review fixture. No API, microphone or audio. The mobile reader
// remembers appearance and reading positions locally; memoir text stays in memory.
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeText = (value) => String(value).replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const icons = (name, extra = '') => `<svg class="icon ${extra}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const categories = {childhood:'어린 시절',family:'가족',life:'삶과 일'};
const recordData = [
  {id:1,category:'childhood',title:'느티나무 아래, 우리 동네',date:'2026. 10. 28.',description:'친구들과 해가 질 때까지 뛰놀던 골목과 커다란 느티나무 이야기.',icon:'leaf'},
  {id:2,category:'family',title:'어머니의 따뜻한 밥상',date:'2026. 10. 26.',description:'부엌에서 피어오르던 구수한 냄새, 말없이 건네주신 따뜻한 마음.',icon:'home'},
  {id:3,category:'life',title:'처음 내 이름으로 받은 월급',date:'2026. 10. 23.',description:'서툴렀지만 설렜던 첫 출근과 가족에게 내밀었던 작은 봉투.',icon:'letter'},
  {id:4,category:'family',title:'우리 가족의 첫 소풍',date:'2026. 10. 20.',description:'김밥을 나누어 먹고 사진 한 장을 남겼던, 유난히 맑았던 날.',icon:'leaf'},
  {id:5,category:'childhood',title:'학교 가는 길의 작은 약속',date:'2026. 10. 17.',description:'모퉁이에서 만나 함께 등교하던 친구와 나눈 소소한 약속들.',icon:'book'},
  {id:6,category:'life',title:'서툰 마음으로 가꾼 작은 정원',date:'2026. 10. 14.',description:'씨앗 하나를 심고 기다리며 배웠던, 느리게 자라는 것들의 힘.',icon:'leaf'},
];
const styles = [
  {id:'plain',title:'담백한 기록',description:'내 말투에 가까운, 솔직하고 편안한 글',icon:'pen',sample:'우리 동네에는 커다란 느티나무가 있었다. 학교가 끝나면 친구들과 그 아래 모였다. 해가 기울고 집집마다 저녁 짓는 냄새가 날 때까지, 우리는 시간 가는 줄 몰랐다.'},
  {id:'essay',title:'다정한 에세이',description:'그때의 마음을 천천히 돌아보는 글',icon:'leaf',sample:'이상하게도 어린 날의 기억에는 늘 나무 그늘이 있다. 그 아래서 보낸 오후들은 아주 평범했는데, 오래 지나 돌아보니 가장 넉넉했던 시간이었다. 내 마음은 아직도 가끔 그 그늘에서 쉰다.'},
  {id:'story',title:'이야기 소설',description:'한 장면씩 생생하게 펼쳐지는 글',icon:'spark',sample:'“조금만 더 놀다 가자!” 누군가 소리치자 아이들이 다시 느티나무 아래로 모여들었다. 골목 끝으로 노을이 번지고 있었다. 멀리서 저녁을 먹으라는 목소리가 들려왔다.'},
  {id:'letter',title:'한 통의 편지',description:'소중한 사람에게 조곤조곤 건네는 글',icon:'letter',sample:'너에게 내가 자란 동네 이야기를 해주고 싶구나. 마을 한가운데 커다란 느티나무가 있었단다. 친구들과 그 아래서 얼마나 많은 오후를 보냈는지 몰라. 언젠가 너와도 그 길을 걸어보고 싶어.'},
];
const initialBody = [
  '우리 동네에는 커다란 느티나무가 있었다. 학교가 끝나면 친구들과 그 아래 모였다. 책가방은 나무 밑에 아무렇게나 내려놓고, 돌멩이 하나와 나뭇가지 하나로도 한참을 놀았다.',
  '해가 기울면 골목에는 저녁 짓는 냄새가 퍼졌다. 어머니가 내 이름을 부르는 목소리가 들리면, 그제야 바지에 묻은 흙을 털고 집으로 달려갔다. 부엌에는 늘 따뜻한 밥상이 기다리고 있었다.',
  '시간이 흘러 처음으로 월급을 받던 날에도, 가장 먼저 떠오른 건 그 밥상이었다. 작은 봉투를 내밀자 어머니는 한참을 바라보다 웃으셨다. 이제는 알 것 같다. 내가 오래 기억하는 것은 큰 사건보다, 그때 주고받았던 작고 따뜻한 마음이라는 것을.',
];
// Static review policy differs from the unchanged 3–5-card server contract.
const memoirSelection = window.MemoirSelectionPolicy;
const MEMOIR_POLICY = memoirSelection.reviewPolicy;
const serviceContract = window.MemoirServiceContract;
const previewService = window.MemoirPreviewService;
const interviewCompletion = window.InterviewCompletion.createStore();
recordData.forEach((record,index)=>{
  const session={session_id:`00000000-0000-4000-8000-${String(index+1).padStart(12,'0')}`,elder_id:'preview-self',title:record.title,
    created_at:`2026-10-${[28,26,23,20,17,14][index]}T01:00:00Z`,
    postcard:{title:record.title,text:postcardBody(record),caption:'',style:'spoken'}};
  Object.assign(record,previewService.postcard(session,record));
});
const state = {selected:new Set(),pickRecords:false,interviewMode:'reading',interviewId:interviewCompletion.beginInterview(),interviewCompleted:false,storyToReview:null,reviewStoryId:null,style:'plain',filter:'all',query:'',question:0,answers:[],generating:false,font:23,spread:0,draftElderId:'preview-self',title:'그 시절의 골목, 오래 남은 마음',body:[...initialBody],document:null,job:null,serverMetadata:null,serverPreflight:null,recordState:new URLSearchParams(location.search).get('records') || 'normal'};
state.document=serviceContract.memoirView({status:'ready',title:state.title,body:initialBody.join('\n'),style:'spoken',sources:[],verification:{state:'not_run'}},{elder_id:state.draftElderId,uiStyle:state.style,preview:true});
const questions = [
  {title:'어린 시절, 가장 기억에 남는 <br>동네 풍경은 어떤 모습인가요?',hint:'눈을 감으면 떠오르는 풍경을 생각해 보세요.',step:'첫 번째 이야기'},
  {title:'그곳에서 함께 시간을 보낸 <br>사람은 누구였나요?',hint:'그 사람의 얼굴과 목소리를 천천히 떠올려 보세요.',step:'두 번째 이야기'},
  {title:'그 시절의 나에게 <br>어떤 말을 건네고 싶으세요?',hint:'지금의 마음으로 따뜻한 한마디를 전해보세요.',step:'세 번째 이야기'},
];
let toastTimer;
function toast(message){clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').hidden=false;toastTimer=setTimeout(()=>{$('#toast').hidden=true;},3300);}
function selectedStyle(){return styles.find((style)=>style.id===state.style);}
function selectionRangeText(){return MEMOIR_POLICY.max===null?`${MEMOIR_POLICY.min}장 이상`:`${MEMOIR_POLICY.min}~${MEMOIR_POLICY.max}장`;}
function navigate(screen){if(screen==='interview'&&window.RolePreview&&!window.RolePreview.canEnterInterview())screen='prepare';if(screen==='style'&&!memoirSelection.canGenerate(state.selected.size,MEMOIR_POLICY)){toast(`자서전으로 엮을 엽서를 ${selectionRangeText()} 골라주세요.`);screen='records';}if(location.hash===`#${screen}`)show(screen);else location.hash=screen;}
function show(screen) {
  if(window.RolePreview?.isInviteHash(`#${screen}`)){window.RolePreview.enterGuest(`#${screen}`);return;}
  const allowed = ['home','interview','records','library','style','draft','reader','prepare','invitations','invite','start','invite-setup'];
  if (!allowed.includes(screen)) screen = 'home';
  if(screen==='interview'&&window.RolePreview&&!window.RolePreview.canEnterInterview())screen='prepare';
  if(window.RolePreview?.isGuest()&&!['invite','interview'].includes(screen))screen='invite';
  if(['draft','reader'].includes(screen)&&state.draftElderId!==currentElderId()){screen=screen==='reader'?'library':'records';toast('선택한 이야기 주인공의 목록에서 다시 열어주세요.');}
  if (screen === 'style' && !memoirSelection.canGenerate(state.selected.size,MEMOIR_POLICY)) { navigate('records'); return; }
  if (screen === 'interview' && state.interviewCompleted) {
    state.interviewId=interviewCompletion.beginInterview();
    state.interviewCompleted=false;
    state.question=0;
    renderQuestion();setInterviewMode('reading');
  }
  window.dispatchEvent(new CustomEvent('memoir:before-screen', {detail:{screen}}));
  $$('[data-screen]').forEach((panel) => { panel.hidden = panel.dataset.screen !== screen; });
  const navScreen = ['draft','style'].includes(screen) ? 'records' : screen==='reader' ? 'library' : ['prepare','invitations','invite','start','invite-setup'].includes(screen)?'home':screen;
  $$('[data-nav]').forEach((link) => {
    if (link.dataset.nav === navScreen) link.setAttribute('aria-current','page');
    else link.removeAttribute('aria-current');
  });
  $('#topbar-title').textContent = ({home:'나의 이야기',interview:'인터뷰',prepare:'이야기 준비',invitations:'준비한 초대',invite:'초대 이야기',start:'이야기 시작',"invite-setup":'초대 주소 만들기',records:'나의 기록',library:'자서전 보기',style:'자서전 만들기',draft:'자서전 초안',reader:'자서전 읽기'})[screen];
  if (screen === 'records') renderRecords();
  if (screen === 'style') renderStyles();
  if (screen === 'draft') renderDraft();
  if (screen === 'reader') renderBook();
  window.RolePreview?.renderIdentity();
  window.scrollTo({top:0,behavior:'instant'});
  $(`[data-screen="${screen}"] h1`)?.focus({preventScroll:true});
  window.dispatchEvent(new CustomEvent('memoir:screen', {detail:{screen}}));
  if(screen==='records'&&state.storyToReview){const storyId=state.storyToReview;state.storyToReview=null;openStoryReview(storyId);}
}
function currentElderId(){return window.RolePreview?window.RolePreview.currentElderId():'preview-self';}
function currentRecords(){return recordData.filter(record=>record.elder_id===currentElderId());}
function renderRecent(){const records=currentRecords();$('#recent-list').innerHTML=records.slice(0,3).map((record)=>`<button type="button" class="recent-row" data-postcard="${record.id}" aria-label="${escapeText(record.title)}, ${record.date} 엽서 읽기"><span class="memory-thumbnail ${record.category}" aria-hidden="true">${icons(record.icon)}</span><span class="recent-copy"><strong>${escapeText(record.title)}</strong><small>${categories[record.category]} &nbsp;·&nbsp; ${record.date}</small></span><span class="recent-chevron" aria-hidden="true">${icons('chevron')}</span></button>`).join('')||'<p class="role-preview-note">이분의 첫 이야기를 기다리고 있어요.</p>';$$('.nav-count').forEach((node)=>node.textContent=records.length);}
function updateSelection() {
  const unavailable=['empty','error'].includes(state.recordState)||!currentRecords().length;
  const picking=state.pickRecords;
  $('[data-screen="records"]').classList.toggle('records-picking',picking);
  if(window.RolePreview)window.RolePreview.renderIdentity();
  else $('#records-heading').textContent=picking?'함께 엮을 엽서 고르기':'나의 기록';
  $('#selection-count').textContent=picking?`엽서 ${state.selected.size}장 선택`:`엽서 ${unavailable?0:currentRecords().length}장`;
  $('#selection-note').textContent=picking?`함께 엮을 엽서를 ${selectionRangeText()} 골라주세요.`:'기억이 모이면, 얇은 책 한 권이 됩니다.';
  $('#choose-style').disabled=unavailable||(picking&&!memoirSelection.canGenerate(state.selected.size,MEMOIR_POLICY));
  $('#choose-style').textContent=picking?(!memoirSelection.canGenerate(state.selected.size,MEMOIR_POLICY)?`${selectionRangeText()} 골라주세요`:'문체 고르기 →'):'자서전 만들기';
  $('#cancel-postcard-pick').hidden=!picking;
  $('#records-description').textContent=picking?'선택 상한을 풀어보는 검토용 화면이에요. 실제 생성은 계정별 허용 범위와 연결해야 합니다.':'엽서를 누르면 그날의 이야기를 읽을 수 있어요.';
  $('#build-summary').textContent=`엽서 ${state.selected.size}장 · ${selectedStyle().title}`;
  $$('.record-card').forEach((card)=>card.classList.toggle('selected',state.selected.has(Number(card.dataset.id))));
}

function renderPendingStories() {
  const stories=interviewCompletion.pendingStories().filter(story=>(window.RolePreview?.storyElderId(story.id)||'preview-self')===currentElderId());
  $('#pending-stories').hidden=!stories.length;
  $('#pending-stories-summary').textContent=`엽서로 만들기 전의 이야기 (${stories.length})`;
  $('#pending-story-list').innerHTML=stories.map((story)=>`<div class="pending-story-row"><strong>${escapeText(story.title)}</strong><button type="button" class="button outline compact" data-review-story="${escapeText(story.id)}" aria-label="${escapeText(story.title)} 확인">이야기 확인</button></div>`).join('');
}

function renderRecords() {
  renderPendingStories();
  const list=$('#record-list');
  $$('[data-filter]').forEach((button)=>button.setAttribute('aria-pressed',String(button.dataset.filter===state.filter)));
  if(state.recordState==='empty'||!currentRecords().length) {
    list.innerHTML=`<div class="empty-state">${icons('letter')}<h2>아직 모아둔 엽서가 없어요.</h2><p>떠오르는 기억 하나부터 들려주세요.</p><button class="button outline" data-go="interview">첫 이야기 시작하기</button></div>`;
    updateSelection();return;
  }
  if(state.recordState==='error') {
    list.innerHTML=`<div class="empty-state">${icons('letter')}<h2>지금은 엽서를 불러올 수 없어요.</h2><p>엽서가 사라진 것은 아니에요. 잠시 후 다시 확인해주세요.</p><button class="button outline" id="retry-records">다시 불러오기</button></div>`;
    updateSelection();return;
  }
  const filtered=currentRecords().filter((record)=>(state.filter==='all'||record.category===state.filter)&&`${record.title} ${record.description}`.includes(state.query));
  list.innerHTML=filtered.length?filtered.map((record)=>{
    const content=`<span class="memory-thumbnail ${record.category}" aria-hidden="true">${icons(record.icon)}</span><span class="record-copy"><span class="record-meta"><span class="category-label">${categories[record.category]}</span><span>·</span><span>${record.date}</span></span><strong>${escapeText(record.title)}</strong><p>${escapeText(record.description)}</p></span>`;
    if(!state.pickRecords)return `<button class="postcard-card" data-postcard="${record.id}">${content}${icons('chevron')}</button>`;
    return `<label class="record-card ${state.selected.has(record.id)?'selected':''}" data-id="${record.id}" for="record-${record.id}"><input type="checkbox" id="record-${record.id}" data-record="${record.id}" ${state.selected.has(record.id)?'checked':''}>${content}</label>`;
  }).join(''):`<div class="empty-state">${icons('search')}<h2>찾는 엽서가 없어요.</h2><p>다른 낱말로 찾아보세요.</p></div>`;
  updateSelection();
}

function postcardBody(record) {
  return record.body||(record.id<=3?initialBody[record.id-1]:`${record.description}\n\n오래 지나 돌아보니, 그날의 작고 따뜻한 마음이 여전히 선명하게 남아 있습니다.`);
}
let postcardOpener=null;
function openPostcard(id,opener=document.activeElement) {
  const record=recordData.find((item)=>item.id===id);
  if(!record)return;
  const body=postcardBody(record);
  $('#postcard-title').textContent=record.title;
  $('#postcard-body').innerHTML=body.split('\n\n').map((paragraph)=>`<p>${escapeText(paragraph)}</p>`).join('');
  if(!$('#postcard-dialog').open){postcardOpener=opener;$('#postcard-dialog').showModal();}
}
$('#postcard-dialog').addEventListener('close',()=>{
  if(postcardOpener?.isConnected&&!postcardOpener.closest('[hidden],dialog:not([open])'))postcardOpener.focus({preventScroll:true});
  else $(`[data-screen]:not([hidden]) h1`)?.focus({preventScroll:true});
  postcardOpener=null;
});

function openStoryReview(id) {
  const story=interviewCompletion.getStory(id);
  if(!story)return;
  state.reviewStoryId=story.id;
  $('#story-review-title').textContent=story.title;
  $('#story-review-body').innerHTML=story.body.split('\n\n').map((paragraph)=>`<p>${escapeText(paragraph)}</p>`).join('');
  $('#make-postcard').textContent=story.linkedRecordId===null?'예시 엽서 만들기':'엽서 보기';
  if(!$('#story-review-dialog').open)$('#story-review-dialog').showModal();
  $('#story-review-title').focus();
}

function startMemoirFromPostcards() {
  state.pickRecords=true;
  state.selected.clear();
  state.filter='all';state.query='';$('#record-search').value='';
  // Keep the readable document intact for history/back navigation. The next
  // draft replaces it only after its own generation has succeeded.
  state.pendingMemoirTitle='새로운 기억, 나의 이야기';
  if(location.hash==='#records')renderRecords();else navigate('records');
  window.scrollTo({top:0,behavior:'instant'});
  $('#records-heading').focus({preventScroll:true});
}
function renderStyles(){$('#style-options').innerHTML=styles.map((style)=>`<button class="style-card" data-style="${style.id}" aria-pressed="${style.id===state.style}"><span class="style-icon">${icons(style.icon)}</span><span><strong>${style.title}</strong><small>${style.description}</small></span><span class="style-check" aria-hidden="true"></span></button>`).join('');$('#style-sample').textContent=selectedStyle().sample;$('#style-credit').textContent=`「느티나무 아래, 우리 동네」 · ${selectedStyle().title} 예시`;$('#build-summary').textContent=`이야기 ${state.selected.size}개 · ${selectedStyle().title}`;}
function setInterviewMode(mode) {
  state.interviewMode=mode;
  const visual=window.InterviewVisualState.visualFor(mode);
  $('.interview-studio').dataset.interviewState=mode;
  $('#radio-scene').dataset.radioState=visual.radioState;
  $('#listening-status').textContent=visual.status;
  $('#studio-hint').textContent=visual.hint;
  $('#pause-interview').innerHTML=`${icons(visual.icon)}<span>${visual.action}</span>`;
  $('#pause-interview').disabled=mode==='processing';
  $('#pause-interview').hidden=mode==='text';
  $('#toggle-answer').disabled=mode==='processing';
  $('#toggle-answer').innerHTML=`${icons(mode==='text'?'mic':'pen')}${mode==='text'?'말로 하기':'글로 쓰기'}`;
  $('#toggle-answer').setAttribute('aria-expanded',String(mode==='text'));
  window.RadioFeedback?.update(mode);
  $('#answer-panel').hidden=mode!=='text';
}
function renderQuestion(){const alternatives={가족:['함께한 가족 중 가장 먼저 떠오르는 분은 누구인가요?','그분과 함께 보낸 어떤 순간이 기억나세요?','그분에게 지금 어떤 말을 전하고 싶으세요?'],'삶과 일':['처음 일을 시작하던 날은 어떤 모습이었나요?','일하면서 가장 마음에 남은 순간은 언제인가요?','그 시절의 나에게 어떤 말을 건네고 싶으세요?']};const question=questions[state.question];$('#interview-question').textContent=alternatives[state.interviewTopic]?.[state.question]||question.title.replace(/\s*<br>\s*/g,' ');$('#question-hint').textContent=alternatives[state.interviewTopic]?'떠오르는 장면부터 천천히 들려주세요.':question.hint;$('#interview-counter').textContent=question.step;}
function nextQuestion(){state.question=(state.question+1)%questions.length;renderQuestion();setInterviewMode('reading');}
function renderDraft(){$('#draft-title').textContent=state.title;$('#draft-body').innerHTML=state.body.map((paragraph)=>`<p>${escapeText(paragraph)}</p>`).join('');$('#draft-style-label').textContent=selectedStyle().title;$('#draft-reading').hidden=false;$('#draft-editor').hidden=true;$('#edit-draft span').textContent='글 수정하기';}
function bookPages(){
  const pages=[{chapter:'나의 작은 자서전',title:state.title,paragraphs:[],image:true}];
  state.body.forEach((paragraph,index)=>{
    const words=paragraph.match(/\S+\s*/g)||[];
    let chunk='';
    words.forEach((word)=>{
      if(chunk && chunk.length+word.length>155){pages.push({chapter:`나의 이야기 · ${index+1}`,title:'',paragraphs:[chunk.trim()]});chunk='';}
      chunk+=word;
    });
    if(chunk)pages.push({chapter:`나의 이야기 · ${index+1}`,title:'',paragraphs:[chunk.trim()]});
  });
  if(pages.length%2)pages.push({chapter:'그리고, 다음 이야기',title:'우리의 이야기는 계속됩니다.',paragraphs:[]});
  return pages;
}
function renderBook(){const pages=bookPages();state.spread=Math.min(state.spread,pages.length/2-1);['#book-left','#book-right'].forEach((selector,index)=>{const pageIndex=state.spread*2+index,page=pages[pageIndex];$(selector).innerHTML=`<span class="book-chapter">${escapeText(page.chapter)}</span>${page.image?'<img class="book-art" src="book-illustration.svg" alt="오래된 사진과 자서전을 담은 기억의 삽화">':''}${page.title?`<h2>${escapeText(page.title)}</h2>`:''}${page.paragraphs.map((paragraph)=>`<p>${escapeText(paragraph)}</p>`).join('')}<span class="page-number">${pageIndex+1}</span>`;});$('#page-label').textContent=`${state.spread*2+1}–${state.spread*2+2} / ${pages.length}쪽`;$('#previous-page').disabled=state.spread===0;$('#next-page').disabled=state.spread===pages.length/2-1;$('#font-smaller').disabled=state.font<=21;$('#font-larger').disabled=state.font>=29;document.documentElement.style.setProperty('--reader-size',`${state.font}px`);}
document.addEventListener('click',(event)=>{
  const target=event.target.closest('button,a');
  if(!target)return;
  if(target.classList.contains('skip-link')){event.preventDefault();$('#main-content').focus();return;}
  if(target.dataset.nav==='records'){
    state.pickRecords=false;
    if(location.hash==='#records')renderRecords();
  }
  if(target.dataset.postcard){openPostcard(Number(target.dataset.postcard),target);return;}
  if(target.dataset.reviewStory){openStoryReview(target.dataset.reviewStory);return;}
  if(target.dataset.go){
    if(target.dataset.go==='records'&&!['#style','#draft'].includes(location.hash))state.pickRecords=false;
    navigate(target.dataset.go);return;
  }
  if(target.hasAttribute('data-help')){$('#help-dialog').showModal();return;}
  if(target.hasAttribute('data-login')){window.MemoirLogin.open();return;}
  if(target.dataset.filter){state.filter=target.dataset.filter;renderRecords();return;}
  if(target.dataset.style){
    state.style=target.dataset.style;
    $$('[data-style]').forEach((button)=>button.setAttribute('aria-pressed',String(button.dataset.style===state.style)));
    $('#style-sample').textContent=selectedStyle().sample;
    $('#style-credit').textContent=`「느티나무 아래, 우리 동네」 · ${selectedStyle().title} 예시`;
    $('#build-summary').textContent=`엽서 ${state.selected.size}장 · ${selectedStyle().title}`;
    return;
  }
  if(target.id==='retry-records'){state.recordState='normal';renderRecords();toast('예시 엽서를 다시 불러왔어요.');}
});
$('#record-list').addEventListener('change',(event)=>{const checkbox=event.target.closest('[data-record]');if(!checkbox)return;const id=Number(checkbox.dataset.record);if(checkbox.checked&&!memoirSelection.canAdd(state.selected.size,MEMOIR_POLICY)){checkbox.checked=false;toast(`엽서는 ${selectionRangeText()} 고를 수 있어요.`);return;}if(checkbox.checked)state.selected.add(id);else state.selected.delete(id);updateSelection();});
$('#record-search').addEventListener('input',(event)=>{state.query=event.target.value.trim();renderRecords();});
$('#choose-style').addEventListener('click',()=>{if(state.pickRecords)navigate('style');else startMemoirFromPostcards();});
$('#cancel-postcard-pick').addEventListener('click',()=>{state.pickRecords=false;renderRecords();$('#records-heading').focus({preventScroll:true});});
$('#pause-interview').addEventListener('click',()=>setInterviewMode(window.InterviewVisualState.nextVoicePhase(state.interviewMode)));
$('#toggle-answer').addEventListener('click',()=>{const mode=state.interviewMode==='text'?'reading':'text';setInterviewMode(mode);if(mode==='text')$('#answer-text').focus();});
$('#next-question').addEventListener('click',nextQuestion);
$('#answer-panel').addEventListener('submit',(event)=>{event.preventDefault();const answer=$('#answer-text').value;if(!answer.trim()){toast('떠오르는 기억을 한 줄 적어주세요.');$('#answer-text').focus();return;}state.answers.push(answer);$('#answer-text').value='';toast('이번 미리보기에 이야기를 남겼어요.');nextQuestion();setInterviewMode('text');$('#answer-text').focus();});
$('#finish-interview').addEventListener('click',()=>{$('#finish-dialog').showModal();$('#finish-heading').focus();});
$('#keep-interview').addEventListener('click',()=>$('#finish-dialog').close());
$('#confirm-finish').addEventListener('click',()=>{
  if(window.RolePreview&&!window.RolePreview.canFinish()){$('#finish-dialog').close();toast('중단된 초대예요. 초대를 준비한 분에게 새 이야기를 요청해주세요.');navigate('invite');return;}
  const result=interviewCompletion.completeInterview({interviewId:state.interviewId,answers:state.answers,pendingText:$('#answer-text').value});
  if(!result.completed){
    $('#finish-dialog').close();setInterviewMode('text');
    toast('아직 남긴 이야기가 없어요. 떠오르는 기억을 한 줄 적어주세요.');
    $('#answer-text').focus();return;
  }
  // Copy succeeds before clearing the live interview. A duplicate click uses the same interview ID.
  state.answers=[];$('#answer-text').value='';state.interviewCompleted=true;
  setInterviewMode('reading');$('#finish-dialog').close();
  if(window.RolePreview?.complete(result.story))return;
  state.pickRecords=false;state.storyToReview=result.story.id;navigate('records');
});
$('#later-story').addEventListener('click',()=>$('#story-review-dialog').close());
$('#story-review-dialog').addEventListener('close',()=>{if(location.hash==='#records'&&!$('#pending-stories').hidden&&!$('#postcard-dialog').open)$('#pending-stories-summary').focus();});
$('#make-postcard').addEventListener('click',()=>{
  const result=interviewCompletion.makePostcard(state.reviewStoryId,recordData);
  if(!result.record)return;
  if(result.created){
    const elderId=window.RolePreview?.storyElderId(state.reviewStoryId)||'preview-self';
    const presentation={...result.record,category:window.RolePreview?.storyCategory(state.reviewStoryId)||result.record.category};
    recordData.unshift(previewService.postcard({session_id:result.record.session_id,elder_id:elderId,title:result.record.title,created_at:result.record.created_at,
      postcard:{title:result.record.title,text:result.record.body,caption:'',style:'spoken'}},presentation));state.recordState='normal';
    renderRecent();renderRecords();toast('입력한 이야기 그대로 예시 엽서를 만들었어요.');
  }
  $('#story-review-dialog').close();openPostcard(result.record.id);
});
$('#generate-draft').addEventListener('click',()=>{
  if(state.generating)return;
  const selection=memoirSelection.orderedSelection(state.selected,recordData);
  if(!memoirSelection.canGenerate(selection.records.length,MEMOIR_POLICY)){navigate('records');toast(`엽서를 ${selectionRangeText()} 골라주세요.`);return;}
  const chosen=selection.records,context={elder_id:currentElderId(),uiStyle:state.style,title:state.pendingMemoirTitle||state.title,preview:true};
  // Preview policy stays independent. A real request must pass metadata/style/
  // mode validation; missing deployment metadata never means API access granted.
  state.previewRequest={session_ids:selection.session_ids};
  state.serverPreflight=memoirSelection.prepareRequest({mode:'explicit',sessionIds:selection.session_ids,uiStyle:state.style},state.serverMetadata);
  let job;
  try{job=previewService.createMemoirJob(chosen,context);}catch(error){toast(/session time/.test(error.message)?'기록의 시작 시각으로 순서를 정할 수 없어요. 다른 기록을 골라주세요.':'같은 이야기 주인공의 기록을 다시 골라주세요.');return;}
  state.job=serviceContract.jobView(job,context);
  state.draftElderId=context.elder_id;
  state.generating=true;
  const dialog=$('#generation-dialog');dialog.showModal();
  setTimeout(()=>{
    if(state.job?.job_id!==job.job_id)return;
    try{
      state.job=serviceContract.jobView(previewService.completeMemoirJob(job),context);
      if(!state.job.canRead)throw new Error('preview result is not ready');
      state.document=state.job.document;state.title=state.document.title;state.body=[...state.document.body];state.pendingMemoirTitle=null;
      state.style=context.uiStyle;state.draftElderId=context.elder_id;state.spread=0;
      if(currentElderId()===context.elder_id){navigate('draft');toast('선택한 엽서를 모은 예시 초안이에요. 실제 AI 생성은 연결되지 않았어요.');}
      else toast('선택했던 이야기 주인공의 예시 초안을 준비했어요.');
    }catch{toast('초안을 표시하지 못했어요. 고른 기록을 확인하고 다시 시도해 주세요.');}
    finally{state.generating=false;dialog.close();}
  },850);
});
$('#generation-dialog').addEventListener('cancel',(event)=>event.preventDefault());
$('#edit-draft').addEventListener('click',()=>{const editing=$('#draft-editor').hidden;if(editing){$('#edit-title').value=state.title;$('#edit-body').value=state.body.join('\n\n');$('#draft-reading').hidden=true;$('#draft-editor').hidden=false;$('#edit-draft span').textContent='수정 취소';$('#edit-title').focus();}else renderDraft();});
$('#draft-editor').addEventListener('submit',(event)=>{event.preventDefault();const title=$('#edit-title').value.trim(),body=$('#edit-body').value;if(!title||!body.trim()){toast('제목과 이야기를 모두 적어주세요.');return;}const paragraphs=body.split(/\n\s*\n/).filter(paragraph=>paragraph.trim());const original=state.document||serviceContract.memoirView({status:'ready',title:state.title,body:state.body.join('\n'),style:'spoken',sources:[]},{elder_id:state.draftElderId,uiStyle:state.style,preview:true});state.document=serviceContract.editMemoir(original,{title,body:paragraphs});state.title=state.document.title;state.body=[...state.document.body];renderDraft();toast('이번 미리보기에 수정한 글을 적용했어요.');});
$('#save-volume').addEventListener('click',()=>window.MemoirLibrary.saveDraft());
$('#download-draft').addEventListener('click',()=>{const text=`${state.title}\n\n${state.body.join('\n\n')}\n\n— 내말싸미에서 엮은 자서전`;const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download=`${String(state.title||'자서전').replace(/[\\/:*?"<>|]/g,'').slice(0,40)}.txt`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('#previous-page').addEventListener('click',()=>{if(state.spread>0){state.spread--;renderBook();}});
$('#next-page').addEventListener('click',()=>{if(state.spread<bookPages().length/2-1){state.spread++;renderBook();}});
$('#font-smaller').addEventListener('click',()=>{state.font=Math.max(21,state.font-2);renderBook();});
$('#font-larger').addEventListener('click',()=>{state.font=Math.min(29,state.font+2);renderBook();});
document.addEventListener('keydown',(event)=>{if(location.hash!=='#reader'||document.body.classList.contains('ebook-mode')||event.target.closest('input,textarea,button,dialog'))return;if(event.key==='ArrowRight')$('#next-page').click();if(event.key==='ArrowLeft')$('#previous-page').click();});
$$('.review-dialog').forEach((dialog)=>dialog.addEventListener('click',(event)=>{if(event.target===dialog){const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();}}));
window.addEventListener('hashchange',()=>show(location.hash.slice(1)||'home'));
window.addEventListener('memoir:preview-auth',(event)=>{
  const avatar=$('[data-login]');
  avatar.dataset.previewLogin=event.detail.authenticated?'on':'off';
  avatar.setAttribute('aria-label',event.detail.authenticated?'내 계정 보기':'로그인');
  avatar.textContent=event.detail.authenticated?((event.detail.displayName||'나').trim().slice(0,1)):'나';
});
$('#radio-scene').innerHTML=window.createRadioIllustration();
renderRecent();renderQuestion();setInterviewMode('reading');show(location.hash.slice(1)||'home');
