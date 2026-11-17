const {app, BrowserWindow, Menu, session, dialog, Tray, shell} = require('electron');
const {workspaceURL} = require('./policy.cjs');
const {createDesktopHost} = require('./host.cjs');
const {serveUI} = require('./ui-server.cjs');
const path = require('node:path');
const CommandRegistry=require('./commands.cjs');
const {createNativeBrowser,readDebuggerEndpoint} = require('./native-browser.cjs');
const {initializeProtectedAudio} = require('./protected-audio.cjs');
const {BACKEND,createBackendManager,launchSpec,backendResponds,UI_PORT} = require('./backend.cjs');
const {selectWorkspace} = require('./workspace.cjs');
const {claimDesktopWorkspace} = require('./workspace-lock.cjs');
const {createDevBundle, watchDevelopment} = require('./dev-reload.cjs');

app.setName('Vellum');
// Review the prepared desktop UI without installing or replacing an app.
const bundledWorkspace=app.isPackaged || process.env.VELLUM_DESKTOP_BUNDLED_UI==='1';
const devNode = app.isPackaged ? null : process.env.VELLUM_DESKTOP_DEV_NODE;
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
  let devBundle;
  let initialBuild;
  let stopWatching;
  let relaunch = false;
  let supervisor;
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
    // Development reloads and backend restarts wait while a reply is streaming
    // in any window or an agent turn is running, so a chat is never cut off.
    const busy = async () => {
      let active = 0;
      for (const win of BrowserWindow.getAllWindows()) {
        try {active += Number(await win.webContents.executeJavaScript('window.VellumApi?.chat?.activeStreams||0', true)) || 0;} catch {}
      }
      try {
        const response = await fetch(BACKEND+'/api/desktop/activity', {signal:AbortSignal.timeout(2000)});
        if (response.ok) active += Number((await response.json()).active_turns) || 0;
      } catch {}
      return active > 0;
    };
    const waitUntilIdle = async what => {
      const until = Date.now() + 30*60*1000;
      let told = false;
      while (!quitting && Date.now() < until && await busy()) {
        if (!told) {console.log('[Vellum dev] Waiting for the reply in progress before '+what+'.'); told = true;}
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    };
    // Vellum never reloads the window on its own: someone may come back to it
    // after hours and must find it exactly as they left it. A new development
    // build is served on the next manual reload (Ctrl+R) or launch.
    const reloadWorkspace = async () => {
      console.log('[Vellum dev] A new UI build is ready. Reload the window (Ctrl+R) to use it.');
    };
    if (devNode) {
      devBundle = createDevBundle(sourceRoot, devNode);
      const previous = devBundle.current;
      initialBuild = devBundle.build();
      // No progress popup: the first ever build is awaited silently, later
      // launches open on the last good build at once.
      if (!previous) await initialBuild;
      else {
        // Open on the last good build now; swap in the fresh one only if it differs.
        initialBuild.then(changed => {
          if (changed && !quitting) reloadWorkspace();
        }).catch(error => console.error('[Vellum dev]', error.stderr || error.message));
      }
    }
    if (quitting) return;
    const backendOptions = {packaged:app.isPackaged, resourcesPath:process.resourcesPath, sourceRoot, workspaceRoot};
    let backendSpec = launchSpec(backendOptions);
    // The backend is supervised for the whole session: a crash, a hang or a
    // failed restart is repaired here instead of leaving the app without data.
    let backendState = null, backendUp = false, restarting = null, healthFailures = 0, restartDelay = 2000;
    let workspaceReady;
    const onBackendExit = () => {if(!quitting)setTimeout(()=>restartBackend('it exited unexpectedly'),1000);};
    const manage = spec => createBackendManager(spec,{onExit:onBackendExit});
    const launchBackend = progress => {
      backendUp = false;
      workspaceReady = backend.start(progress).then(state=>{backendState=state;backendUp=true;healthFailures=0;restartDelay=2000;return state;});
      workspaceReady.catch(()=>{});
      return workspaceReady;
    };
    // Every stop/start runs one at a time, so a crash restart and an edit
    // restart can never race and orphan a backend on port 8000.
    let lifecycle = Promise.resolve(), lifecycleBusy = 0;
    const serially = task => {
      lifecycleBusy++;
      const run = lifecycle.then(task).finally(() => {lifecycleBusy--;});
      lifecycle = run.catch(() => {});
      return run;
    };
    function restartBackend(reason) {
      if (quitting || restarting) return restarting;
      console.warn('[Vellum] Restarting the backend because '+reason+'.');
      restarting = serially(async () => {
        await backend.kill();
        if (quitting) return;
        backendSpec = launchSpec(backendOptions);
        backend = manage(backendSpec);
        await launchBackend();
        host?.windows.get('workspace')?.webContents.send('vellum:backend-restarted');
      }).catch(error => {
        console.error('[Vellum] The backend did not restart:', error.message);
        const delay = restartDelay; restartDelay = Math.min(restartDelay*2, 60000);
        setTimeout(() => restartBackend('the previous restart failed'), delay);
      }).finally(() => {restarting = null;});
      return restarting;
    }
    backend=manage(backendSpec);
    launchBackend(message=>{if(startup&&!startup.isDestroyed())startup.setTitle(message);}).then(state=>{recordStartup('backend_ready');return state;}).catch(()=>{});
    // Only a backend that keeps failing while the computer is awake is replaced.
    // Sleep, screen lock and timer throttling of an idle app reset the count and
    // start a grace period, so returning to Vellum never triggers a restart.
    let lastTick = Date.now(), graceUntil = 0;
    const settle = () => {healthFailures = 0; graceUntil = Date.now() + 60000;};
    try {
      const {powerMonitor} = require('electron');
      for (const event of ['resume', 'unlock-screen', 'user-did-become-active']) powerMonitor.on(event, settle);
    } catch {}
    supervisor = setInterval(async () => {
      const now = Date.now(), gap = now - lastTick;
      lastTick = now;
      if (gap > 15000) settle();
      if (quitting || restarting || lifecycleBusy || !backendUp || !backend.owned || now < graceUntil) return;
      if (await backendResponds(undefined, 8000)) {healthFailures = 0; return;}
      if (++healthFailures >= 6) restartBackend('it stopped responding for about 30 seconds');
    }, 5000);
    const protectedAudioReady=initializeProtectedAudio(require('electron'))
      .then(state=>{recordStartup('protected_audio_ready');return state;})
      .catch(()=>({status:'unavailable'}));
    // The preview entry has no startup gate. Packaged JSX waits for this same
    // promise through the trusted preload, so its window can appear immediately.
    if(!bundledWorkspace)await workspaceReady;
    if(quitting)return;
    if (bundledWorkspace) {
      const bundledRoot = path.join(app.getAppPath(), 'resources/ui');
      uiServer = await serveUI(bundledRoot, UI_PORT, () => devBundle?.current ?? bundledRoot);
    }
    nativeBrowser = await createNativeBrowser(require('electron'), {
      root: workspaceRoot,
      cdpEndpoint:await readDebuggerEndpoint(app), ownerWindow:()=>host?.openWorkspace(),
    });
    if(quitting){await nativeBrowser.stop();return;}
    host = createDesktopHost(require('electron'), {workspaceRoot,workspace: workspaceURL(bundledWorkspace?'http://127.0.0.1:'+UI_PORT:undefined), nativeBrowser,workspaceReady:()=>workspaceReady,protectedAudioReady,
      onWorkspaceClose:()=>{if(!quitting&&!booting)app.quit();}});
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
    try {await workspaceReady;} catch (error) {
      // The window is already open; keep retrying instead of closing the app.
      console.error('[Vellum] The backend did not start:', error.message);
      restartBackend('it did not start');
    }
    if (devBundle && !quitting) {
      stopWatching = watchDevelopment(sourceRoot, async changed => {
        if (changed.has('desktop')) {
          console.log('[Vellum dev] Desktop host files changed. Restart Vellum to apply them.');
        }
        let reload = false;
        if (changed.has('backend')) {
          const next = launchSpec(backendOptions);
          if (next.buildId !== backendSpec.buildId || !backendUp) {
            if (backendState?.reused) {
              console.warn('[Vellum dev] Restart the independently started API to apply backend edits.');
            } else {
              await waitUntilIdle('restarting the backend');
              try {
                await serially(async () => {
                  await backend.stop();
                  if (quitting) return;
                  backend = manage(next);
                  backendSpec = next;
                  await launchBackend();
                });
              } catch (error) {restartBackend('it did not start after an edit');}
              // No window reload: the API client waits for the backend and refreshes.
            }
          }
        }
        if (changed.has('ui')) {
          await devBundle.build();
          reload = true;
        }
        if (reload && !quitting) await reloadWorkspace();
      });
      console.log('[Vellum dev] Watching workspace source changes.');
    }
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
    clearInterval(supervisor);
    Promise.all([initialBuild?.catch(()=>{}), stopWatching?.()]).then(()=>nativeBrowser?.stop()).then(()=>backend?.stop()).then(()=>{
      uiServer?.close();workspaceLock?.close();tray?.destroy();
      devBundle?.close();
      if (relaunch) app.relaunch();
      app.quit();
    }).catch(error=>{quitting=false;dialog.showErrorBox('Vellum is still closing',error.message);});
  });
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) host?.openWorkspace(); });
  // Closing the workspace stops its watcher and the backend owned by this app.
  app.on('window-all-closed', () => { if (!booting && process.platform !== 'darwin') app.quit(); });
}
