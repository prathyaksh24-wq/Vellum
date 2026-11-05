const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {createLocalFiles}=require('../electron/local-files.cjs');
const {validateCommand}=require('../electron/policy.cjs');
test('local browsing lists folders and previews text without executing HTML',async t=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'vellum-local-files-'));t.after(()=>fs.rm(root,{recursive:true,force:true}));
  await fs.mkdir(path.join(root,'Folder'));await fs.writeFile(path.join(root,'example.html'),'<script>private()</script>');
  const read=createLocalFiles({root}),listing=await read({operation:'list'});
  assert.equal(listing.parent,null);assert.deepEqual(listing.entries.map(x=>x.name),['Folder','example.html']);
  const result=await read({operation:'preview',path:path.join(root,'example.html')});
  assert.equal(result.kind,'text');assert.equal(result.text,'<script>private()</script>');
  await assert.rejects(read({operation:'list',path:path.dirname(root)}),/local drive/);
  await assert.rejects(read({operation:'delete',path:root}),/read-only/);
  await assert.rejects(read({operation:'list',path:'\\\\server\\share'}),/local drive/);
});
test('large and unsupported files do not enter renderer previews',async t=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'vellum-preview-'));t.after(()=>fs.rm(root,{recursive:true,force:true}));
  await fs.writeFile(path.join(root,'large.txt'),'x'.repeat(256*1024+1));await fs.writeFile(path.join(root,'program.exe'),'not executable');
  const read=createLocalFiles({root});
  for(const name of ['large.txt','program.exe']){const result=await read({operation:'preview',path:path.join(root,name)});assert.equal(result.kind,'unsupported');assert.equal(result.text,undefined);}
});
test('native file command accepts only bounded read operations',()=>{
  assert.deepEqual(validateCommand('local_files',{operation:'list'}),{operation:'list'});
  for(const args of [{operation:'delete',path:'C:/'},{operation:'preview'},{operation:'list',path:'C:/a\nsecret'},{operation:'list',command:'dir'}])assert.throws(()=>validateCommand('local_files',args));
});
