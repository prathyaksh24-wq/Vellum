const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {configureWorkspaceProfile} = require('../electron/workspace-profile.cjs');

test('profile cutover preserves UI storage and the original profile, without copying old runtime state', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(),'vellum-profile-test-'));
  const previous = path.join(root,'previous'), directory = path.join(root,'local');
  const store = 'Partitions/vellum-workspace/Local Storage';
  fs.mkdirSync(path.join(previous,store),{recursive:true});
  fs.writeFileSync(path.join(previous,store,'fixture'),'saved UI preference');
  fs.writeFileSync(path.join(previous,'Local State'),'old runtime state');
  fs.mkdirSync(path.join(previous,'Cache'));
  let selected;
  const app = {getPath:() => previous,setPath:(name,value) => {assert.equal(name,'userData');selected=value;}};
  configureWorkspaceProfile(app,{directory});
  assert.equal(selected,directory);
  assert.equal(fs.readFileSync(path.join(directory,store,'fixture'),'utf8'),'saved UI preference');
  assert.equal(fs.readFileSync(path.join(previous,store,'fixture'),'utf8'),'saved UI preference');
  assert.equal(fs.existsSync(path.join(directory,'Local State')),false);
  assert.equal(fs.existsSync(path.join(directory,'Cache')),false);
  fs.writeFileSync(path.join(directory,store,'fixture'),'new UI preference');
  configureWorkspaceProfile(app,{directory});
  assert.equal(fs.readFileSync(path.join(directory,store,'fixture'),'utf8'),'new UI preference');
});

test('profile selection preserves default startup and rejects relative overrides', () => {
  const app={getPath:()=>{throw Error('unused');},setPath:()=>{throw Error('unused');}};
  configureWorkspaceProfile(app,{});
  assert.throws(()=>configureWorkspaceProfile(app,{directory:'relative'}),/absolute/);
});

test('packaged Windows startup migrates to the verified per-user home profile', () => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'vellum-installed-profile-test-'));
  const previous=path.join(root,'Roaming','Vellum');
  fs.mkdirSync(path.join(previous,'Local Storage'),{recursive:true});
  fs.writeFileSync(path.join(previous,'Local Storage','preference'),'retained');
  let selected;
  const app={isPackaged:true,getPath:name=>name==='home'?root:previous,
    setPath:(name,value)=>{assert.equal(name,'userData');selected=value;}};
  configureWorkspaceProfile(app,{platform:'win32'});
  assert.equal(selected,path.join(root,'.vellum','desktop-profile'));
  assert.equal(fs.readFileSync(path.join(selected,'Local Storage','preference'),'utf8'),'retained');
  assert.equal(fs.existsSync(path.join(previous,'Local Storage','preference')),true);
});

