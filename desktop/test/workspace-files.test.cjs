const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const os=require('node:os');
const {readWorkspaceFiles}=require('../electron/workspace-files.cjs');

test('workspace file browsing separates real folders and readable previews',async t=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'vellum-files-'));
  t.after(()=>fs.rm(root,{recursive:true,force:true}));
  await fs.mkdir(path.join(root,'docs'));await fs.writeFile(path.join(root,'notes.txt'),'Saved notes');
  await fs.writeFile(path.join(root,'.env'),'secret');
  const listing=await readWorkspaceFiles(root,{operation:'list',relativePath:''});
  assert.deepEqual(listing.entries.map(row=>row.name),['docs','notes.txt']);
  const file=await readWorkspaceFiles(root,{operation:'read',relativePath:'notes.txt'});
  assert.equal(file.text_content,'Saved notes');
  await assert.rejects(readWorkspaceFiles(root,{operation:'read',relativePath:'.env'}));
  await assert.rejects(readWorkspaceFiles(root,{operation:'read',relativePath:'../outside'}));
});

test('workspace preview rejects symlinks escaping the selected root',async t=>{
  const base=await fs.mkdtemp(path.join(os.tmpdir(),'vellum-file-scope-'));
  t.after(()=>fs.rm(base,{recursive:true,force:true}));
  const root=path.join(base,'workspace');await fs.mkdir(root);await fs.writeFile(path.join(base,'outside.txt'),'Outside');
  try{await fs.symlink(path.join(base,'outside.txt'),path.join(root,'link.txt'));}
  catch(error){if(['EPERM','EACCES'].includes(error.code)){t.skip('Symlink creation is unavailable.');return;}throw error;}
  await assert.rejects(readWorkspaceFiles(root,{operation:'read',relativePath:'link.txt'}),/inside this workspace/);
});
