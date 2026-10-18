const electron=require('electron');
const {app}=electron;
const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {createNativeBrowser,readDebuggerEndpoint}=require('../electron/native-browser.cjs');
const {createDesktopHost}=require('../electron/host.cjs');
const {workspaceURL}=require('../electron/policy.cjs');

const root=process.env.VELLUM_NATIVE_TEST_ROOT;
app.setPath('userData',path.join(root,'app-profile'));
app.commandLine.appendSwitch('remote-debugging-port','0');
app.commandLine.appendSwitch('remote-debugging-address','127.0.0.1');
app.commandLine.appendSwitch('mute-audio');
app.enableSandbox();
let bridge, server, timer;
app.whenReady().then(async()=>{
  server=http.createServer((req,res)=>{
    if(req.url==='/download') {
      res.writeHead(200,{'Content-Type':'application/octet-stream','Content-Disposition':'attachment; filename="fixture.txt"'});
      res.end('Vellum native download fixture');return;
    }
    res.setHeader('Content-Type','text/html');
    res.end(req.url==='/site' || req.url==='/' ? `<title>Native fixture</title><h1>Embedded website</h1>
      <form role="search"><input type="file" hidden><input aria-label="Search fixture" type="search" oninput="clearTimeout(window.fixtureSuggestions);window.fixtureSuggestions=setTimeout(()=>document.querySelector('#suggestions').innerHTML='<a role=option href=/article>Jailer 2 - Wikipedia</a>',100)"><div id="suggestions" role="listbox"></div><input type="submit" aria-label="Google Search" value="Search"></form><button type="button" onclick="document.querySelector('#result').textContent='Applied: '+document.querySelector('input[type=search]').value">Apply fixture</button>
      <p id="result"></p><button onclick="document.documentElement.requestFullscreen()">Fullscreen fixture</button>
      <div style="height:3000px"></div><p>Bottom fixture</p>` : req.url==='/article' ? '<title>Jailer 2 - Wikipedia fixture</title><h1>Jailer 2</h1>' : '<title>Vellum fixture workspace</title><main>Workspace stays separate</main>');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const url='http://127.0.0.1:'+server.address().port;
  let host;
  bridge=await createNativeBrowser(electron,{root,cdpEndpoint:await readDebuggerEndpoint(app),ownerWindow:()=>host.openWorkspace()});
  host=createDesktopHost(electron,{workspace:workspaceURL(url),nativeBrowser:bridge,showWindows:false});
  const win=host.openWorkspace();
  await new Promise(resolve=>win.webContents.once('did-finish-load',resolve));
  win.show();win.focus();
  timer=setInterval(async()=>{
    try {
      const response=await fetch(bridge.descriptor.endpoint+'/browser',{method:'POST',headers:{Authorization:'Bearer '+bridge.descriptor.token,'Content-Type':'application/json'},body:JSON.stringify({operation:'status'})});
      const state=await response.json();
      if (state.active_target_id) await bridge.mount(win,{visible:true,target_id:state.active_target_id,bounds:{x:400,y:100,width:800,height:600}});
    } catch {}
  },80);
  const python=path.resolve(__dirname,'../../.venv/Scripts/python.exe');
  const env={...process.env,PYTHONPATH:path.resolve(__dirname,'../../backend'),VELLUM_NATIVE_FIXTURE_URL:url+'/site'};
  const child=spawn(python,[path.join(__dirname,'native-check.py')],{env,stdio:'inherit',windowsHide:true});
  child.on('error',error=>{console.error(error.message);app.exit(1);});
  child.on('exit',async code=>{
    clearInterval(timer);await bridge.stop();server.close();
    fs.writeFileSync(path.join(root,'result.json'),JSON.stringify({passed:code===0}));
    app.exit(code || 0);
  });
}).catch(error=>{console.error(error);app.exit(1);});
