const path = require('node:path');
const fs = require('node:fs');
const {pathToFileURL} = require('node:url');
const {workspaceChromeOptions,installChromeHandler} = require('./chrome.cjs');
const {conversationTarget, trustedWorkspace, validateCommand} = require('./policy.cjs');

function createDesktopHost(electron, {workspace, root = path.resolve(__dirname, '..'), backend = 'http://127.0.0.1:8000', showWindows = true, nativeBrowser = null}) {
  const {BrowserWindow, ipcMain, screen, dialog, shell} = electron;
  const windows = new Map();
  const controlsURL = pathToFileURL(path.join(root, 'index.html')).href;
  const overlayURL = pathToFileURL(path.join(root, 'overlay.html')).href;
  const known = contents => [...windows.values()].some(win => !win.isDestroyed() && win.webContents === contents);
  const trusted = url => trustedWorkspace(url, workspace) || url === controlsURL;

  installChromeHandler(electron,{known,trusted:url=>trustedWorkspace(url,workspace),windows});

  function createWindow(key, url, options = {}) {
    const existing = windows.get(key);
    if (existing && !existing.isDestroyed()) {
      if (existing.isMinimized()) existing.restore();
      if (showWindows) {
        existing.show();
        if (key !== 'overlay') existing.focus();
      }
      return existing;
    }
    const customChrome=process.platform==='win32' && (key==='workspace'||key.startsWith('conversation-'));
    const win = new BrowserWindow({
      width: 1280, height: 820, minWidth: 700, minHeight: 500,
      title: 'Vellum', backgroundColor: '#10141c', show: false,
      ...options,
      ...(customChrome?workspaceChromeOptions():{}),
      webPreferences: {
        preload: key === 'overlay' ? undefined : path.join(__dirname, 'preload.cjs'),
        contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true,
        partition: 'persist:vellum-workspace',
        additionalArguments:customChrome?['--vellum-workspace-chrome']:[],
      },
    });
    if (customChrome) {
      win.setAutoHideMenuBar?.(false);
      win.setMenuBarVisibility?.(false);
    }
    windows.set(key, win);
    let closing = false;
    win.once('close', () => { closing = true; nativeBrowser?.unmount(win); });
    win.on('closed', () => windows.delete(key));
    win.webContents.on('will-navigate', (event, target) => {
      if (!(key === 'overlay' ? target === overlayURL : trusted(target))) event.preventDefault();
    });
    win.webContents.setWindowOpenHandler(({url}) => {
      // Only an explicit user-facing link can request an external web window;
      // no native bridge is ever loaded into third-party content.
      if (/^https?:\/\//i.test(url)) {
        dialog.showMessageBox(win, {
          type: 'question', title: 'Open link', message: 'Open this link in your default browser?',
          detail: url, buttons: ['Cancel', 'Open'], defaultId: 0, cancelId: 0,
        }).then(({response}) => { if (response === 1) return shell.openExternal(url); }).catch(() => {});
      }
      return {action: 'deny'};
    });
    win.webContents.on('will-attach-webview', event => event.preventDefault());
    win.once('ready-to-show', () => {
      if (!showWindows) return;
      if (options.focusable === false) win.showInactive(); else win.show();
    });
    win.loadURL(url).catch(error => {
      if (!closing && !win.isDestroyed() && error.code !== 'ERR_ABORTED') {
        dialog.showErrorBox('Vellum could not open', error.message);
      }
    });
    return win;
  }

  function openWorkspace() { return createWindow('workspace', workspace); }
  function openConversation(id) {
    const target = conversationTarget(workspace, id);
    return createWindow(target.key, target.url, {title: 'Vellum · Conversation', width: 1120, height: 780});
  }
  function openControls() {
    return createWindow('controls', controlsURL, {title: 'Vellum · Computer controls', width: 440, height: 560, minWidth: 380});
  }
  function setOverlay(enabled) {
    if (!enabled) { windows.get('overlay')?.close(); return; }
    const bounds = screen.getPrimaryDisplay().bounds;
    const overlay = createWindow('overlay', overlayURL, {
      ...bounds, minWidth: 1, minHeight: 1, frame: false, transparent: true,
      backgroundColor: '#00000000', alwaysOnTop: true, focusable: false,
      skipTaskbar: true, resizable: false, hasShadow: false,
    });
    overlay.setIgnoreMouseEvents(true, {forward: true});
  }

  ipcMain.handle('vellum:desktop', async (event, command, input) => {
    // A trusted origin alone is insufficient: require a registered top-level window.
    if (!known(event.sender) || event.senderFrame !== event.sender.mainFrame || !trusted(event.senderFrame.url)) {
      throw new Error('Desktop command is unavailable to this page.');
    }
    const args = validateCommand(command, input);
    switch (command) {
      case 'backend_health':
        try {
          const response = await fetch(backend + '/api/health', {signal: AbortSignal.timeout(2000)});
          return {ok: response.ok};
        } catch { return {ok: false}; }
      case 'open_vellum_window': openWorkspace(); break;
      case 'open_conversation_window': openConversation(args.conversationId); break;
      case 'set_overlay': setOverlay(args.enabled); break;
    }
  });

  ipcMain.handle('vellum:browser-mount', async (event, input) => {
    if (!nativeBrowser || !known(event.sender) || event.senderFrame !== event.sender.mainFrame || !trustedWorkspace(event.senderFrame.url,workspace)) {
      throw new Error('The embedded browser is unavailable to this page.');
    }
    const window = BrowserWindow.fromWebContents(event.sender);
    return nativeBrowser.mount(window,input);
  });

  function configurePermissions(session) {
    const granted = new Set();
    const pending = new Map();
    const workspaceScope = new URL(workspace).origin + new URL(workspace).pathname;
    const profile = electron.app?.getPath('userData');
    const permissionFile = profile ? path.join(profile,'workspace-permissions.json') : null;
    let microphoneAllowed = false;
    if (permissionFile) {
      try {
        if (fs.statSync(permissionFile).size <= 16384) {
          const saved = JSON.parse(fs.readFileSync(permissionFile,'utf8'));
          microphoneAllowed = saved.version === 1 && saved.workspace === workspaceScope && saved.microphone === true;
        }
      } catch (error) {
        if (error.code !== 'ENOENT') console.warn('Could not read the saved Vellum microphone permission.');
      }
    }
    const rememberMicrophone = () => {
      microphoneAllowed = true;
      if (!permissionFile) return;
      try {
        fs.mkdirSync(profile,{recursive:true});
        const staging = permissionFile + '.tmp';
        fs.writeFileSync(staging,JSON.stringify({version:1,workspace:workspaceScope,microphone:true}),{mode:0o600});
        fs.renameSync(staging,permissionFile);
      } catch { console.warn('Could not save Vellum microphone permission; it remains allowed for this session.'); }
    };
    const trustedPermission = (contents, origin, details = {}) => {
      if (!known(contents) || !trustedWorkspace(contents.getURL(),workspace) || details.isMainFrame === false) return false;
      try {
        for (const value of [origin, details.securityOrigin].filter(Boolean)) {
          const url = new URL(value);
          if (url.origin !== new URL(workspace).origin || url.username || url.password) return false;
        }
        return !details.requestingUrl || trustedWorkspace(details.requestingUrl,workspace);
      } catch { return false; }
    };
    session.setPermissionCheckHandler((contents, permission, origin, details = {}) => {
      if (!trustedPermission(contents,origin,details)) return false;
      if (permission === 'media') {
        return (details.mediaType === 'audio' && microphoneAllowed) ||
          (['audio','video'].includes(details.mediaType) && granted.has(contents.id + ':media:' + details.mediaType));
      }
      return permission === 'fullscreen' || granted.has(contents.id + ':' + permission);
    });
    session.setPermissionRequestHandler(async (contents, permission, callback, details = {}) => {
      if (!trustedPermission(contents,details.requestingUrl,details) ||
          !['media', 'notifications', 'clipboard-sanitized-write', 'fullscreen'].includes(permission)) {
        callback(false); return;
      }
      if (['fullscreen', 'clipboard-sanitized-write'].includes(permission)) { callback(true); return; }
      const mediaTypes = Array.isArray(details.mediaTypes) ? [...new Set(details.mediaTypes)].sort() : [];
      const microphoneOnly = permission === 'media' && mediaTypes.length === 1 && mediaTypes[0] === 'audio';
      if (microphoneOnly && microphoneAllowed) { callback(true); return; }
      const permissionKey = contents.id + ':' + permission + (permission === 'media' ? ':' + mediaTypes.join(',') : '');
      if (granted.has(permissionKey)) { callback(true); return; }
      try {
        // Coalesce simultaneous microphone requests from workspace windows.
        const promptKey = microphoneOnly ? 'workspace-microphone' : permissionKey;
        if (!pending.has(promptKey)) {
          const parent = BrowserWindow.fromWebContents(contents);
          pending.set(promptKey,dialog.showMessageBox(parent, {
            type: 'question', title: 'Vellum permission',
            message: microphoneOnly ? 'Allow Vellum to use your microphone?' : permission === 'media' ? 'Allow Vellum to use the requested camera or microphone?' : 'Allow Vellum notifications?',
            ...(microphoneOnly ? {detail:'If you allow access, Vellum will remember it on this device.'} : {}),
            buttons: ['Do not allow', 'Allow'], defaultId: 0, cancelId: 0,
          }));
        }
        let response;
        try { ({response} = await pending.get(promptKey)); }
        finally { pending.delete(promptKey); }
        if (!trustedPermission(contents,details.requestingUrl,details)) { callback(false); return; }
        if (response === 1) {
          granted.add(permissionKey);
          if (microphoneOnly && !microphoneAllowed) rememberMicrophone();
          if (permission === 'media') {
            for (const type of mediaTypes.filter(type => ['audio','video'].includes(type))) granted.add(contents.id + ':media:' + type);
          }
        }
        callback(response === 1);
      } catch { callback(false); }
    });
  }
  return {openWorkspace, openConversation, openControls, setOverlay, configurePermissions, windows};
}

module.exports = {createDesktopHost};
