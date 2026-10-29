const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const os=require('node:os');
const {createNativeBrowser,profilePath,webURL}=require('../electron/native-browser.cjs');

test('native profiles and addresses cannot select arbitrary paths or local files',()=>{
  for(const id of ['../other','personal','', 'a'.repeat(33)]) assert.throws(()=>profilePath('C:/Vellum',id));
  assert.match(profilePath('C:/Vellum','default'),/browser-session[\\/]electron$/);
  for(const url of ['file:///private','javascript:alert(1)','data:text/html,fixture','https://user:pass@example.org']) assert.throws(()=>webURL(url));
  assert.equal(webURL('https://www.wikipedia.org/'),'https://www.wikipedia.org/');
});

test('the private native broker rejects unauthenticated and browser-origin requests',async t=>{
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'vellum-native-broker-'));
  const bridge=await createNativeBrowser({ipcMain:{on(){}}},{root,cdpEndpoint:'ws://127.0.0.1:1/devtools/browser/fixture',ownerWindow:()=>null});
  t.after(async()=>{await bridge.stop();await fs.rm(root,{recursive:true,force:true});});
  const options={method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({operation:'status'})};
  assert.equal((await fetch(bridge.descriptor.endpoint+'/browser',options)).status,403);
  options.headers.Authorization='Bearer '+bridge.descriptor.token;
  options.headers.Origin='https://example.org';
  assert.equal((await fetch(bridge.descriptor.endpoint+'/browser',options)).status,403);
  delete options.headers.Origin;
  assert.equal((await fetch(bridge.descriptor.endpoint+'/browser',options)).status,200);
  options.body=JSON.stringify({operation:'arbitrary_exec'});
  assert.equal((await fetch(bridge.descriptor.endpoint+'/browser',options)).status,400);
});
