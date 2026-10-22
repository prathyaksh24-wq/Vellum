const {app, BrowserWindow, Menu, session} = require('electron');
const {workspaceURL} = require('./policy.cjs');
const {createDesktopHost} = require('./host.cjs');
const {serveUI} = require('./ui-server.cjs');
const path = require('node:path');
const {createNativeBrowser,readDebuggerEndpoint} = require('./native-browser.cjs');

const {initializeProtectedAudio} = require('./protected-audio.cjs');

app.setName('Vellum');
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
  let quitting = false;
  require('node:fs').rmSync(path.join(app.getPath('userData'),'DevToolsActivePort'),{force:true});
  app.on('second-instance', () => host?.openWorkspace());
  app.whenReady().then(async () => {
    // Wait for CDM registration before a workspace can probe EME.
    try { await initializeProtectedAudio(require('electron')); }
    catch (error) { console.warn('Spotify protected audio:', error.message); }
    if (app.isPackaged) uiServer = await serveUI(path.join(app.getAppPath(), 'resources/ui'));
    let workspaceRoot=process.env.VELLUM_WORKSPACE_ROOT;
    if(!workspaceRoot && app.isPackaged) {
      const response=await fetch('http://127.0.0.1:8000/api/browser/desktop-config',{signal:AbortSignal.timeout(3000)});
      if(!response.ok) throw new Error('Start the Vellum backend before opening the packaged desktop app.');
      workspaceRoot=(await response.json()).workspace_root;
      if(typeof workspaceRoot!=='string' || !path.isAbsolute(workspaceRoot)) throw new Error('The backend returned an invalid workspace location.');
    }
    nativeBrowser = await createNativeBrowser(require('electron'), {
      root: workspaceRoot || path.resolve(app.getAppPath(),'..'),
      cdpEndpoint:await readDebuggerEndpoint(app), ownerWindow:()=>host?.openWorkspace(),
    });
    host = createDesktopHost(require('electron'), {workspace: workspaceURL(), nativeBrowser});
    host.configurePermissions(session.fromPartition('persist:vellum-workspace'));
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      {id:'vellum', label: 'Vellum', submenu: [
        {label: 'Open Vellum', click: () => host.openWorkspace()},
        {label: 'Computer controls', click: () => host.openControls()},
        {type: 'separator'}, {role: 'quit'},
      ]},
      {id:'edit', role: 'editMenu'},
      {id:'view', role: 'viewMenu'},
      {id:'window', role: 'windowMenu'},
    ]));
    host.openWorkspace();
  }).catch(error => {
    require('electron').dialog.showErrorBox('Vellum startup', error.code === 'EADDRINUSE'
      ? 'Port 5173 is already in use. Close the Vellum development UI before opening the packaged app.' : error.message);
    app.quit();
  });
  app.on('before-quit', event => {
    if (quitting) return;
    event.preventDefault();quitting=true;
    Promise.resolve(nativeBrowser?.stop()).finally(()=>{uiServer?.close();app.quit();});
  });
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) host?.openWorkspace(); });
  // The existing Python backend and automation scheduler remain independent.
  app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
}
