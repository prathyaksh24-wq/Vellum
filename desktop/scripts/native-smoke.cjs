const {spawn}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'../../.test-data');
fs.mkdirSync(root,{recursive:true});
const profile=fs.mkdtempSync(path.join(root,'native-electron-'));
const env={...process.env,VELLUM_NATIVE_TEST_ROOT:profile,ELECTRON_ENABLE_LOGGING:'1'};
delete env.ELECTRON_RUN_AS_NODE;
const child=spawn(require('electron'),[path.join(__dirname,'../test/native-smoke-app.cjs')],{env,stdio:'inherit',windowsHide:true});
let timedOut=false;
const timeout=setTimeout(()=>{timedOut=true;child.kill();},90000);
child.on('exit',(code,signal)=>{
  clearTimeout(timeout);
  const file=path.join(profile,'result.json');
  const passed=fs.existsSync(file) && JSON.parse(fs.readFileSync(file,'utf8')).passed;
  if(timedOut || signal || code!==0 || !passed){console.error('Native browser smoke failed:',{code,signal,timedOut,profile});process.exitCode=1;}
  else console.log('Native browser smoke passed.');
});
