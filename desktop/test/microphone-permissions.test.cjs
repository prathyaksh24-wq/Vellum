const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {createDesktopHost} = require('../electron/host.cjs');
const {workspaceURL} = require('../electron/policy.cjs');

function fixture({profile = fs.mkdtempSync(path.join(os.tmpdir(),'vellum-microphone-test-')), answer = async () => ({response:1})} = {}) {
  const workspace = workspaceURL();
  let nextId = 0;
  const prompts = [];
  class Window {
    constructor() {
      this.url = workspace;
      this.webContents = {id:++nextId,getURL:()=>this.url,on(){},setWindowOpenHandler(){}};
    }
    static fromWebContents(contents) { return [...host.windows.values()].find(win=>win.webContents===contents); }
    isDestroyed() { return false; }
    once() {} on() {}
    loadURL(url) { this.url=url; return Promise.resolve(); }
  }
  const host = createDesktopHost({app:{getPath:()=>profile},BrowserWindow:Window,ipcMain:{handle(){}},
    dialog:{showMessageBox(parent,options){prompts.push(options);return answer();}},screen:{},shell:{}},
    {workspace,showWindows:false});
  const win = host.openWorkspace();
  let check, request;
  host.configurePermissions({setPermissionCheckHandler(fn){check=fn;},setPermissionRequestHandler(fn){request=fn;}});
  return {profile,workspace,win,host,prompts,
    check:(details={},contents=win.webContents,origin=new URL(workspace).origin)=>check(contents,'media',origin,{isMainFrame:true,...details}),
    request:(details={},contents=win.webContents)=>new Promise(resolve=>request(contents,'media',resolve,
      {requestingUrl:workspace,securityOrigin:new URL(workspace).origin,isMainFrame:true,mediaTypes:['audio'],...details})),
  };
}

test('one microphone approval survives repeat requests, new windows, and a fresh desktop host', async () => {
  const f=fixture();
  assert.equal(f.check({mediaType:'audio'}),false);
  assert.equal(await f.request(),true);
  assert.equal(await f.request(),true);
  assert.equal(f.prompts.length,1);
  assert.equal(f.check({mediaType:'audio'}),true);
  assert.equal(f.check({mediaType:'video'}),false);
  assert.equal(f.check({mediaType:'unknown'}),false);
  const conversation=f.host.openConversation('permission-test');
  assert.equal(await f.request({},conversation.webContents),true);
  assert.equal(f.prompts.length,1);
  const restarted=fixture({profile:f.profile});
  assert.equal(restarted.check({mediaType:'audio'}),true);
  assert.equal(await restarted.request(),true);
  assert.equal(restarted.prompts.length,0);
  const saved=JSON.parse(fs.readFileSync(path.join(f.profile,'workspace-permissions.json'),'utf8'));
  assert.deepEqual(saved,{version:1,workspace:new URL(f.workspace).origin+new URL(f.workspace).pathname,microphone:true});
});

test('denying microphone access does not save an approval', async () => {
  const f=fixture({answer:async()=>({response:0})});
  assert.equal(await f.request(),false);
  assert.equal(f.check({mediaType:'audio'}),false);
  assert.equal(fs.existsSync(path.join(f.profile,'workspace-permissions.json')),false);
  const restarted=fixture({profile:f.profile});
  assert.equal(restarted.check({mediaType:'audio'}),false);
  assert.equal(await restarted.request(),true);
  assert.equal(restarted.prompts.length,1);
});

test('saved microphone permission does not approve cameras or ambiguous media requests', async () => {
  const f=fixture();
  await f.request();
  for (const mediaTypes of [['video'],['audio','video'],[]]) {
    const fresh=fixture({profile:f.profile,answer:async()=>({response:0})});
    assert.equal(await fresh.request({mediaTypes}),false);
    assert.equal(fresh.prompts.length,1);
    assert.equal(fresh.check({mediaType:'video'}),false);
  }
});

test('saved approval rejects subframes, unrelated origins, other pages, and unregistered contents', async () => {
  const f=fixture();
  await f.request();
  for (const details of [
    {isMainFrame:false}, {securityOrigin:'https://example.com'},
    {requestingUrl:new URL('/untrusted',f.workspace).href},
    {requestingUrl:'https://example.com'},
  ]) assert.equal(await f.request(details),false);
  assert.equal(await f.request({}, {...f.win.webContents}),false);
  assert.equal(f.check({mediaType:'audio',isMainFrame:false}),false);
  assert.equal(f.check({mediaType:'audio'},f.win.webContents,'https://example.com'),false);
  f.win.url=new URL('/untrusted',f.workspace).href;
  assert.equal(await f.request(),false);
  assert.equal(f.prompts.length,1);
});

test('invalid or unrelated saved permissions require fresh approval', async () => {
  for (const value of ['{broken',JSON.stringify({version:2,microphone:true}),
    JSON.stringify({version:1,workspace:'https://example.com/',microphone:true}),' '.repeat(16385)]) {
    const profile=fs.mkdtempSync(path.join(os.tmpdir(),'vellum-invalid-microphone-test-'));
    fs.writeFileSync(path.join(profile,'workspace-permissions.json'),value);
    const f=fixture({profile});
    assert.equal(f.check({mediaType:'audio'}),false);
    assert.equal(await f.request(),true);
    assert.equal(f.prompts.length,1);
  }
});

test('simultaneous requests share one microphone prompt', async () => {
  let respond;
  const f=fixture({answer:()=>new Promise(resolve=>{respond=resolve;})});
  const conversation=f.host.openConversation('concurrent-permission');
  const first=f.request(), second=f.request({},conversation.webContents);
  assert.equal(f.prompts.length,1);
  respond({response:1});
  assert.deepEqual(await Promise.all([first,second]),[true,true]);
});

test('a page that navigates away during the prompt cannot save approval', async () => {
  let respond;
  const f=fixture({answer:()=>new Promise(resolve=>{respond=resolve;})});
  const result=f.request();
  f.win.url=new URL('/untrusted',f.workspace).href;
  respond({response:1});
  assert.equal(await result,false);
  assert.equal(fs.existsSync(path.join(f.profile,'workspace-permissions.json')),false);
});
