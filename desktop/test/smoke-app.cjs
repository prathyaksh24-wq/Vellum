const electron = require('electron');
const {app} = electron;
const assert = require('node:assert/strict');
const http = require('node:http');
const {writeFileSync} = require('node:fs');
const {createDesktopHost} = require('../electron/host.cjs');
const {workspaceURL} = require('../electron/policy.cjs');

app.setPath('userData', process.env.VELLUM_SMOKE_PROFILE);
app.commandLine.appendSwitch('mute-audio');
app.enableSandbox();
const report = result => writeFileSync(process.env.VELLUM_SMOKE_RESULT, JSON.stringify(result));
report({status: 'starting'});
let server;
app.whenReady().then(async () => {
  report({status: 'ready'});
  // Only a disposable local fixture is loaded. No user tabs, media or account sessions.
  server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'text/html');
    res.end(req.url === '/frame' ? '<p>Child frame</p>' :
      '<title>Vellum desktop fixture</title><h1>Vellum</h1><iframe src="/frame"></iframe>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const workspace = workspaceURL('http://127.0.0.1:' + server.address().port);
  const host = createDesktopHost(electron, {workspace, showWindows: false});
  const win = host.openWorkspace();
  report({status: 'loading'});
  await new Promise(resolve => win.webContents.once('did-finish-load', resolve));
  const bridge = await win.webContents.executeJavaScript('({runtime:window.VellumDesktop.runtime,node:typeof require})');
  report({status: 'checking-windows'});
  assert.deepEqual(bridge, {runtime: 'electron', node: 'undefined'});
  assert.equal(win.webContents.getLastWebPreferences().sandbox, true);
  assert.equal(win.webContents.getLastWebPreferences().nodeIntegrationInSubFrames, false);
  assert.equal(await win.webContents.mainFrame.frames[0].executeJavaScript('typeof window.VellumDesktop'), 'undefined');
  report({status: 'opening-conversation'});
  await win.webContents.executeJavaScript('window.VellumDesktop.invoke("open_conversation_window", {conversationId:"fixture / chat"})');
  const conversation = [...host.windows.entries()].find(([key]) => key.startsWith('conversation-'))[1];
  report({status: 'loading-conversation'});
  await new Promise(resolve => {
    if (!conversation.webContents.isLoading()) resolve();
    else conversation.webContents.once('did-finish-load', resolve);
  });
  assert.equal(new URL(conversation.webContents.getURL()).searchParams.get('conversation_id'), 'fixture / chat');
  report({status: 'reusing-conversation'});
  await win.webContents.executeJavaScript('window.VellumDesktop.invoke("open_conversation_window", {conversationId:"fixture / chat"})');
  assert.equal(host.windows.size, 2);
  report({status: 'overlay'});
  await win.webContents.executeJavaScript('window.VellumDesktop.invoke("set_overlay", {enabled:true})');
  const overlay = host.windows.get('overlay');
  assert.equal(overlay.isFocusable(), false);
  assert.equal(overlay.isAlwaysOnTop(), true);
  await win.webContents.executeJavaScript('window.VellumDesktop.invoke("set_overlay", {enabled:false})');
  const denied = await win.webContents.executeJavaScript('window.VellumDesktop.invoke("exec", {}).then(()=>false,()=>true)');
  assert.equal(denied, true);
  // An unrelated page in the same window must lose native command authority.
  await win.loadURL('http://127.0.0.1:' + server.address().port + '/untrusted');
  const restricted = await win.webContents.executeJavaScript('window.VellumDesktop.invoke("open_vellum_window").then(()=>false,()=>true)');
  assert.equal(restricted, true);
  report({status: 'passed', checks: ['isolated preload', 'detached chat reuse', 'overlay', 'untrusted IPC rejected']});
  for (const window of host.windows.values()) window.destroy();
  server.close();
  app.exit(0);
}).catch(error => { report({status: 'failed', error: error.stack}); server?.close(); app.exit(1); });
