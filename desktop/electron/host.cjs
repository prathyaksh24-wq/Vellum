const path = require('node:path');
const fs = require('node:fs');
const {pathToFileURL} = require('node:url');
const {workspaceChromeOptions,installChromeHandler} = require('./chrome.cjs');
const {conversationTarget, trustedWorkspace, validateCommand} = require('./policy.cjs');

function createDesktopHost(electron, {workspace, root = path.resolve(__dirname, '..'), backend = 'http://127.0.0.1:8000', showWindows = true, nativeBrowser = null}) {
  const {BrowserWindow, ipcMain, screen, dialog, shell} = electron;
  const windows = new Map();
  const providerAuthWindows = new Map();
  const controlsURL = pathToFileURL(path.join(root, 'index.html')).href;
  const overlayURL = pathToFileURL(path.join(root, 'overlay.html')).href;
  const known = contents => [...windows.values()].some(win => !win.isDestroyed() && win.webContents === contents);
  const trusted = url => trustedWorkspace(url, workspace) || url === controlsURL;

  installChromeHandler(electron,{known,trusted:url=>trustedWorkspace(url,workspace),windows});

  function providerAuthStart(value) {
    try {
      const target = new URL(value), api = new URL(backend);
      const flowId = target.searchParams.get('flow_id');
      const provider = /^\/api\/plugins\/(github|slack|airtable|notion|firecrawl|apify|exa|tavily|supabase|vercel|clickup|hubspot|asana|swiggy|zomato|district)\/oauth\/open$/.exec(target.pathname)?.[1];
      return target.origin === api.origin && ['127.0.0.1','localhost'].includes(target.hostname) &&
        !target.username && !target.password && !target.hash && provider && target.searchParams.getAll('flow_id').length===1 &&
        [...target.searchParams.keys()].every(key=>key==='flow_id') && /^[A-Za-z0-9_-]{20,100}$/.test(flowId || '') ? {provider,flowId} : null;
    } catch { return null; }
  }

  function providerLoopback(target) {
    const api=new URL(backend);
    return ['127.0.0.1','localhost'].includes(api.hostname)&&['127.0.0.1','localhost'].includes(target.hostname)&&
      target.protocol===api.protocol&&target.port===api.port&&!target.username&&!target.password;
  }

  function openProviderAuth(owner, url, {provider,flowId}) {
    const key=provider+':'+flowId;
    const previous = providerAuthWindows.get(key);
    if (previous && !previous.isDestroyed()) {previous.show(); previous.focus(); return;}
    const auth = new BrowserWindow({parent:owner, width:680, height:780, minWidth:480, minHeight:500,
      title:'Sign in to '+({github:'GitHub',slack:'Slack',airtable:'Airtable',notion:'Notion',firecrawl:'Firecrawl',apify:'Apify',exa:'Exa',tavily:'Tavily',supabase:'Supabase',vercel:'Vercel',clickup:'ClickUp',hubspot:'HubSpot',asana:'Asana',swiggy:'Swiggy',zomato:'Zomato',district:'District'})[provider], autoHideMenuBar:true, show:false,
      webPreferences:{contextIsolation:true, sandbox:true, nodeIntegration:false, webSecurity:true, partition:'vellum-'+provider+'-oauth'}});
    providerAuthWindows.set(key,auth);
    // This window is deliberately outside `windows`/`known`: provider pages get
    // no preload, native bridge, workspace privileges or device permissions.
    auth.webContents.session.setPermissionCheckHandler(()=>false);
    auth.webContents.session.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));
    auth.webContents.setWindowOpenHandler(()=>({action:'deny'}));
    const restoreOwner=()=>{if(!owner.isDestroyed()){owner.show();owner.focus();}};
    const closeWithOwner=()=>{if(!auth.isDestroyed())auth.destroy();};
    owner.once('closed',closeWithOwner);
    auth.on('closed',()=>{providerAuthWindows.delete(key);owner.removeListener('closed',closeWithOwner);restoreOwner();});
    const navigation=(event,value)=>{
      if (trustedWorkspace(value,workspace)) {event.preventDefault();auth.close();return;}
      try {
        const target=new URL(value);
        const callbacks=[`/api/plugins/${provider}/oauth/callback`,`/api/plugins/${provider}/oauth/open`,`/api/plugins/${provider}/oauth/return`];
        if(provider==='github')callbacks.push('/api/accounts/callback/github');
        const localCallback=providerLoopback(target)&&callbacks.includes(target.pathname);
        if (target.protocol!=='https:'&&!localCallback) event.preventDefault();
      } catch {event.preventDefault();}
    };
    auth.webContents.on('will-navigate',navigation);
    auth.webContents.on('will-redirect',navigation);
    auth.webContents.on('did-finish-load',async()=>{
      try {
        if(auth.isDestroyed())return;
        const page=new URL(auth.webContents.getURL());
        if(!providerLoopback(page)||page.pathname!==`/api/plugins/${provider}/oauth/return`||page.searchParams.get('flow_id')!==flowId)return;
        const statusUrl=new URL(`/api/plugins/${provider}/oauth/status`,backend);statusUrl.searchParams.set('flow_id',flowId);
        const response=await fetch(statusUrl,{headers:{Origin:new URL(workspace).origin,'X-Vellum-Accounts':'1'},signal:AbortSignal.timeout(5000)});
        if(!response.ok)return;
        const result=await response.json();
        if(['connected','failed','cancelled'].includes(result.status)&&!auth.isDestroyed())auth.close();
      } catch {/* The return page and original app retain their own status checks. */}
    });
    auth.once('ready-to-show',()=>{if(!auth.isDestroyed())auth.show();});
    auth.loadURL(url).catch(()=>{if(!auth.isDestroyed())auth.close();});
  }

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
      const providerFlow=providerAuthStart(url);
      if(providerFlow){openProviderAuth(win,url,providerFlow);return {action:'deny'};}
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
      if (permission === 'mediaKeySystem') return protectedAudio(contents,origin);
      if (!trustedPermission(contents,origin,details)) return false;
      if (permission === 'media') {
        return (details.mediaType === 'audio' && microphoneAllowed) ||
          (['audio','video'].includes(details.mediaType) && granted.has(contents.id + ':media:' + details.mediaType));
      }
      return permission === 'fullscreen' || granted.has(contents.id + ':' + permission);
    });
    session.setPermissionRequestHandler(async (contents, permission, callback, details = {}) => {
      if (permission === 'mediaKeySystem') {
        callback(protectedAudio(contents, details.requestingUrl)); return;
      }
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
