const {test}=require('node:test');
const assert=require('node:assert/strict');
const {workspaceChromeOptions,validateChromeRequest,installChromeHandler}=require('../electron/chrome.cjs');

test('Windows uses the integrated title bar and native caption buttons',()=>{
  const options=workspaceChromeOptions('win32');
  assert.equal(options.titleBarStyle,'hidden');
  assert.equal(options.titleBarOverlay.height,38);
  assert.deepEqual(workspaceChromeOptions('darwin'),{});
});

test('window requests accept only named menus, local anchors and opaque colors',()=>{
  assert.equal(validateChromeRequest({kind:'menu',menu:'edit',x:80,y:33},{width:900}).menu,'edit');
  assert.equal(validateChromeRequest({kind:'theme',background:'#151313',foreground:'#e8e2dc'},{}).kind,'theme');
  for(const request of [null,{kind:'menu',menu:'exec',x:0,y:0},{kind:'menu',menu:'edit',x:-1,y:0},
    {kind:'menu',menu:'edit',x:901,y:0},{kind:'menu',menu:'edit',x:0,y:100},
    {kind:'menu',menu:'edit',x:0,y:0,url:'https://example.com'},
    {kind:'theme',background:'red',foreground:'#ffffff'}])assert.throws(()=>validateChromeRequest(request,{width:900}));
});

test('native menu IPC preserves registered-window and top-frame authorization',async()=>{
  let handler,popup,overlay;
  const mainFrame={url:'http://127.0.0.1:5173/workspace'};
  const sender={mainFrame};
  const win={getContentBounds:()=>({width:900}),setTitleBarOverlay:value=>overlay=value};
  const electron={ipcMain:{handle(name,fn){assert.equal(name,'vellum:chrome');handler=fn;}},
    BrowserWindow:{fromWebContents:()=>win},Menu:{getApplicationMenu:()=>({getMenuItemById:id=>({submenu:{popup(options){popup={id,...options};options.callback();}}})})}};
  const windows=new Map([['workspace',win]]);
  installChromeHandler(electron,{windows,known:value=>value===sender,trusted:url=>url===mainFrame.url});
  await handler({sender,senderFrame:mainFrame},{kind:'menu',menu:'edit',x:80,y:33});
  assert.equal(popup.id,'edit');assert.equal(popup.window,win);
  await handler({sender,senderFrame:mainFrame},{kind:'theme',background:'#f2f0f0',foreground:'#2b2727'});
  assert.equal(overlay.color,'#f2f0f0');
  for(const event of [{sender:{mainFrame},senderFrame:mainFrame},{sender,senderFrame:{url:mainFrame.url}}]){
    await assert.rejects(()=>handler(event,{kind:'menu',menu:'edit',x:0,y:33}),/unavailable/);
  }
  windows.clear();windows.set('controls',win);
  await assert.rejects(()=>handler({sender,senderFrame:mainFrame},{kind:'menu',menu:'edit',x:0,y:33}),/unavailable/);
});
