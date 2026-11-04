const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {EventEmitter}=require('node:events');
const {PassThrough}=require('node:stream');
const {createBackendManager,validateIdentity,launchSpec,sourceBuildId}=require('../electron/backend.cjs');

function fixture(t){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'vellum-backend-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  return root;
}

test('a healthy service is reused only for the selected workspace and exact backend build',t=>{
  const root=fixture(t), other=fixture(t);
  const identity={service:'vellum',protocol_version:1,workspace_root:root,build_id:'a'.repeat(64)};
  validateIdentity(identity,root,identity.build_id);
  assert.throws(()=>validateIdentity({...identity,service:'other'},root,identity.build_id),/another service/);
  assert.throws(()=>validateIdentity(identity,other,identity.build_id),/another service/);
  assert.throws(()=>validateIdentity(identity,root,'b'.repeat(64)),/different Vellum backend version/);
});

test('packaged startup resolves its bundled Python independently of the selected data folder',t=>{
  const root=fixture(t), workspace=fixture(t), runtime=path.join(root,'backend-runtime');
  fs.mkdirSync(path.join(runtime,'python'),{recursive:true});
  fs.mkdirSync(path.join(runtime,'app'),{recursive:true});
  fs.writeFileSync(path.join(runtime,'python','python.exe'),'fixture');
  fs.writeFileSync(path.join(runtime,'app','desktop-backend.json'),JSON.stringify({protocol_version:1,build_id:'a'.repeat(64)}));
  const spec=launchSpec({packaged:true,resourcesPath:root,workspaceRoot:workspace});
  assert.equal(spec.python,path.join(runtime,'python','python.exe'));
  assert.equal(spec.workspaceRoot,workspace);
  assert.equal(spec.codeRoot,path.join(runtime,'app'));
});

test('data and credentials are absent from backend content identity',t=>{
  const root=fixture(t);
  fs.mkdirSync(path.join(root,'backend/agent'),{recursive:true});
  fs.writeFileSync(path.join(root,'backend/agent/example.py'),'print(1)');
  const before=sourceBuildId(root);
  fs.mkdirSync(path.join(root,'data'),{recursive:true});
  fs.writeFileSync(path.join(root,'data/auth.json'),'private');
  fs.writeFileSync(path.join(root,'.env'),'PRIVATE=private');
  assert.equal(sourceBuildId(root),before);
  fs.writeFileSync(path.join(root,'backend/agent/example.py'),'print(2)');
  assert.notEqual(sourceBuildId(root),before);
});

test('the app never stops a reused backend',async t=>{
  const root=fixture(t), identity={service:'vellum',protocol_version:1,workspace_root:root,build_id:'a'.repeat(64),pid:100};
  let spawns=0;
  const manager=createBackendManager({workspaceRoot:root,buildId:identity.build_id},{probe:async()=>identity,spawnProcess:()=>{spawns++;}});
  assert.equal((await manager.start()).reused,true);
  await manager.stop();
  assert.equal(spawns,0);
});

test('first launch waits for its own child and sends a private graceful-stop command',async t=>{
  const root=fixture(t), child=new EventEmitter();
  child.pid=2345;child.stdin=new PassThrough();
  let stop='';child.stdin.on('data',data=>{stop+=data;});
  child.stdin.on('finish',()=>{child.emit('exit',0);});
  let spawned=false,launchId;
  const spec={workspaceRoot:root,codeRoot:root,python:path.join(root,'python.exe'),buildId:'a'.repeat(64)};
  const identity={service:'vellum',protocol_version:1,workspace_root:root,build_id:spec.buildId,pid:child.pid+1};
  const manager=createBackendManager(spec,{
    probe:async()=>spawned?{...identity,launch_id:launchId}:null,occupied:async()=>false,
    spawnProcess:(executable,args,options)=>{
      assert.equal(executable,spec.python);
      assert.deepEqual(args,['-u','-m','agent.desktop_entry']);
      assert.equal(options.env.VELLUM_WORKSPACE_ROOT,root);
      assert.equal(options.windowsHide,true);
      assert.equal(options.cwd,root);
      launchId=options.env.VELLUM_DESKTOP_LAUNCH_ID;
      assert.match(launchId,/^[a-f0-9]{32}$/);
      spawned=true;return child;
    },
  });
  assert.equal((await manager.start()).reused,false);
  assert.equal(manager.owned,true);
  await manager.stop();
  assert.equal(stop,'stop\n');
  assert.equal(manager.owned,false);
});

test('an occupied unknown service is neither reused nor replaced',async t=>{
  const root=fixture(t);
  const manager=createBackendManager({workspaceRoot:root,buildId:'a'.repeat(64)},{
    probe:async()=>null,occupied:async()=>true,spawnProcess:()=>assert.fail('Must not spawn against an occupied port'),
  });
  await assert.rejects(manager.start(),/will not stop or replace/);
});
