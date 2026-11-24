const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const core=require('../electron/install-core.cjs');
const {createUpdater,isInstalledCopy}=require('../electron/updater.cjs');

function publish(feed,id,sequence,marker){
  const dir=path.join(feed,'releases',id);
  fs.mkdirSync(path.join(dir,'resources'),{recursive:true});
  fs.writeFileSync(path.join(dir,'Vellum.exe'),'exe-'+marker);
  fs.writeFileSync(path.join(dir,'resources','app.asar'),'asar-'+marker);
  core.writeJSONAtomic(path.join(feed,'latest.json'),{id,sequence});
}

function sandbox(t){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'vellum-update-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  return {feed:path.join(root,'feed'),install:path.join(root,'Programs','Vellum')};
}

test('installing a release makes it current behind a stable junction',async t=>{
  const {feed,install}=sandbox(t);
  publish(feed,'r1',1,'one');
  const exe=await core.installRelease(core.readLatest(feed),{root:install});
  assert.equal(exe,path.join(install,'current','Vellum.exe'));
  assert.equal(fs.readFileSync(exe,'utf8'),'exe-one');
  assert.equal(path.basename(fs.realpathSync(path.join(install,'current'))),'app-r1');
  assert.equal(core.readJSON(path.join(install,'current','resources',core.BUILD_FILE)).id,'r1');
  assert.ok(isInstalledCopy({execPath:exe,root:install}));
  assert.ok(!isInstalledCopy({execPath:path.join(feed,'releases','r1','Vellum.exe'),root:install}));
});

test('a newer published build shows as ready, installs, and relaunches into it',async t=>{
  const {feed,install}=sandbox(t);
  publish(feed,'r1',1,'one');
  await core.installRelease(core.readLatest(feed),{root:install});
  const states=[],relaunches=[];let quit=0;
  const app={isPackaged:true,relaunch:options=>relaunches.push(options),quit:()=>quit++};
  const updater=createUpdater({app,feed,root:install,build:{id:'r1',sequence:1},enabled:true,broadcast:s=>states.push(s.status)});
  assert.equal(updater.check().status,'idle');
  publish(feed,'r2',2,'two');
  assert.deepEqual(updater.check(),{status:'ready',current:'r1',available:'r2',progress:null,error:null});
  await updater.install();
  assert.ok(states.includes('installing'));
  assert.equal(relaunches.length,1);
  assert.equal(relaunches[0].execPath,path.join(install,'current','Vellum.exe'));
  assert.equal(quit,1);
  assert.equal(fs.readFileSync(path.join(install,'current','Vellum.exe'),'utf8'),'exe-two');
  // The previous build stays for rollback; older ones are pruned.
  publish(feed,'r3',3,'three');
  await core.installRelease(core.readLatest(feed),{root:install});
  core.pruneInstalled(install);
  assert.deepEqual(fs.readdirSync(install).filter(n=>n.startsWith('app-')).sort(),['app-r2','app-r3']);
});

test('an older or incomplete release never offers an update',t=>{
  const {feed,install}=sandbox(t);
  publish(feed,'r1',1,'one');
  const app={isPackaged:true,relaunch(){},quit(){}};
  const updater=createUpdater({app,feed,root:install,build:{id:'r5',sequence:5},enabled:true});
  assert.equal(updater.check().status,'idle');
  fs.rmSync(path.join(feed,'releases','r1','Vellum.exe'));
  core.writeJSONAtomic(path.join(feed,'latest.json'),{id:'r1',sequence:9});
  assert.equal(updater.check().status,'idle');
});

test('development runs never update themselves',()=>{
  const updater=createUpdater({app:{isPackaged:false},build:null});
  assert.equal(updater.check().status,'unavailable');
});
