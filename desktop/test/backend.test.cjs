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
    probe:async()=>null,occupied:async()=>true,busyWaitMs:10,pollMs:1,findStalled:()=>null,
    terminate:()=>assert.fail('Must not stop an unknown service'),spawnProcess:()=>assert.fail('Must not spawn against an occupied port'),
  });
  await assert.rejects(manager.start(),/will not stop or replace/);
});

function ownedBackend(t,options={}){
  const root=fixture(t), child=new EventEmitter();
  child.pid=4567;child.stdin=new PassThrough();
  let launchId,spawned=false;
  const spec={workspaceRoot:root,codeRoot:root,python:path.join(root,'python.exe'),buildId:'b'.repeat(64)};
  const identity={service:'vellum',protocol_version:1,workspace_root:root,build_id:spec.buildId};
  const manager=createBackendManager(spec,{
    probe:async()=>spawned?{...identity,launch_id:launchId}:null,occupied:async()=>false,
    spawnProcess:(_,__,opts)=>{launchId=opts.env.VELLUM_DESKTOP_LAUNCH_ID;spawned=true;return child;},
    ...options,
  });
  return {manager,child};
}

test('a backend that cannot finish shutting down is force-stopped instead of blocking quit',async t=>{
  const killed=[];
  const {manager,child}=ownedBackend(t,{stopTimeoutMs:20,terminate:pid=>{killed.push(pid);child.emit('exit',1);}});
  await manager.start();
  await manager.stop();
  assert.deepEqual(killed,[4567]);
  assert.equal(manager.owned,false);
});

test('an unexpected backend exit is reported so the host can restart it',async t=>{
  const exits=[];
  const {manager,child}=ownedBackend(t,{onExit:code=>exits.push(code)});
  await manager.start();
  child.emit('exit',3);
  assert.deepEqual(exits,[3]);
});

test('an intentional stop is not reported as a crash',async t=>{
  const exits=[];
  const {manager,child}=ownedBackend(t,{onExit:code=>exits.push(code)});
  child.stdin.on('finish',()=>child.emit('exit',0));
  await manager.start();
  await manager.stop();
  assert.deepEqual(exits,[]);
});

test('a hung Vellum backend holding the port is replaced; an unknown service is not',async t=>{
  const root=fixture(t);
  let held=true;const killed=[];
  const spec={workspaceRoot:root,codeRoot:root,python:path.join(root,'python.exe'),buildId:'c'.repeat(64)};
  const manager=createBackendManager(spec,{
    probe:async()=>null,occupied:async()=>held,busyWaitMs:10,pollMs:1,
    findStalled:()=>({pid:900,parent:899}),terminate:pid=>{killed.push(pid);held=false;},
    spawnProcess:()=>{throw new Error('spawned');},
  });
  await assert.rejects(manager.start(),/spawned/);
  assert.deepEqual(killed,[899,900]);
  const unknown=createBackendManager(spec,{
    probe:async()=>null,occupied:async()=>true,busyWaitMs:10,pollMs:1,findStalled:()=>null,
    terminate:()=>assert.fail('Must not stop an unknown service'),spawnProcess:()=>assert.fail('Must not spawn'),
  });
  await assert.rejects(unknown.start(),/will not stop or replace/);
});

test('an older build of this workspace backend is replaced instead of blocking startup',async t=>{
  const root=fixture(t), child=new EventEmitter();
  child.pid=7000;child.stdin=new PassThrough();
  const spec={workspaceRoot:root,codeRoot:root,python:path.join(root,'python.exe'),buildId:'d'.repeat(64)};
  let old={service:'vellum',protocol_version:1,workspace_root:root,build_id:'e'.repeat(64),pid:6000};
  let launchId,spawned=false;const killed=[];
  const manager=createBackendManager(spec,{
    probe:async()=>spawned?{service:'vellum',protocol_version:1,workspace_root:root,pid:7001,build_id:spec.buildId,launch_id:launchId}:old,occupied:async()=>old!==null,pollMs:1,
    terminate:pid=>{killed.push(pid);old=null;},
    spawnProcess:(_,__,opts)=>{launchId=opts.env.VELLUM_DESKTOP_LAUNCH_ID;spawned=true;return child;},
  });
  const started=await manager.start();
  assert.equal(started.reused,false);
  assert.deepEqual(killed,[6000]);
});

test('another workspace backend is never replaced',async t=>{
  const root=fixture(t), other=fixture(t);
  const manager=createBackendManager({workspaceRoot:root,buildId:'d'.repeat(64)},{
    probe:async()=>({service:'vellum',protocol_version:1,workspace_root:other,build_id:'e'.repeat(64),pid:6000}),
    terminate:()=>assert.fail('Must not stop another workspace'),spawnProcess:()=>assert.fail('Must not spawn'),
  });
  await assert.rejects(manager.start(),/another service or Vellum workspace/);
});

test('a backend that holds the workspace lease but no longer answers is replaced before starting',async t=>{
  const killed=[],order=[];
  const {manager}=ownedBackend(t,{
    findLeaseHolder:()=>({pid:9911}),
    terminate:pid=>{killed.push(pid);order.push('terminate');},
  });
  await manager.start();
  assert.deepEqual(killed,[9911]);
  assert.equal(order[0],'terminate');
});

test('no recorded lease holder leaves nothing to stop',async t=>{
  const {manager}=ownedBackend(t,{findLeaseHolder:()=>null,terminate:()=>assert.fail('Nothing should be stopped')});
  assert.equal((await manager.start()).reused,false);
});
