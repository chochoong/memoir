'use strict';

// Offline only: source fingerprints, local unit tests and syntax. No API/auth/DB.
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const reviewRoot=__dirname;
const repoRoot=path.resolve(reviewRoot,'../..');
const baseline=JSON.parse(fs.readFileSync(path.join(reviewRoot,'server-baseline.json'),'utf8'));
const sha=value=>crypto.createHash('sha256').update(value.replace(/\r\n/g,'\n')).digest('hex');
let failed=false;

for(const entry of baseline.sources){
  const file=path.resolve(repoRoot,entry.path);
  if(!file.startsWith(repoRoot+path.sep))throw new Error('Baseline path outside repository');
  if(!fs.existsSync(file)||sha(fs.readFileSync(file,'utf8'))!==entry.sha256){
    console.error(`REVIEW REQUIRED: server source changed: ${entry.path}`);
    failed=true;
  }
}
if(failed){
  console.error('Recheck the changed contract before updating the fingerprint. No requests were sent.');
  process.exitCode=1;
}else{
  console.log(`Source baseline matched: ${baseline.commit.slice(0,7)} (${baseline.sources.length} files; local snapshot only)`);
  const files=fs.readdirSync(reviewRoot).sort();
  const tests=files.filter(name=>name.endsWith('.test.cjs')).map(name=>path.join(reviewRoot,name));
  const result=spawnSync(process.execPath,['--test',...tests],{cwd:repoRoot,stdio:'inherit'});
  if(result.error)throw result.error;
  if(result.status!==0)failed=true;
  const scripts=files.filter(name=>/\.(?:js|cjs)$/.test(name));
  for(const name of scripts){
    const check=spawnSync(process.execPath,['--check',path.join(reviewRoot,name)],{stdio:'pipe',encoding:'utf8'});
    if(check.error)throw check.error;
    if(check.status!==0){failed=true;console.error(check.stderr||`Syntax check failed: ${name}`);}
  }
  console.log(`Syntax checked: ${scripts.length} files`);
  console.log(failed?'Offline checks failed.':'Offline checks passed. Live OAuth/API/audio/DB/deployment remain unverified.');
  process.exitCode=failed?1:0;
}
