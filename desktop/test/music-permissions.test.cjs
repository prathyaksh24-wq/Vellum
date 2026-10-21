const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createDesktopHost}=require('../electron/host.cjs');
const {workspaceURL}=require('../electron/policy.cjs');

function fixture(showWindows = false) {
  const workspace=workspaceURL();
  class Window {
    constructor() {this.handlers={};this.shows=0;this.webContents={id:1,getURL:()=>workspace,on:(name,fn)=>this.handlers[name]=fn,setWindowOpenHandler(){}};}
    isDestroyed(){return false;}
    show(){this.shows++;}
    once(){} on(){} loadURL(){return Promise.resolve();}
  }
  const host=createDesktopHost({BrowserWindow:Window,ipcMain:{handle(){}},dialog:{},screen:{},shell:{}},{workspace,showWindows});
  const contents=host.openWorkspace().webContents;
  let check,request;
  host.configurePermissions({setPermissionCheckHandler(fn){check=fn;},setPermissionRequestHandler(fn){request=fn;}});
  return {contents,workspace,check,request,Window,host};
}

test('a rendered workspace becomes visible without waiting for external frame loads',()=>{
  const f=fixture(true),win=f.host.windows.get('workspace');
  assert.equal(win.shows,0);
  win.handlers['dom-ready']();
  assert.equal(win.shows,1);
  win.handlers['dom-ready']();
  assert.equal(win.shows,1);
});

test('Spotify protected audio is permitted only inside a registered Vellum workspace',async()=>{
  const f=fixture();
  assert.equal(f.check(f.contents,'mediaKeySystem','https://sdk.scdn.co'),true);
  assert.equal(f.check(f.contents,'mediaKeySystem',new URL(f.workspace).origin),true);
  let allowed;
  await f.request(f.contents,'mediaKeySystem',value=>allowed=value,{requestingUrl:'https://sdk.scdn.co/embedded/index.html'});
  assert.equal(allowed,true);
  for(const origin of ['https://sdk.scdn.co.evil.org','https://example.org','http://sdk.scdn.co','https://user@sdk.scdn.co']) {
    assert.equal(f.check(f.contents,'mediaKeySystem',origin),false);
    await f.request(f.contents,'mediaKeySystem',value=>allowed=value,{requestingUrl:origin});
    assert.equal(allowed,false);
  }
  assert.equal(f.check({...f.contents,id:2},'mediaKeySystem','https://sdk.scdn.co'),false);
  f.contents.getURL=()=>new URL('/untrusted',f.workspace).href;
  assert.equal(f.check(f.contents,'mediaKeySystem','https://sdk.scdn.co'),false);
});

test('Spotify frames do not inherit camera or microphone permission',async()=>{
  const f=fixture();let allowed;
  assert.equal(f.check(f.contents,'media','https://sdk.scdn.co'),false);
  await f.request(f.contents,'media',value=>allowed=value,{requestingUrl:'https://sdk.scdn.co/embedded/index.html'});
  assert.equal(allowed,false);
});
