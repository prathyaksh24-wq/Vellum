const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {selectWorkspace}=require('../electron/workspace.cjs');

test('a saved workspace is reused and its contents are never copied',async t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'vellum-workspace-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const data=path.join(root,'existing'),profile=path.join(root,'profile');
  fs.mkdirSync(path.join(data,'data'),{recursive:true});
  fs.writeFileSync(path.join(data,'.env'),'SECRET=do-not-copy');
  fs.mkdirSync(profile);
  fs.writeFileSync(path.join(profile,'desktop-workspace.json'),JSON.stringify({version:1,workspaceRoot:data}));
  const app={isPackaged:true,getPath:()=>profile};
  const fallback=()=>{throw new Error('must not create a fresh workspace');};
  assert.equal(await selectWorkspace(app,null,{configured:null,fallback}),fs.realpathSync(data));
  assert.equal(fs.readFileSync(path.join(data,'.env'),'utf8'),'SECRET=do-not-copy');
});

test('first launch on a new computer creates a ready workspace without asking',async t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'vellum-fresh-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const profile=path.join(root,'profile'),fresh=path.join(root,'Documents','Vellum');
  const app={isPackaged:true,getPath:name=>name==='documents'?path.join(root,'Documents'):profile};
  const selected=await selectWorkspace(app,null,{configured:null});
  assert.equal(selected,fs.realpathSync(fresh));
  assert.ok(fs.statSync(path.join(fresh,'data')).isDirectory());
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(profile,'desktop-workspace.json'),'utf8')),{version:1,workspaceRoot:selected});
  // The next launch reuses it.
  assert.equal(await selectWorkspace(app,null,{configured:null,fallback:()=>{throw new Error('reused');}}),selected);
});
