const path = require('node:path');
const fs = require('node:fs');
const {pathToFileURL} = require('node:url');
const {conversationTarget, trustedWorkspace, validateCommand} = require('./policy.cjs');
const {workspaceChromeOptions,installChromeHandler} = require('./chrome.cjs');
const {createLocalFiles}=require('./local-files.cjs');

function createDesktopHost(electron, {workspace, workspaceRoot, root = path.resolve(__dirname, '..'), backend = 'http://127.0.0.1:8000', showWindows = true, nativeBrowser = null, workspaceReady = () => Promise.resolve({reused:true}), protectedAudioReady = Promise.resolve({status:'unsupported'}), onWorkspaceClose = () => {}}) {
  const {BrowserWindow, ipcMain, screen, dialog, shell} = electron;
  const windows = new Map();
  const providerAuthSessions = new Map();
  const controlsURL = pathToFileURL(path.join(root, 'index.html')).href;
  const overlayURL = pathToFileURL(path.join(root, 'overlay.html')).href;
  const known = contents => [...windows.values()].some(win => !win.isDestroyed() && win.webContents === contents);
  const localFiles=createLocalFiles();
  const trusted = url => trustedWorkspace(url, workspace) || url === controlsURL;
  installChromeHandler(electron,{known,trusted:url=>trustedWorkspace(url,workspace),windows});

  function providerAuthStart(value) {
    try {
      const target = new URL(value), api = new URL(backend);
      const flowId = target.searchParams.get('flow_id');
      const provider = /^\/api\/plugins\/(youtube|github|linear|slack|airtable|notion|firecrawl|apify|exa|tavily|supabase|district|zomato|swiggy|vercel|clickup|asana|hubspot)\/oauth\/open$/.exec(target.pathname)?.[1];
      return target.origin === api.origin && ['127.0.0.1','localhost'].includes(target.hostname) &&
        !target.username && !target.password && !target.hash && provider && target.searchParams.getAll('flow_id').length===1 &&
        [...target.searchParams.keys()].every(key=>key==='flow_id') && /^[A-Za-z0-9_-]{20,100}$/.test(flowId || '') ? {provider,flowId} : null;
    } catch { return null; }
  }

  function openProviderAuth(owner, url, {provider,flowId}) {
    const key=provider+':'+flowId;
    if(providerAuthSessions.has(key))return providerAuthSessions.get(key).opening;
    // OAuth runs in the user's system browser. Embedded Electron browsers are
    // rejected by Google and other identity providers, including federated login.
    const session={timer:null,expires:Date.now()+10*60*1000};
    const finish=()=>{
      clearTimeout(session.timer);providerAuthSessions.delete(key);
      owner.removeListener('closed',finish);
    };
    owner.once('closed',finish);
    providerAuthSessions.set(key,session);
    const poll=async()=>{
      if(!providerAuthSessions.has(key))return;
      if(owner.isDestroyed()||Date.now()>=session.expires){finish();return;}
      try {
        const statusUrl=new URL(`/api/plugins/${provider}/oauth/status`,backend);statusUrl.searchParams.set('flow_id',flowId);
        const response=await fetch(statusUrl,{headers:{Origin:new URL(workspace).origin,'X-Vellum-Accounts':'1',...(provider==='linear'?{'X-Vellum-Linear':'1'}:{})},signal:AbortSignal.timeout(5000)});
        if(response.ok){
          const result=await response.json();
          if(['connected','complete','failed','cancelled','expired'].includes(result.status)){
            finish();if(!owner.isDestroyed()){if(owner.isMinimized())owner.restore();owner.show();owner.focus();}return;
          }
        }
      } catch {/* Original app keeps polling and exposes connection errors. */}
      if(providerAuthSessions.has(key)){session.timer=setTimeout(poll,1500);session.timer.unref?.();}
    };
    session.opening=Promise.resolve().then(()=>shell.openExternal(url)).then(()=>{
      if(providerAuthSessions.has(key)){session.timer=setTimeout(poll,1500);session.timer.unref?.();}
    }).catch(()=>{finish();throw new Error('Could not open your default browser. Use Continue to sign in again.');});
    return session.opening;
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
    win.on('closed', () => {windows.delete(key);if(key==='workspace')onWorkspaceClose();});
    win.webContents.on('will-navigate', (event, target) => {
      if (!(key === 'overlay' ? target === overlayURL : trusted(target))) event.preventDefault();
    });
    win.webContents.setWindowOpenHandler(({url}) => {
      const providerFlow=providerAuthStart(url);
      if(providerFlow){openProviderAuth(win,url,providerFlow).catch(error=>{if(!win.isDestroyed())dialog.showMessageBox(win,{type:'error',title:'Could not open sign-in',message:error.message}).catch(()=>{});});return {action:'deny'};}
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
      case 'open_plugin_oauth': {
        if(!trustedWorkspace(event.senderFrame.url,workspace))throw new Error('Sign-in is available only in the workspace.');
        const flow=providerAuthStart(args.url);
        if(!flow)throw new Error('Choose a valid local plugin sign-in flow.');
        const owner=[...windows.values()].find(win=>win.webContents===event.sender);
        await openProviderAuth(owner,args.url,flow);
        return {opened:true};
      }
      case 'local_files': {
        if(!trustedWorkspace(event.senderFrame.url,workspace))throw new Error('Local files are available only in the workspace.');
        return localFiles(args);
      }
      case 'workspace_files': {
        if (!workspaceRoot || !trustedWorkspace(event.senderFrame.url,workspace)) throw new Error('Workspace files are unavailable here.');
        return require('./workspace-files.cjs').readWorkspaceFiles(workspaceRoot,args);
      }
      case 'workspace_ready': {
        const state=await (typeof workspaceReady==='function'?workspaceReady():workspaceReady);
        return {ready:true,reused:state.reused};
      }
      case 'protected_audio_ready': return await protectedAudioReady;
      case 'backend_health':
        try {
          const response = await fetch(backend + '/api/health', {signal: AbortSignal.timeout(2000)});
          return {ok: response.ok};
        } catch { return {ok: false}; }
      case 'open_vellum_window': openWorkspace(); break;
      case 'open_conversation_window': openConversation(args.conversationId); break;
      case 'set_overlay': setOverlay(args.enabled); break;
      case 'skill_file': {
        if (!trustedWorkspace(event.senderFrame.url,workspace)) throw new Error('Skill files are available only in the workspace.');
        const response=await fetch(backend+'/api/skills/'+encodeURIComponent(args.name),{signal:AbortSignal.timeout(5000)});
        if (!response.ok) throw new Error('The registered skill could not be found.');
        const detail=await response.json();
        // Resolve through the canonical backend catalog; the renderer cannot supply a path.
        const target=detail.local_file;
        if (typeof target!=='string' || !path.isAbsolute(target) || path.basename(target)!=='SKILL.md' || !fs.statSync(target).isFile()) throw new Error('No local SKILL.md is available.');
        if (args.operation==='reveal') shell.showItemInFolder(target);
        else {const error=await shell.openPath(target);if(error)throw new Error('The default editor could not open SKILL.md.');}
        return {ok:true};
      }
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
    const protectedAudio = (contents, origin) => {
      if (!known(contents) || !trustedWorkspace(contents.getURL(), workspace)) return false;
      try {
        const url = new URL(origin);
        return !url.username && !url.password &&
          [new URL(workspace).origin, 'https://sdk.scdn.co', 'https://open.spotify.com'].includes(url.origin);
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
