const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {conversationTarget, trustedWorkspace, validateCommand} = require('./policy.cjs');

function createDesktopHost(electron, {workspace, root = path.resolve(__dirname, '..'), backend = 'http://127.0.0.1:8000', showWindows = true, nativeBrowser = null}) {
  const {BrowserWindow, ipcMain, screen, dialog, shell} = electron;
  const windows = new Map();
  const controlsURL = pathToFileURL(path.join(root, 'index.html')).href;
  const overlayURL = pathToFileURL(path.join(root, 'overlay.html')).href;
  const known = contents => [...windows.values()].some(win => !win.isDestroyed() && win.webContents === contents);
  const trusted = url => trustedWorkspace(url, workspace) || url === controlsURL;

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
    const win = new BrowserWindow({
      width: 1280, height: 820, minWidth: 700, minHeight: 500,
      title: 'Vellum', backgroundColor: '#10141c', show: false,
      ...options,
      webPreferences: {
        preload: key === 'overlay' ? undefined : path.join(__dirname, 'preload.cjs'),
        contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true,
        partition: 'persist:vellum-workspace',
      },
    });
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
    let shown = false;
    const showWorkspace = () => {
      if (!showWindows || shown || closing || win.isDestroyed()) return;
      shown = true;
      if (options.focusable === false) win.showInactive(); else win.show();
    };
    win.once('ready-to-show', showWorkspace);
    // A third-party playback iframe may keep the full document load pending.
    // Its network lifecycle must not leave the already-rendered workspace hidden.
    win.webContents.on('dom-ready', showWorkspace);
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
    const protectedAudio = (contents, origin) => {
      if (!known(contents) || !trustedWorkspace(contents.getURL(), workspace)) return false;
      try {
        const url = new URL(origin);
        return !url.username && !url.password &&
          [new URL(workspace).origin, 'https://sdk.scdn.co', 'https://open.spotify.com'].includes(url.origin);
      } catch { return false; }
    };

    session.setPermissionCheckHandler((contents, permission, origin) => {
      if (permission === 'mediaKeySystem') return protectedAudio(contents,origin);
      return known(contents) && trustedWorkspace(origin + new URL(workspace).pathname, workspace) &&
        (permission === 'fullscreen' || granted.has(contents.id + ':' + permission));
    });
    session.setPermissionRequestHandler(async (contents, permission, callback, details = {}) => {
      if (permission === 'mediaKeySystem') {
        callback(protectedAudio(contents, details.requestingUrl)); return;
      }
      if (!known(contents) || !trustedWorkspace(contents.getURL(), workspace) ||
          (details.requestingUrl && !trustedWorkspace(details.requestingUrl, workspace)) ||
          !['media', 'notifications', 'clipboard-sanitized-write', 'fullscreen'].includes(permission)) {
        callback(false); return;
      }
      if (['fullscreen', 'clipboard-sanitized-write'].includes(permission)) { callback(true); return; }
      try {
        const parent = BrowserWindow.fromWebContents(contents);
        const {response} = await dialog.showMessageBox(parent, {
          type: 'question', title: 'Vellum permission',
          message: permission === 'media' ? 'Allow Vellum to use the requested camera or microphone?' : 'Allow Vellum notifications?',
          buttons: ['Do not allow', 'Allow'], defaultId: 0, cancelId: 0,
        });
        if (response === 1) granted.add(contents.id + ':' + permission);
        callback(response === 1);
      } catch { callback(false); }
    });
  }
  return {openWorkspace, openConversation, openControls, setOverlay, configurePermissions, windows};
}

module.exports = {createDesktopHost};
