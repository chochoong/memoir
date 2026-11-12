(function(root,factory){
  'use strict';
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./service-contract.js'));
  else root.MemoirPreviewService=factory(root.MemoirServiceContract);
})(typeof globalThis!=='undefined'?globalThis:this,function(contract){
  'use strict';
  // A local fixture transport, not an API client. No identity, network or storage.
  const jobs=new Map();
  let nextJob=0;
  const copy=value=>JSON.parse(JSON.stringify(value));
  const uuid=/^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i;

  function postcard(session,presentation={}){
    return contract.postcardView(session,session.postcard,presentation);
  }

  function createMemoirJob(records,context={}){
    if(!Array.isArray(records)||records.length<3)throw new TypeError('preview requires three sessions');
    if(!context.elder_id||records.some(record=>record.elder_id!==context.elder_id))throw new TypeError('preview speaker mismatch');
    if(records.some(record=>!uuid.test(record.session_id)||typeof record.body!=='string'||!record.body.trim()))throw new TypeError('invalid preview session');
    if(new Set(records.map(record=>record.session_id.toLowerCase())).size!==records.length)throw new TypeError('duplicate preview session');
    // develop memoir.merge uses session creation time, never click order or
    // postcard publication time. Preserve microseconds when ISO dates have them.
    const timed=records.map(record=>{
      const stamp=record.sourceSession?record.sourceSession.created_at:record.created_at;
      const millis=typeof stamp==='string'?Date.parse(stamp):NaN;
      if(!Number.isFinite(millis))throw new TypeError('missing preview session time');
      const fraction=stamp.match(/\.(\d{1,6})(?:Z|[+-]\d{2}:\d{2})$/)?.[1]||'';
      return{record,millis,micros:Number(fraction.padEnd(6,'0').slice(3))};
    }).sort((a,b)=>a.millis-b.millis||a.micros-b.micros);
    if(timed.some((item,index)=>index&&item.millis===timed[index-1].millis&&item.micros===timed[index-1].micros))throw new TypeError('ambiguous preview session time');
    const job={job_id:`preview-job-${++nextJob}`,status:'running',stage:'analysis'};
    jobs.set(job.job_id,{records:copy(timed.map(item=>item.record)),context:copy(context),response:null});
    return copy(job);
  }

  function completeMemoirJob(job){
    const saved=jobs.get(job?.job_id);
    if(!saved)throw new TypeError('unknown preview job');
    if(!saved.response){
      const chapters=saved.records.map((record,index)=>({
        no:index+1,title:record.title,status:'ready',
        paragraphs:record.body.split(/\n\s*\n/).filter(text=>text.trim()).map(text=>({sentences:[{text,turns:[]}]})),
      }));
      saved.response={job_id:job.job_id,status:'done',stage:'complete',result:{
        status:'ready',title:saved.context.title||'나의 이야기',style:'spoken',chapters,
        body:chapters.flatMap(ch=>ch.paragraphs.flatMap(p=>p.sentences.map(s=>s.text))).join('\n'),
        sources:[],to_confirm:[],verification:{state:'not_run'},
        run:{session_ids:saved.records.map(record=>record.session_id),chapters_requested:chapters.length},
      }};
    }
    // The fixture uses spoken as its server-shaped value. UI style choices are
    // presentation only; no unsupported style is submitted or claimed generated.
    return copy(saved.response);
  }
  return{postcard,createMemoirJob,completeMemoirJob};
});
