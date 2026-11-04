const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {EventEmitter}=require('node:events');
const source=readFileSync(path.join(__dirname,'../scripts/smoke.cjs'),'utf8');
function fixture(result,raw){
  const child=new EventEmitter(),logs=[],process={env:{PRIVATE_KEY:'secret-sentinel'},exitCode:0};
  child.kill=()=>{};let timeout;
  const stubs={'node:child_process':{spawn:()=>child},'node:path':path,'node:os':{tmpdir:()=>'/private-user'},
    'node:fs':{mkdtempSync:()=>'/private-user/profile-sentinel',existsSync:()=>true,readFileSync:()=>raw??JSON.stringify(result)},electron:'fake-electron'};
  vm.runInNewContext(source,{__dirname:path.join(__dirname,'../scripts'),require:name=>stubs[name],process,
    setTimeout:callback=>{timeout=callback;return 1;},clearTimeout:()=>{},console:{error:(...args)=>logs.push(args),log:(...args)=>logs.push(args)}});
  return {child,logs,process,timeout:()=>timeout()};
}
for(const mode of ['failure','timeout','error','success'])test('smoke '+mode+' logs only a bounded summary',()=>{
  const f=fixture({status:mode==='success'?'passed':'failed',error:'secret-sentinel',checks:['secret-sentinel']});
  if(mode==='error')f.child.emit('error',new Error('secret-sentinel'));
  else {if(mode==='timeout')f.timeout();f.child.emit('exit',mode==='success'?0:1,null);}
  assert.equal(f.process.exitCode,mode==='success'?0:1);
  const output=JSON.stringify(f.logs);
  assert.doesNotMatch(output,/secret-sentinel|private-user|profile-sentinel/);
  assert.match(output,mode==='success'?/smoke passed/:/smoke failed|could not start/);
});
test('malformed smoke reports fail without leaking their contents',()=>{
  const f=fixture(null,'secret-sentinel');
  assert.doesNotThrow(()=>f.child.emit('exit',0,null));
  assert.equal(f.process.exitCode,1);
  assert.doesNotMatch(JSON.stringify(f.logs),/secret-sentinel|private-user/);
});
