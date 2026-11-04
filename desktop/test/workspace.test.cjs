const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {selectWorkspace}=require('../electron/workspace.cjs');

test('first installed launch explicitly selects existing data and remembers only its location',async t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'vellum-workspace-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const data=path.join(root,'existing'),profile=path.join(root,'profile');
  fs.mkdirSync(path.join(data,'data'),{recursive:true});
  fs.writeFileSync(path.join(data,'.env'),'SECRET=do-not-copy');
  const app={isPackaged:true,getPath:()=>profile};
  let prompts=0;
  const dialog={showOpenDialog:async()=>{prompts++;return {canceled:false,filePaths:[data]};}};
  assert.equal(await selectWorkspace(app,dialog,{configured:null}),fs.realpathSync(data));
  assert.equal(await selectWorkspace(app,dialog,{configured:null}),fs.realpathSync(data));
  assert.equal(prompts,1);
  assert.deepEqual(fs.readdirSync(profile),['desktop-workspace.json']);
  assert.equal(fs.readFileSync(path.join(data,'.env'),'utf8'),'SECRET=do-not-copy');
});

test('cancelled workspace selection does not start a fresh data tree',async t=>{
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'vellum-cancel-'));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const result=await selectWorkspace({isPackaged:true,getPath:()=>profile},{showOpenDialog:async()=>({canceled:true})},{configured:null});
  assert.equal(result,null);
  assert.deepEqual(fs.readdirSync(profile),[]);
});
