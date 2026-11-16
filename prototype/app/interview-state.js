(function (root, factory) {
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.InterviewVisualState=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const phases={
    reading:{radioState:'reading',status:'질문을 확인해 주세요',action:'말하기 시작',hint:'준비되시면 편하게 말씀해 주세요.',icon:'mic'},
    listening:{radioState:'listening',status:'말씀하시는 차례예요',action:'잠시 쉬기',hint:'천천히, 편하게 말씀하셔도 괜찮아요.',icon:'pause'},
    paused:{radioState:'paused',status:'잠시 쉬어가요',action:'다시 말하기',hint:'준비되시면 다시 시작해 주세요.',icon:'play'},
    processing:{radioState:'processing',status:'이야기를 정리하고 있어요',action:'정리하는 중',hint:'다음 이야기를 준비하고 있어요.',icon:'spark'},
    text:{radioState:'idle',status:'글로 이야기하는 중',action:'말하기 시작',hint:'떠오르는 기억을 천천히 적어주세요.',icon:'mic'},
    idle:{radioState:'idle',status:'함께한 이야기',action:'말하기 시작',hint:'다음 기억도 함께 나눠요.',icon:'mic'},
  };
  function visualFor(phase){const value=phases[phase]||phases.idle;return{...value,onAir:phase==='listening',headphones:phase==='reading'};}
  function nextVoicePhase(phase){return({reading:'listening',listening:'paused',paused:'listening',text:'reading',processing:'processing',idle:'reading'})[phase]||'reading';}
  function fromSnapshot(snapshot){
    const phaseFor={SPEAKING:'reading',LISTENING:'listening',PROCESSING:'processing',CLOSED:'idle'};
    const state=snapshot&&typeof snapshot==='object'?snapshot.state:null;
    if(typeof state!=='string'||!Object.prototype.hasOwnProperty.call(phaseFor,state))return null;
    return{phase:phaseFor[state],serverState:state,closed:state==='CLOSED'};
  }
  function commandFor(action){
    if(typeof action!=='string')return{supported:false,reason:'unknown_action'};
    const commands={
      'turn-done':{supported:true,method:'POST',path:'/done',scope:'turn'},
      'send-text':{supported:true,method:'POST',path:'/speech',scope:'turn'},
      'tts-done':{supported:true,method:'POST',path:'/tts-done',scope:'turn'},
      abort:{supported:true,method:'POST',path:'/abort',scope:'session'},
    };
    if(Object.prototype.hasOwnProperty.call(commands,action))return{...commands[action]};
    const unavailable={pause:'pause_requires_server_contract',resume:'resume_requires_server_contract',finish:'finish_requires_server_contract'};
    return{supported:false,reason:Object.prototype.hasOwnProperty.call(unavailable,action)?unavailable[action]:'unknown_action'};
  }
  return{visualFor,nextVoicePhase,fromSnapshot,commandFor};
});
