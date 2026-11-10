(function(){
  'use strict';
  // A tab-memory review of account/speaker/invitation UI. No access is granted.
  const store=window.RolePreviewState.createStore({emptySpeakers:new URLSearchParams(location.search).get('speakers')==='empty'});
  let run=null,issued=null,guest=false,guestReference='',revokeId=null;
  const interrupted=[];
  let guestStory=null;
  const topics=['어린 시절','가족','삶과 일'];
  const labels={ready:'시작 전',in_progress:'이야기 중',expired:'기한 지남',revoked:'취소됨',completed:'이야기 완료'};
  const host=document.querySelector('main');
  const context=document.createElement('div');context.className='role-context';context.hidden=true;host.querySelector('.review-notice').after(context);
  function addScreen(name,title){const section=document.createElement('section');section.className='screen role-screen';section.dataset.screen=name;section.hidden=true;section.innerHTML=`<h1 id="${name}-heading" tabindex="-1">${title}</h1><div class="role-content"></div>`;host.append(section);return section;}
  const prepare=addScreen('prepare','누구의 이야기를 담을까요?');
  const invitations=addScreen('invitations','준비한 초대');
  const entry=addScreen('invite','이야기를 들려주세요');
  const revokeDialog=document.createElement('dialog');
  revokeDialog.className='review-dialog role-confirm';
  revokeDialog.setAttribute('aria-labelledby','revoke-heading');
  revokeDialog.innerHTML='<h2 id="revoke-heading">초대를 취소할까요?</h2><p id="revoke-description"></p><div class="dialog-actions"><button type="button" class="button outline" data-role="keep-invite">그대로 두기</button><button type="button" class="button primary" data-role="confirm-revoke">초대 취소하기</button></div>';
  document.body.append(revokeDialog);
  function snapshot(){return store.snapshot();}
  function elder(){const data=snapshot();return data.elders.find(item=>item.elder_id===data.selectedElderId)||null;}
  const changeIcon='<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7a8 8 0 0 0-13-3L4 7m0-5v5h5M4 17a8 8 0 0 0 13 3l3-3m0 5v-5h-5"/></svg>';
  function changeMarkup(person){return `<button type="button" class="role-change" data-go="prepare" aria-label="${person?`이야기 주인공 변경, 현재 ${escapeText(person.name)}`:'이야기 주인공 이름 등록하기'}">${person?changeIcon:''}<span>${person?'변경':'이름 등록하기'}</span></button>`;}
  function renderIdentity(){
    const person=elder();
    const identity=JSON.stringify([person?.elder_id,person?.name]);
    const nameMarkup=person?`<span class="personal-name">「${escapeText(person.name)}」</span>`:'';
    for(const [screen,label,fallback] of [['records','기록','이야기 기록'],['library','자서전','자서전']]){
      const heading=$(`#${screen}-heading`);
      const picking=screen==='records'&&state.pickRecords;
      const key=JSON.stringify([identity,picking]);
      if(heading.dataset.identity!==key){
        heading.innerHTML=picking?'함께 엮을 엽서 고르기':person?`${nameMarkup}의 ${label}`:fallback;
        heading.dataset.identity=key;
      }
      const action=$(`[data-owner-change="${screen}"]`);
      if(action.dataset.identity!==identity){action.innerHTML=changeMarkup(person);action.dataset.identity=identity;}
    }
    const note=$('#records-owner-note');
    note.hidden=!state.pickRecords;
    note.textContent=person?`「${person.name}」의 기록에서 고르고 있어요.`:'이야기 주인공을 먼저 등록해주세요.';
  }
  function hasDraft(){return state.answers.length>0||!!$('#answer-text').value.trim();}
  function validRun(){return !!run&&!run.completed&&(!run.invitationId||snapshot().invitations.some(inv=>inv.id===run.invitationId&&inv.status==='in_progress'));}
  function interruptRun(id){if(run?.invitationId!==id)return;const text=[...state.answers,$('#answer-text').value].filter(value=>value.trim()).join('\n\n');if(text)interrupted.push({elderId:run.elderId,text});state.answers=[];$('#answer-text').value='';state.interviewCompleted=true;run=null;setInterviewMode('paused');}
  function refreshOwnership(){state.selected.clear();state.pickRecords=false;state.filter='all';state.query='';$('#record-search').value='';renderRecent();renderRecords();window.MemoirLibrary?.render();}
  function headingCopy(){const person=elder();return person?`${escapeText(person.name)} 님의 이야기`:'이야기 주인공 등록';}
  function renderPrepare(){
    const data=snapshot(),person=elder();
    const nameForm=`<form id="speaker-form" class="role-name-form"><label for="speaker-name">이야기 주인공 이름</label><div class="role-name-actions"><input id="speaker-name" name="name" maxlength="30" required autocomplete="off" placeholder="이름 하나만 적어주세요"><button type="submit" class="button outline">이름 등록</button></div><p class="role-error" id="speaker-error" role="status"></p></form>`;
    prepare.querySelector('.role-content').innerHTML=`<p class="role-intro">계정은 이야기를 모으는 사람, 이야기 주인공은 삶을 들려주는 사람입니다.</p><div class="role-account-strip"><span>이야기를 모으는 계정 <strong>${data.user?escapeText(data.user.name):'로그인 전 · 예시 둘러보기'}</strong></span><button type="button" class="text-button" data-login>${data.user?'계정 보기':'가상 로그인'}</button></div><div class="panel role-preparation"><h2>${person?'이야기 주인공':'먼저, 이름을 알려주세요'}</h2>${data.elders.length?`<div class="role-speakers" role="group" aria-label="이야기 주인공 선택">${data.elders.map(item=>`<button type="button" class="button outline" data-speaker="${escapeText(item.elder_id)}" aria-pressed="${item.elder_id===data.selectedElderId}">${escapeText(item.name)}</button>`).join('')}</div><details class="role-add-speaker"><summary>다른 분 이름 추가</summary>${nameForm}</details>`:nameForm}${person?`<div class="role-topic"><label for="prepared-topic">이번에 나눌 주제</label><select id="prepared-topic">${topics.map(topic=>`<option${run?.topic===topic?' selected':''}>${topic}</option>`).join('')}</select></div><p class="role-subcopy">${headingCopy()}를 담습니다. 떠오르는 기억부터 편하게 들려주세요.</p><button type="button" class="button primary role-main-action" data-role="start-local">${run&&!run.completed&&run.elderId===person.elder_id?'이어서 이야기하기':'이 기기에서 시작하기'} ${icons('arrow')}</button><div class="role-secondary-actions"><button type="button" class="text-button" data-role="issue">초대 주소 준비하기</button><button type="button" class="text-button" data-go="invitations">준비한 초대 보기</button></div>`:''}</div><p class="role-preview-note">화면 검토용입니다. 이름·초대·입력한 이야기는 이 탭에서만 유지됩니다.</p><details class="role-review-tools"><summary>다른 상태 검토</summary><a href="?speakers=empty#prepare">화자 0명인 첫 이용 예시 열기</a></details>`;
  }
  function renderInterrupted(){
    const entries=interrupted.filter(item=>item.elderId===snapshot().selectedElderId);
    if(!entries.length)return;
    const details=document.createElement('details');details.className='role-interrupted panel';
    details.innerHTML='<summary>중단된 초대에서 적은 글 확인</summary><p>초대는 중단됐습니다. 적은 글은 이 탭에서 확인할 수 있어요. 완료한 이야기나 엽서로 처리하지 않습니다.</p>'+entries.map(item=>`<pre>${escapeText(item.text)}</pre>`).join('');
    prepare.querySelector('.role-content').append(details);
  }
  function renderInvitations(){
    const data=snapshot();
    invitations.querySelector('.role-content').innerHTML=`<p class="role-intro">초대 주소는 준비한 직후 한 번만 보여드립니다. 주소를 복사해도 전달이 끝난 것은 아닙니다.</p>${issued?`<div class="panel role-issued" role="region" aria-labelledby="issued-heading"><h2 id="issued-heading">초대 주소가 준비됐어요</h2><p>지금 주소를 복사해 따로 전해주세요. 이 화면을 떠나면 다시 표시하지 않습니다.</p><label for="issued-address">이번에 준비한 예시 주소</label><input id="issued-address" readonly value="${escapeText(issued.address)}"><div class="role-issued-actions"><button type="button" class="button primary" data-role="copy-address">주소 복사</button><button type="button" class="button outline" data-role="preview-invite">초대받는 화면 미리보기</button></div><p id="copy-result" role="status">실제 초대 권한이 없는 이 탭 전용 예시 주소입니다.</p></div>`:''}<div class="role-invitation-list">${data.invitations.length?data.invitations.map(inv=>{const person=data.elders.find(item=>item.elder_id===inv.elder_id);return `<article class="panel role-invitation"><div><span class="pill">${labels[inv.status]||'확인 필요'}</span><h2>${escapeText(person?.name||'이야기 주인공')} · ${escapeText(inv.topic)}</h2><p>${inv.status==='in_progress'?'이야기를 나누고 있어요.':inv.status==='completed'?'완료한 회차입니다. 새 이야기는 새로 준비해주세요.':'이 회차의 상태만 표시합니다.'}</p></div><div class="role-invite-actions">${store.canRevoke(inv)?`<button type="button" class="button outline" data-revoke="${inv.id}">초대 취소</button>`:''}${store.canReissue(inv)?`<button type="button" class="text-button" data-reissue="${inv.id}">주소 다시 준비</button>`:''}</div></article>`;}).join(''):'<div class="panel role-empty"><h2>아직 준비한 초대가 없어요</h2><p>이야기 주인공과 주제를 정한 뒤 초대를 준비해주세요.</p></div>'}</div><button type="button" class="button outline" data-go="prepare">이야기 준비로 돌아가기</button><details class="role-review-tools"><summary>초대 상태 검토</summary><p>아래 버튼은 시작 전·진행 중·기한 지남·취소·완료 상태의 예시를 더합니다.</p><button type="button" class="text-button" data-role="seed-invites">다섯 가지 예시 상태 보기</button></details>`;
  }
  function enterGuest(reference){issued=null;guestReference=reference;guest=true;document.body.classList.add('role-guest');const result=store.invitationByReference(reference);show('invite');renderEntry(result);}
  function renderEntry(result=store.invitationByReference(guestReference)){
    const inv=result.invitation,person=snapshot().elders.find(item=>item.elder_id===inv?.elder_id);
    const completed=inv?.status==='completed';
    entry.querySelector('h1').textContent=completed?'오늘 이야기, 고맙습니다':result.ok?'준비된 이야기를 만나보세요':'이 주소로는 시작할 수 없어요';
    entry.querySelector('.role-content').innerHTML=`<div class="panel role-guest-card"><span class="eyebrow">내말싸미 · 초대 화면 예시</span>${result.ok?`<h2>${escapeText(person?.name||'이야기 주인공')} 님의 이야기</h2><p class="role-guest-topic">${escapeText(inv.topic)}</p><p>떠오르는 기억부터 천천히 들려주세요.</p><button type="button" class="button primary role-main-action" data-role="start-invite">${inv.status==='in_progress'?'이어서 이야기하기':'이야기 시작하기'} ${icons('arrow')}</button>`:`<h2>${completed?'함께 나눈 이야기를 확인했어요':result.error==='superseded'?'새 주소가 준비되었어요':inv?.status==='revoked'?'취소된 초대예요':inv?.status==='expired'?'초대 기한이 지났어요':'사용할 수 없는 예시 주소예요'}</h2><p>${completed?'이야기는 이번 미리보기에 남겼습니다. 엽서는 이야기를 모으는 사람이 따로 만들 수 있어요.':'초대를 준비한 분에게 새 주소를 요청해주세요.'}</p>`}<p class="role-preview-note">실제 저장·녹음이 연결되지 않은 화면 예시입니다.</p></div><details class="role-review-tools"><summary>시안 검토 화면</summary><button type="button" class="text-button" data-role="leave-guest">초대 관리 시안으로 돌아가기</button></details>`;
    entry.querySelector('h1').focus({preventScroll:true});
    if(completed&&guestStory?.invitationId===inv.id){const article=document.createElement('article');article.className='panel role-guest-story';article.innerHTML=`<h2>오늘 나눈 이야기</h2>${guestStory.body.split('\n\n').map(paragraph=>`<p>${escapeText(paragraph)}</p>`).join('')}`;entry.querySelector('.role-guest-card').after(article);}
  }
  function begin(inv=null){
    const person=inv?snapshot().elders.find(item=>item.elder_id===inv.elder_id):elder();
    if(!person)return;
    if(hasDraft()&&run?.elderId!==person.elder_id){toast('작성 중인 이야기를 먼저 마쳐주세요. 이야기 주인공을 섞지 않고 이어갈게요.');return;}
    const needsNewRun=!run||run.completed||run.elderId!==person.elder_id||run.invitationId!==(inv?.id||null);
    if(needsNewRun&&hasDraft()){toast('작성 중인 이야기를 먼저 마친 뒤 새 회차를 시작해주세요.');return;}
    if(inv){const result=store.startInvitation(inv.id);if(!result.ok){renderEntry(result);return;}}
    if(!run||run.completed||run.elderId!==person.elder_id||run.invitationId!==(inv?.id||null)){
      if(hasDraft()){toast('작성 중인 이야기를 먼저 마친 뒤 새 회차를 시작해주세요.');return;}
      state.interviewTopic=inv?.topic||$('#prepared-topic')?.value||topics[0];
      state.interviewId=interviewCompletion.beginInterview();state.interviewCompleted=false;state.question=0;state.answers=[];$('#answer-text').value='';renderQuestion();setInterviewMode('reading');
      run={elderId:person.elder_id,topic:inv?.topic||$('#prepared-topic')?.value||topics[0],invitationId:inv?.id||null,completed:false};
    }
    navigate('interview');
    let label=$('#interview-speaker-label');if(!label){label=document.createElement('p');label.id='interview-speaker-label';label.className='role-current-speaker';$('.interview-page-heading').append(label);}
    label.textContent=`이야기 주인공: ${person.name} · ${run.topic}`;$('.studio-topline .pill').textContent=run.topic;
  }
  function showIssued(result){if(!result.ok){toast('지금은 주소를 다시 준비할 수 없어요.');return;}issued={address:result.address,id:result.invitation.id};if(location.hash==='#invitations'){renderInvitations();const heading=$('#issued-heading');heading.tabIndex=-1;heading.focus({preventScroll:true});}else navigate('invitations');}
  document.addEventListener('submit',event=>{
    if(event.target.id!=='speaker-form')return;event.preventDefault();
    if(hasDraft()){toast('작성 중인 이야기를 먼저 마친 뒤 다른 분을 등록해주세요.');return;}
    const result=store.addElder($('#speaker-name').value);
    if(!result.ok){$('#speaker-error').textContent=result.error==='duplicate_name'?'이미 등록한 이름이에요. 위에서 선택해주세요.':'이름을 확인해주세요.';return;}
    refreshOwnership();renderPrepare();prepare.querySelector('[data-role="start-local"]')?.focus();
  });
  document.addEventListener('click',async event=>{
    const button=event.target.closest('button');if(!button)return;
    if(button.dataset.speaker){if(hasDraft()&&run?.elderId!==button.dataset.speaker){toast('작성 중인 이야기를 먼저 마친 뒤 다른 분을 선택해주세요.');return;}store.selectElder(button.dataset.speaker);refreshOwnership();renderPrepare();prepare.querySelector(`[data-speaker="${button.dataset.speaker}"]`)?.focus();return;}
    if(button.dataset.revoke){revokeId=button.dataset.revoke;const inv=snapshot().invitations.find(item=>item.id===revokeId);$('#revoke-description').textContent=inv.status==='in_progress'?'지금 나누는 인터뷰가 중단됩니다. 이 주소로는 다시 시작할 수 없어요.':'이 주소로는 이야기를 시작할 수 없게 됩니다.';revokeDialog.showModal();return;}
    if(button.dataset.reissue){showIssued(store.reissue(button.dataset.reissue));toast('이전 주소는 사용할 수 없어요. 새 주소를 따로 전해주세요.');return;}
    switch(button.dataset.role){
      case 'start-local':begin();break;
      case 'issue':if(!snapshot().user){window.MemoirLogin.open();toast('예시 계정으로 로그인한 뒤 초대를 준비해주세요.');return;}showIssued(store.issueInvitation({elderId:elder()?.elder_id,topic:$('#prepared-topic').value}));break;
      case 'copy-address':{const current=issued;if(!current)return;try{await navigator.clipboard.writeText(current.address);if(issued===current)$('#copy-result').textContent='주소를 복사했어요. 초대할 분에게 따로 전해주세요.';}catch{if(issued===current){$('#issued-address').select();$('#copy-result').textContent='자동 복사가 되지 않았어요. 선택된 주소를 직접 복사해주세요.';}}break;}
      case 'preview-invite':if(issued)location.hash=new URL(issued.address).hash;break;
      case 'keep-invite':revokeDialog.close();break;
      case 'confirm-revoke':{const result=store.revoke(revokeId);if(result.ok)interruptRun(revokeId);revokeDialog.close();issued=null;renderInvitations();invitations.querySelector('h1').focus();break;}
      case 'seed-invites':store.seedReviewInvitations();renderInvitations();break;
      case 'start-invite':{const result=store.invitationByReference(guestReference);if(result.ok)begin(result.invitation);else renderEntry(result);break;}
      case 'leave-guest':guest=false;guestReference='';document.body.classList.remove('role-guest');navigate('invitations');break;
    }
  });
  window.addEventListener('memoir:preview-auth',event=>{if(event.detail.authenticated)store.login();else store.logout();if(location.hash==='#prepare')renderPrepare();});
  window.addEventListener('memoir:before-screen',event=>{if(event.detail.screen!=='invitations'){issued=null;invitations.querySelector('.role-issued')?.remove();}});
  window.addEventListener('memoir:screen',event=>{
    if(event.detail.screen==='prepare'){renderPrepare();renderInterrupted();}
    if(event.detail.screen==='invitations')renderInvitations();
    context.hidden=guest||event.detail.screen!=='home';
    const person=elder();
    context.innerHTML=`<span class="role-context-label">이야기 주인공</span><span class="role-name-action"><strong class="role-context-name">${escapeText(person?.name||'아직 등록하지 않았어요')}</strong>${changeMarkup(person)}</span>`;
  });
  window.RolePreview={store,renderIdentity,currentElderId:()=>run&&!run.completed&&location.hash==='#interview'?run.elderId:snapshot().selectedElderId,canEnterInterview:validRun,canFinish:()=>!run?.invitationId||validRun(),isGuest:()=>guest,isInviteHash:hash=>/^#invite-preview-/.test(hash),enterGuest,
    complete(story){const elderId=run?.elderId||snapshot().selectedElderId;storyOwners.set(story.id,elderId);storyTopics.set(story.id,run?.topic||topics[0]);if(run){run.completed=true;if(run.invitationId)store.completeInvitation(run.invitationId);}if(guest){guestStory={invitationId:run?.invitationId,body:story.body};setInterviewMode('idle');renderEntry();navigate('invite');return true;}return false;}
  };
  const storyOwners=new Map();
  const storyTopics=new Map();
  window.RolePreview.storyElderId=id=>storyOwners.get(id)||'preview-self';
  window.RolePreview.storyCategory=id=>({가족:'family','삶과 일':'life'})[storyTopics.get(id)]||'childhood';
  refreshOwnership();
  if(window.RolePreview.isInviteHash(location.hash))enterGuest(location.hash);
  else if(location.hash==='#invite')enterGuest('');
  else show(location.hash==='#interview'?'prepare':location.hash.slice(1)||'home');
}());
