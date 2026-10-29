const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs/promises');
const {randomBytes, randomUUID, timingSafeEqual} = require('node:crypto');

function profilePath(root, identity) {
  if (!/^(default|[a-f0-9]{32})$/.test(identity)) throw new Error('Unknown browser profile.');
  return path.join(root, 'data/browser-session', ...(identity === 'default' ? [] : ['profiles', identity]), 'electron');
}

function webURL(value) {
  if (value === 'about:blank') return value;
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('Unsupported website address.');
  return url.href;
}

async function createNativeBrowser(electron, {root, cdpEndpoint, ownerWindow}) {
  const {WebContentsView, session, ipcMain, Menu, screen, dialog} = electron;
  const token = randomBytes(32).toString('hex');
  const tabs = new Map(), downloads = new Map();
  let preferences, profile, active = '', mount = null, humanInput = false, agentAction = false, control = 'closed', still = '';
  const activeSession = () => session.fromPath(profilePath(root, profile.id));
  const owned = contents => [...tabs.values()].find(tab => tab.view.webContents === contents);
  async function applyCursor(tab) {
    const settings=preferences || {};
    const signature=JSON.stringify([settings.cursor_style,settings.cursor_size,settings.cursor_image,settings.cursor_hotspot_x,settings.cursor_hotspot_y]);
    if(tab.cursorSignature===signature || tab.view.webContents.isDestroyed()) return;
    tab.cursorSignature=signature;
    if(tab.cursorCSS) await tab.view.webContents.removeInsertedCSS(tab.cursorCSS).catch(()=>{});
    tab.cursorCSS='';
    if(!settings.cursor_style || settings.cursor_style==='classic') return;
    const size=Math.max(16,Math.min(48,settings.cursor_size || 28));
    const colors={light:['#ffffff','#20252b'],ember:['#ff8655','#332016'],mint:['#7ce8bd','#12372c'],pixel:['#fff5cf','#252525']};
    let image;
    if(settings.cursor_style==='custom' && /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(settings.cursor_image || '')) {
      image=electron.nativeImage.createFromDataURL(settings.cursor_image).resize({width:size,height:size}).toDataURL();
    } else {
      const [fill,stroke]=colors[settings.cursor_style] || colors.light;
      const shape=settings.cursor_style==='pixel' ? 'M3 2h4v4h4v4h4v4h4v4h-8v4H7v-8H3Z' : 'M3 2 24 18l-10 1-5 9Z';
      image='data:image/svg+xml,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 32 32"><path d="${shape}" fill="${fill}" stroke="${stroke}" stroke-width="1.6"/></svg>`);
    }
    const x=Math.max(0,Math.min(size-1,settings.cursor_hotspot_x || 0));
    const y=Math.max(0,Math.min(size-1,settings.cursor_hotspot_y || 0));
    tab.cursorCSS=await tab.view.webContents.insertCSS(`html,body,a,button,input,textarea,select,[role="button"],[role="link"]{cursor:url("${image}") ${x} ${y},auto !important}`,{cssOrigin:'user'});
  }
  function permissionFor(url, category) {
    let origin;
    try { origin = new URL(url).origin; } catch { return 'block'; }
    const rule = profile.site_rules.find(item => item.origin === origin);
    return (rule?.permissions || profile.site_defaults)[category] || 'block';
  }
  function sendShortcut(command) {
    if (mount && !mount.window.isDestroyed()) {
      mount.window.webContents.focus();
      mount.window.webContents.send('vellum:browser-event', {type:'shortcut', command});
    }
  }
  function present() {
    for (const [id, tab] of tabs) {
      const visible = mount && mount.visible && id === active && !tab.background && tab.view.webContents.getURL() !== 'about:blank';
      if (!visible) {
        if (tab.parent && !tab.parent.isDestroyed()) tab.parent.contentView.removeChildView(tab.view);
        tab.parent = null;
        continue;
      }
      if (tab.parent !== mount.window) {
        if (tab.parent && !tab.parent.isDestroyed()) tab.parent.contentView.removeChildView(tab.view);
        mount.window.contentView.addChildView(tab.view);
        tab.parent = mount.window;
      }
      const bounds = tab.fullscreen ? {x:0,y:0,width:mount.window.getContentSize()[0],height:mount.window.getContentSize()[1]} : mount.bounds;
      tab.view.setBounds({x:bounds.x,y:bounds.y,width:bounds.width,height:bounds.height});
      tab.view.setVisible(true);
    }
  }
  async function create(background = false) {
    if (!profile) throw new Error('Open the browser profile first.');
    const view = new WebContentsView({webPreferences:{
      session: activeSession(), sandbox:true, contextIsolation:true, nodeIntegration:false,
      webSecurity:true, preload:path.join(__dirname, 'browser-preload.cjs'),
      // Site script policy is enforced with CSP below; keep the isolated cursor preload available.
      javascript:true,
    }});
    const contents = view.webContents;
    // Navigation and planning may begin before the workspace has mounted the pane.
    view.setBounds({x:0,y:0,width:1280,height:800});
    const target = contents.getOrCreateDevToolsTargetId();
    const tab = {view, background, parent:null, fullscreen:false};
    tabs.set(target, tab);
    if (!background) active = target;
    const navigate = (event, url) => { try { webURL(url); } catch { event.preventDefault(); } };
    contents.on('will-navigate', navigate);
    contents.on('will-redirect', (event, url, _inPlace, main) => { if (main) navigate(event, url); });
    contents.on('did-navigate', present);
    contents.on('did-finish-load',()=>{tab.cursorSignature='';applyCursor(tab).catch(()=>{});});
    contents.on('destroyed', () => { tabs.delete(target); if (active === target) active = [...tabs.keys()][0] || ''; present(); });
    contents.on('enter-html-full-screen', () => {
      tab.fullscreen = true;
      if (mount) { tab.wasFullscreen = mount.window.isFullScreen(); mount.window.setFullScreen(true); }
      present();
    });
    contents.on('leave-html-full-screen', () => {
      tab.fullscreen = false;
      if (mount && !tab.wasFullscreen) mount.window.setFullScreen(false);
      present();
    });
    contents.on('before-input-event', (event, input) => {
      if (!['keyDown','rawKeyDown'].includes(input.type)) return;
      const key = input.key.toLowerCase(), modifier = input.control || input.meta;
      if (key === 'escape' && tab.fullscreen) {
        event.preventDefault();
        contents.executeJavaScript('document.fullscreenElement && document.exitFullscreen()').catch(()=>{});
        return;
      }
      const command = modifier && key === 'l' ? 'address' : modifier && key === 't' ? 'new_tab'
        : modifier && key === 'w' ? 'close_tab' : key === 'f5' || modifier && key === 'r' ? 'reload'
        : input.alt && key === 'arrowleft' ? 'back' : input.alt && key === 'arrowright' ? 'forward' : '';
      if (command) { event.preventDefault(); sendShortcut(command); }
    });
    contents.setWindowOpenHandler(({url}) => {
      if (permissionFor(contents.getURL(), 'popups') === 'allow') {
        try { webURL(url); create(false).then(next => tabs.get(next.target_id)?.view.webContents.loadURL(url)).catch(() => {}); } catch {}
      }
      return {action:'deny'};
    });
    contents.on('context-menu', (_event, info) => {
      const items = info.isEditable ? [{role:'cut'}, {role:'copy'}, {role:'paste'}, {role:'selectAll'}]
        : info.selectionText ? [{role:'copy'}, {role:'selectAll'}] : [{label:'Back',click:()=>sendShortcut('back')},{label:'Reload',click:()=>sendShortcut('reload')}];
      Menu.buildFromTemplate(items).popup({window:tab.parent || ownerWindow()});
    });
    await contents.loadURL('about:blank');
    present();
    return {target_id:target};
  }
  function configureSession() {
    const browserSession = activeSession();
    browserSession.setPermissionCheckHandler((contents, permission) => {
      const tab = owned(contents);
      if (!tab) return false;
      if (permission === 'fullscreen') return true;
      const key = {geolocation:'location', media:'camera', notifications:'notifications'}[permission];
      return key && permissionFor(contents.getURL(), key) === 'allow';
    });
    browserSession.setPermissionRequestHandler(async (contents, permission, callback, details) => {
      if (!owned(contents)) return callback(false);
      if (permission === 'fullscreen') return callback(true);
      const keys = permission === 'media' ? (details.mediaTypes || []).map(type=>type === 'audio' ? 'microphone' : 'camera')
        : [{geolocation:'location',notifications:'notifications',clipboard:'clipboard'}[permission]];
      if (!keys.length || keys.some(key => !key || permissionFor(contents.getURL(), key) === 'block')) return callback(false);
      if (keys.every(key=>permissionFor(contents.getURL(), key) === 'allow')) return callback(true);
      try {
        const answer = await dialog.showMessageBox(ownerWindow(), {type:'question', title:'Website permission',
          message:`Allow ${new URL(contents.getURL()).hostname} to use ${keys.join(' and ')}?`,
          buttons:['Do not allow','Allow'],defaultId:0,cancelId:0});
        callback(answer.response === 1);
      } catch { callback(false); }
    });
    browserSession.webRequest.onBeforeRequest((details, callback) => callback({cancel:
      details.resourceType === 'image' && permissionFor(details.url, 'images') === 'block'}));
    browserSession.webRequest.onHeadersReceived((details,callback)=>{
      const directives=[];
      if (permissionFor(details.url,'javascript')==='block') directives.push("script-src 'none'");
      if (permissionFor(details.url,'images')==='block') directives.push("img-src 'none'");
      const headers={...details.responseHeaders};
      if (directives.length) headers['Content-Security-Policy']=[...(headers['Content-Security-Policy'] || []),directives.join('; ')];
      callback({responseHeaders:headers});
    });
    browserSession.removeAllListeners('will-download');
    browserSession.on('will-download', (event, item, contents) => {
      const tab = owned(contents);
      if (!tab) { event.preventDefault(); return; }
      const rule = profile.site_rules.find(rule=>rule.origin === new URL(contents.getURL()).origin);
      if (control === 'agent' && !humanInput && (rule?.downloads || preferences.agent_downloads) === 'block') { event.preventDefault(); return; }
      const id = randomUUID();
      const directory = path.join(profilePath(root, profile.id), 'staging-downloads', id);
      const filename = path.basename(item.getFilename()).replace(/[<>:"|?*\x00-\x1f]/g, '_') || 'download';
      require('node:fs').mkdirSync(directory, {recursive:true});
      const destination = path.join(directory, filename);
      item.setSavePath(destination); item.pause();
      const record = {id, profile_id:profile.id, name:filename, item, path:destination, target_id:contents.getOrCreateDevToolsTargetId(), state:'paused'};
      downloads.set(id, record);
      item.on('done', (_event,state)=>{record.state=state;});
    });
  }
  async function close() {
    for (const record of downloads.values()) {
      if (!['completed','cancelled','interrupted'].includes(record.state)) record.item.cancel();
    }
    for (const tab of [...tabs.values()]) {
      if (tab.parent && !tab.parent.isDestroyed()) tab.parent.contentView.removeChildView(tab.view);
      tab.view.webContents.close();
    }
    tabs.clear(); active=''; control='closed'; humanInput=false;
  }
  const commands = {
    async open(data) {
      if (!Array.isArray(data.preferences?.profiles)) throw new Error('Invalid browser preferences.');
      preferences = data.preferences;
      const next = preferences.profiles.find(item=>item.id === preferences.active_profile_id);
      if (!next) throw new Error('Unknown browser profile.');
      profilePath(root,next.id);
      if (profile?.id !== next.id) await close();
      profile = next; configureSession();
      if (!tabs.size && !data.background) await create();
      return {cdp_endpoint:cdpEndpoint, control, ...await commands.status()};
    },
    async create(data) { return create(data.background === true); },
    async close() { await close(); return {}; },
    async activate(data) {
      if (data.target_id && !tabs.has(data.target_id)) throw new Error('This embedded tab is closed.');
      active=data.target_id; control=data.control;
      if (data.preferences) preferences=data.preferences;
      await Promise.all([...tabs.values()].map(tab=>applyCursor(tab).catch(()=>{})));
      if (control !== 'agent') for (const tab of tabs.values()) tab.view.webContents.send('vellum:browser-pointer', null);
      present(); return {};
    },
    async status() {
      const tab=tabs.get(active), bounds=tab?.view.getBounds();
      const result={active_target_id:active,tabs:[...tabs].filter(([,item])=>!item.view.webContents.isDestroyed()).map(([id,item])=>({target_id:id,background:item.background})),
        human_input:humanInput, viewport:bounds && bounds.width>=240 && bounds.height>=160 ? {width:bounds.width,height:bounds.height} : null,
        downloads:[...downloads.values()].filter(item=>item.profile_id===profile?.id).map(({id,name,target_id})=>({id,name,target_id}))};
      humanInput=false; return result;
    },
    async activity(data) { agentAction=data.active === true; return {}; },
    async pointer(data) {
      const tab=tabs.get(data.target_id);
      if (!tab) throw new Error('The embedded tab changed.');
      tab.view.webContents.send('vellum:browser-pointer', {...data.pointer, preferences:data.preferences}); return {};
    },
    async clear(data) {
      const identity = data.profile_id;
      const browserSession = session.fromPath(profilePath(root,identity));
      if (data.data_types.includes('cache')) await browserSession.clearCache();
      if (data.data_types.includes('cookies')) await browserSession.clearStorageData({storages:['cookies','localstorage','indexdb','serviceworkers','cachestorage']});
      return {};
    },
    async download_resume(data) { const item=downloads.get(data.download_id); if (!item) throw new Error('Download is unavailable.'); item.item.resume(); return {}; },
    async download_cancel(data) { downloads.get(data.download_id)?.item.cancel(); return {}; },
    async download_status(data) { const item=downloads.get(data.download_id); if (!item) throw new Error('Download is unavailable.'); return {state:item.state,path:item.path}; },
  };
  ipcMain.on('vellum:browser-human-input', event => {
    if (owned(event.sender) && !agentAction) {
      humanInput=true;
      if (mount && !mount.window.isDestroyed()) mount.window.webContents.send('vellum:browser-event', {type:'take_over'});
    }
  });
  const server=http.createServer(async (req,res)=>{
    const received=Buffer.from(req.headers.authorization || '');
    const expected=Buffer.from('Bearer '+token);
    if (req.method !== 'POST' || req.url !== '/browser' || req.headers.origin || received.length !== expected.length || !timingSafeEqual(received,expected)) {
      res.writeHead(403).end(); return;
    }
    try {
      const chunks=[];let size=0;
      for await (const chunk of req) { size+=chunk.length; if (size>4000000) throw new Error('Browser command is too large.'); chunks.push(chunk); }
      const data=JSON.parse(Buffer.concat(chunks));
      if (!Object.hasOwn(commands,data.operation)) throw new Error('Unknown browser command.');
      const result=await commands[data.operation](data);
      res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'}).end(JSON.stringify(result));
    } catch { res.writeHead(400,{'Content-Type':'application/json'}).end(JSON.stringify({error:'The embedded browser command could not complete.'})); }
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  const descriptor={version:1, endpoint:'http://127.0.0.1:'+server.address().port, token};
  const descriptorPath=path.join(root,'.desktop-runtime/browser-bridge.json');
  await fs.mkdir(path.dirname(descriptorPath),{recursive:true});
  await fs.writeFile(descriptorPath,JSON.stringify(descriptor),{mode:0o600});
  return {
    async mount(window, data) {
      if (data.focus_chrome === true) { window.webContents.focus(); return; }
      if (data.prepare_only === true) {
        const page=tabs.get(active)?.view.webContents;
        if (page && !still) still=(await page.capturePage()).toDataURL();
        return {still};
      }
      if (data.visible === false) {
        const page=tabs.get(active)?.view.webContents;
        if (data.snapshot && page && !still) still=(await page.capturePage()).toDataURL();
        mount={window,visible:false};present();return {still:data.snapshot ? still : ''};
      }
      if (!tabs.has(data.target_id)) throw new Error('This embedded tab is closed.');
      const rect=data.bounds;
      if (!rect || !['x','y','width','height'].every(key=>Number.isFinite(rect[key]))) throw new Error('Invalid browser bounds.');
      const [width,height]=window.getContentSize();
      const zoom=window.webContents.getZoomFactor();
      const x=Math.max(0,Math.round(rect.x*zoom)), y=Math.max(0,Math.round(rect.y*zoom));
      mount={window,visible:true,bounds:{x,y,width:Math.max(1,Math.min(Math.round(rect.width*zoom),width-x)),height:Math.max(1,Math.min(Math.round(rect.height*zoom),height-y))}};
      active=data.target_id;still='';present();
    },
    unmount(window) { if(mount?.window===window) {mount=null;present();} },
    async stop() {
      await close();server.close();
      try { const value=JSON.parse(await fs.readFile(descriptorPath,'utf8')); if (value.token===token) await fs.unlink(descriptorPath); } catch {}
    },
    descriptor,
  };
}

async function readDebuggerEndpoint(app) {
  const file=path.join(app.getPath('userData'),'DevToolsActivePort');
  for (let i=0;i<100;i++) {
    try {
      const [port, route]=(await fs.readFile(file,'utf8')).trim().split(/\r?\n/);
      if (/^\d+$/.test(port) && /^\/devtools\/browser\/[a-f0-9-]+$/.test(route)) return `ws://127.0.0.1:${port}${route}`;
    } catch {}
    await new Promise(resolve=>setTimeout(resolve,30));
  }
  throw new Error('Vellum embedded browser debugging transport did not start.');
}
module.exports={createNativeBrowser,readDebuggerEndpoint,profilePath,webURL};
