const {app, BrowserWindow, Menu, session, dialog, Tray, shell} = require('electron');
const {workspaceURL} = require('./policy.cjs');
const {createDesktopHost} = require('./host.cjs');
const {serveUI} = require('./ui-server.cjs');
const path = require('node:path');
const CommandRegistry=require('./commands.cjs');
const {createNativeBrowser,readDebuggerEndpoint} = require('./native-browser.cjs');
const {initializeProtectedAudio} = require('./protected-audio.cjs');
const {createBackendManager,launchSpec,UI_PORT} = require('./backend.cjs');
const {selectWorkspace} = require('./workspace.cjs');
const {claimDesktopWorkspace} = require('./workspace-lock.cjs');

app.setName('Vellum');
// Review the prepared desktop UI without installing or replacing an app.
const bundledWorkspace=app.isPackaged || process.env.VELLUM_DESKTOP_BUNDLED_UI==='1';
require('./workspace-profile.cjs').configureWorkspaceProfile(app,{directory:process.env.VELLUM_DESKTOP_PROFILE});
app.setAppUserModelId('local.vellum.desktop');
app.enableSandbox();
app.commandLine.appendSwitch('remote-debugging-address','127.0.0.1');
app.commandLine.appendSwitch('remote-debugging-port','0');
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  let host;
  let uiServer;
  let nativeBrowser;
  let backend;
  let workspaceLock;
  let tray;
  let startup;
  let booting = true;
  let quitting = false;
  const launchedAt=performance.now();
  let selectedRoot;
  const startupTimings=[];
  const recordStartup=phase=>{
    startupTimings.push({phase,elapsed_ms:Math.round(performance.now()-launchedAt)});
    if(selectedRoot){
      const fs=require('node:fs'),directory=path.join(selectedRoot,'.api-runtime');
      fs.mkdirSync(directory,{recursive:true});
      fs.writeFileSync(path.join(directory,'desktop-startup.json'),JSON.stringify({version:1,phases:startupTimings},null,2));
    }
  };
  require('node:fs').rmSync(path.join(app.getPath('userData'),'DevToolsActivePort'),{force:true});
  const reveal=()=>{if(host)host.openWorkspace();else if(startup&&!startup.isDestroyed()){startup.show();startup.focus();}};
  app.on('second-instance', reveal);
  app.whenReady().then(async () => {
    recordStartup('electron_ready');
    const sourceRoot=path.resolve(app.getAppPath(),'..');
    const workspaceRoot=await selectWorkspace(app,dialog,{sourceRoot});
    if(!workspaceRoot){app.quit();return;}
    selectedRoot=workspaceRoot;
    workspaceLock=await claimDesktopWorkspace(workspaceRoot,reveal);
    if(!workspaceLock){app.quit();return;}
    recordStartup('workspace_selected');
    startup=new BrowserWindow({width:420,height:170,resizable:false,minimizable:false,maximizable:false,
      title:'Opening Vellum',backgroundColor:'#14181e',webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false}});
    startup.on('close',()=>{if(booting&&!quitting)app.quit();});
    const opening='<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>Opening Vellum</title><style>body{background:#14181e;color:#eee;font:15px system-ui;padding:24px}h1{font-size:22px;margin:0 0 12px}p{color:#abb3bd}</style><h1>Vellum</h1><p>Opening your workspace…</p>';
    await startup.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent(opening));
    backend=createBackendManager(launchSpec({packaged:app.isPackaged,resourcesPath:process.resourcesPath,sourceRoot,workspaceRoot}));
    const workspaceReady=backend.start(message=>{if(!startup.isDestroyed())startup.setTitle(message);}).then(state=>{recordStartup('backend_ready');return state;});
    workspaceReady.catch(()=>{}); // The startup owner and trusted preload await it below.
    const protectedAudioReady=initializeProtectedAudio(require('electron'))
      .then(state=>{recordStartup('protected_audio_ready');return state;})
      .catch(()=>({status:'unavailable'}));
    // The preview entry has no startup gate. Packaged JSX waits for this same
    // promise through the trusted preload, so its window can appear immediately.
    if(!bundledWorkspace)await workspaceReady;
    if(quitting)return;
    if (bundledWorkspace) uiServer = await serveUI(path.join(app.getAppPath(), 'resources/ui'),UI_PORT);
    nativeBrowser = await createNativeBrowser(require('electron'), {
      root: workspaceRoot,
      cdpEndpoint:await readDebuggerEndpoint(app), ownerWindow:()=>host?.openWorkspace(),
    });
    if(quitting){await nativeBrowser.stop();return;}
    host = createDesktopHost(require('electron'), {workspace: workspaceURL(bundledWorkspace?'http://127.0.0.1:'+UI_PORT:undefined), nativeBrowser,workspaceReady,protectedAudioReady});
    host.configurePermissions(session.fromPartition('persist:vellum-workspace'));
    const commandItem=id=>({id:'command-'+id,label:CommandRegistry.definition(id).label,click:()=>{const win=BrowserWindow.getFocusedWindow();if(win&&!win.isDestroyed())win.webContents.send('vellum:app-command',id);}});
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      {id:'vellum', label: 'Vellum', submenu: [
        {label: 'Open Vellum', click: () => host.openWorkspace()},
        commandItem('chat.new'),commandItem('commands.open'),commandItem('settings.open'),
        {label: 'Computer controls', click: () => host.openControls()},
        {label: 'Open startup logs', click: () => shell.openPath(path.join(workspaceRoot,'.api-runtime'))},
        {label: 'About Vellum', click: () => app.showAboutPanel()},
        {type: 'separator'}, {role: 'quit'},
      ]},
      {id:'edit', role: 'editMenu'},
      {id:'view',label:'View',submenu:[commandItem('sidebar.toggle'),commandItem('workspace.tabs'),commandItem('workspace.layout'),{label:'Browser',submenu:['browser.new','browser.close','browser.reopen','browser.next','browser.previous','browser.closeOthers','browser.address','browser.back','browser.forward'].map(commandItem)},{type:'separator'},commandItem('surface.reload'),commandItem('surface.forceReload'),commandItem('find.open'),{type:'separator'},commandItem('zoom.in'),commandItem('zoom.out'),commandItem('zoom.reset'),commandItem('shortcuts.open'),{role:'toggleDevTools'}]},
      {id:'window',label:'Window',submenu:[{role:'minimize'},{role:'close',accelerator:'Alt+F4'}]},
    ]));
    if(bundledWorkspace){
      tray=new Tray(path.join(app.getAppPath(),'assets/icon.ico'));
      tray.setToolTip('Vellum — background tasks are running');
      tray.setContextMenu(Menu.buildFromTemplate([
        {label:'Open Vellum',click:()=>host.openWorkspace()},
        {label:'Quit Vellum',click:()=>app.quit()},
      ]));
      tray.on('double-click',()=>host.openWorkspace());
    }
    booting=false;
    const window=host.openWorkspace();
    recordStartup('workspace_window_requested');
    window.webContents.once('did-finish-load',()=>recordStartup('workspace_document_loaded'));
    startup?.close();
    await workspaceReady;
  }).catch(async error => {
    if(quitting)return;
    booting=false;
    // Do not expose process environments or credentials in native dialogs.
    const result=await dialog.showMessageBox({type:'error',title:'Vellum could not open',
      message:error.code==='EADDRINUSE'?'The desktop UI port '+UI_PORT+' is already in use.':error.message,
      detail:'Your workspace has not been moved. The existing development server was not stopped.',
      buttons:['Close','Open startup logs'],defaultId:0,cancelId:0});
    if(result.response===1){
      try{const root=backend?.workspaceRoot || process.env.VELLUM_WORKSPACE_ROOT || path.resolve(app.getAppPath(),'..');await shell.openPath(path.join(root,'.api-runtime'));}catch{}
    }
    app.quit();
  });
  app.on('before-quit', event => {
    if (quitting) return;
    event.preventDefault();quitting=true;
    Promise.resolve(nativeBrowser?.stop()).then(()=>backend?.stop()).then(()=>{
      uiServer?.close();workspaceLock?.close();tray?.destroy();app.quit();
    }).catch(error=>{quitting=false;dialog.showErrorBox('Vellum is still closing',error.message);});
  });
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) host?.openWorkspace(); });
  // Packaged windows can close while automations continue in the tray. Quit
  // gracefully stops only the backend this desktop instance actually spawned.
  app.on('window-all-closed', () => { if (!booting && !tray && process.platform !== 'darwin') app.quit(); });
}
