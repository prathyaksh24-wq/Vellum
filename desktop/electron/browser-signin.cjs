// Google (and a few other identity providers) refuse to sign in inside embedded
// browsers. Instead of disguising Vellum, the person signs in with a real
// installed browser that runs on a Vellum-owned profile; once they close it,
// Vellum reads that profile's cookies (the browser decrypts its own store in a
// short headless run) and copies them into the embedded browser session.
const path = require('node:path');
const fs = require('node:fs');
const {spawn: spawnProcess, execFileSync} = require('node:child_process');

const SIGN_IN_HOSTS = new Set(['accounts.google.com', 'accounts.youtube.com']);
const SIGN_IN_PATHS = /^\/(v3\/signin|signin|ServiceLogin|AccountChooser|InteractiveLogin|o\/oauth2|CheckCookie)/i;

function needsBrowserSignIn(url) {
  try {
    const {protocol, hostname, pathname} = new URL(url);
    return protocol === 'https:' && SIGN_IN_HOSTS.has(hostname) && SIGN_IN_PATHS.test(pathname);
  } catch { return false; }
}

function signInBrowsers(env = process.env) {
  const programs = env.PROGRAMFILES || 'C:/Program Files';
  const programsX86 = env['PROGRAMFILES(X86)'] || 'C:/Program Files (x86)';
  const local = env.LOCALAPPDATA || '';
  if (process.platform === 'darwin') return [
    {name:'Brave', path:'/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'},
    {name:'Chrome', path:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'},
    {name:'Edge', path:'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'},
  ];
  if (process.platform !== 'win32') return [
    {name:'Brave', path:'/usr/bin/brave-browser'}, {name:'Chrome', path:'/usr/bin/google-chrome'},
    {name:'Chromium', path:'/usr/bin/chromium'}, {name:'Edge', path:'/usr/bin/microsoft-edge'},
  ];
  return [
    {name:'Brave', path:path.join(programs, 'BraveSoftware/Brave-Browser/Application/brave.exe')},
    {name:'Brave', path:path.join(programsX86, 'BraveSoftware/Brave-Browser/Application/brave.exe')},
    ...(local ? [{name:'Brave', path:path.join(local, 'BraveSoftware/Brave-Browser/Application/brave.exe')}] : []),
    {name:'Chrome', path:path.join(programs, 'Google/Chrome/Application/chrome.exe')},
    {name:'Chrome', path:path.join(programsX86, 'Google/Chrome/Application/chrome.exe')},
    ...(local ? [{name:'Chrome', path:path.join(local, 'Google/Chrome/Application/chrome.exe')}] : []),
    {name:'Edge', path:path.join(programsX86, 'Microsoft/Edge/Application/msedge.exe')},
    {name:'Edge', path:path.join(programs, 'Microsoft/Edge/Application/msedge.exe')},
  ];
}

// Only Chromium-based browsers can hand their cookies over (through DevTools).
const CHROMIUM = {'brave.exe':'Brave', 'chrome.exe':'Chrome', 'msedge.exe':'Edge', 'vivaldi.exe':'Vivaldi',
  'opera.exe':'Opera', 'launcher.exe':'Opera', 'chromium.exe':'Chromium', 'thorium.exe':'Thorium'};

// The person's default browser on Windows, when it is Chromium-based.
function defaultBrowser({run = execFileSync} = {}) {
  if (process.platform !== 'win32') return null;
  try {
    // Newer Windows 11 records the current choice under UserChoiceLatest\ProgId
    // and leaves the older UserChoice key stale.
    const key = 'HKCU\\Software\\Microsoft\\Windows\\Shell\\Associations\\UrlAssociations\\https\\';
    let progId = '';
    for (const choiceKey of [key + 'UserChoiceLatest\\ProgId', key + 'UserChoice']) {
      try { progId = /ProgId\s+REG_SZ\s+(\S+)/i.exec(run('reg.exe', ['query', choiceKey, '/v', 'ProgId'], {encoding:'utf8', windowsHide:true}))?.[1] || ''; } catch {}
      if (progId) break;
    }
    if (!progId || !/^[\w.-]+$/.test(progId)) return null;
    const command = run('reg.exe', ['query', `HKCR\\${progId}\\shell\\open\\command`, '/ve'], {encoding:'utf8', windowsHide:true});
    const executable = /REG_(?:EXPAND_)?SZ\s+"([^"]+\.exe)"/i.exec(command)?.[1] || /REG_(?:EXPAND_)?SZ\s+(\S+\.exe)/i.exec(command)?.[1];
    const name = executable && CHROMIUM[path.basename(executable).toLowerCase()];
    return name ? {name, path:executable} : null;
  } catch { return null; }
}

function findSignInBrowser({env = process.env, exists = fs.existsSync, preferred = defaultBrowser} = {}) {
  const explicit = String(env.VELLUM_SIGNIN_BROWSER || '').trim();
  if (explicit && exists(explicit)) return {name:CHROMIUM[path.basename(explicit).toLowerCase()] || path.basename(explicit).replace(/\.exe$/i, ''), path:explicit};
  // Brave first (Vellum's own browser elsewhere), then the person's default
  // Chromium browser, then any other installed one.
  const candidates = signInBrowsers(env);
  const brave = candidates.find(item => item.name === 'Brave' && exists(item.path));
  if (brave) return brave;
  const chosen = preferred();
  if (chosen && exists(chosen.path)) return chosen;
  return candidates.find(item => exists(item.path)) || null;
}

const sameSite = {Strict:'strict', Lax:'lax', None:'no_restriction'};
// CDP cookie -> Electron cookies.set() details. Host-only cookies must not carry
// a domain, otherwise Chromium widens them to subdomains.
function electronCookie(cookie) {
  if (!cookie?.name || typeof cookie.domain !== 'string') return null;
  const host = cookie.domain.replace(/^\./, '');
  if (!host) return null;
  // Electron cannot set partitioned (CHIPS) cookies. One partitioned under its
  // own site behaves like a first-party cookie there; cross-site ones are skipped.
  if (cookie.partitionKey) {
    let top = '';
    try { top = new URL(typeof cookie.partitionKey === 'string' ? cookie.partitionKey : cookie.partitionKey.topLevelSite).hostname; } catch {}
    if (!top || cookie.partitionKey.hasCrossSiteAncestor || !(host === top || host.endsWith('.' + top) || top.endsWith('.' + host))) return null;
  }
  const details = {
    url:(cookie.secure ? 'https://' : 'http://') + host + (cookie.path || '/'),
    name:cookie.name, value:String(cookie.value ?? ''), path:cookie.path || '/',
    secure:!!cookie.secure, httpOnly:!!cookie.httpOnly,
    sameSite:sameSite[cookie.sameSite] || 'unspecified',
  };
  if (cookie.domain.startsWith('.') && !cookie.name.startsWith('__Host-')) details.domain = cookie.domain;
  if (!cookie.session && Number(cookie.expires) > 0) details.expirationDate = Number(cookie.expires);
  return details;
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function readDevToolsEndpoint(profileDir, child, timeoutMs = 15000) {
  const file = path.join(profileDir, 'DevToolsActivePort');
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (child.exitCode !== null) throw new Error('The sign-in browser closed before Vellum could read its session.');
    try {
      const [port, route] = fs.readFileSync(file, 'utf8').trim().split(/\r?\n/);
      if (/^\d+$/.test(port) && /^\/devtools\/browser\/[\w-]+$/.test(route)) return `ws://127.0.0.1:${port}${route}`;
    } catch {}
    await sleep(100);
  }
  throw new Error('The sign-in browser did not start its session reader.');
}

function cdpCall(endpoint, calls) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(endpoint);
    const results = [];
    let index = 0;
    const timer = setTimeout(() => { socket.close(); reject(new Error('Reading the sign-in session timed out.')); }, 20000);
    const next = () => {
      if (index >= calls.length) { clearTimeout(timer); socket.close(); resolve(results); return; }
      socket.send(JSON.stringify({id:index + 1, method:calls[index][0], params:calls[index][1] || {}}));
    };
    socket.onopen = next;
    socket.onerror = () => { clearTimeout(timer); reject(new Error('Vellum could not read the sign-in session.')); };
    socket.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.id !== index + 1) return;
      results.push(message.result || {});
      index += 1;
      next();
    };
  });
}

// Chromium removes its lockfile when the profile's last window closes, including
// when the launch hands off to an instance already running on this profile.
async function waitForProfileClosed(profileDir, child, signal) {
  const lock = path.join(profileDir, 'lockfile');
  const singleton = path.join(profileDir, 'SingletonLock');
  await new Promise(resolve => { if (child.exitCode !== null) resolve(); else child.once('exit', resolve); });
  for (;;) {
    if (signal?.aborted) throw new Error('Sign-in was cancelled.');
    if (!fs.existsSync(lock) && !fs.existsSync(singleton)) return;
    await sleep(500);
  }
}

// A background (headless) run must fully let go of the profile before the
// visible window starts: Chromium hands a launch on a profile that is still in
// use to the running process and exits at once, so no window would appear.
async function releaseProfile(child, profileDir, timeoutMs = 8000) {
  const started = Date.now();
  if (child.exitCode === null && child.signalCode == null) {
    await Promise.race([new Promise(resolve => child.once('exit', resolve)), sleep(timeoutMs / 2)]);
    if (child.exitCode === null && child.signalCode == null) { child.kill(); await Promise.race([new Promise(resolve => child.once('exit', resolve)), sleep(2000)]); }
  }
  const lock = path.join(profileDir, 'lockfile'), singleton = path.join(profileDir, 'SingletonLock');
  while ((fs.existsSync(lock) || fs.existsSync(singleton)) && Date.now() - started < timeoutMs) await sleep(150);
}

// myaccount.google.com stays put for a live Google session and redirects
// elsewhere (sign-in or the marketing page) for a missing or revoked one.
const SESSION_CHECK_URL = 'https://myaccount.google.com/';
const sessionLive = url => { try { return new URL(url).hostname === 'myaccount.google.com'; } catch { return false; } };

// A short headless run of the sign-in profile: is its Google session live, and
// what cookies does it hold? A dead session's cookies can be cleared so the
// next visible run really asks the person to sign in.
async function probeProfile({executable, profileDir, spawn = spawnProcess, clearIfDead = false, timeoutMs = 12000}) {
  fs.rmSync(path.join(profileDir, 'DevToolsActivePort'), {force:true});
  const child = spawn(executable, [
    `--user-data-dir=${profileDir}`, '--headless=new', '--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check', SESSION_CHECK_URL,
  ], {stdio:'ignore', windowsHide:true});
  try {
    const endpoint = await readDevToolsEndpoint(profileDir, child);
    const port = new URL(endpoint.replace(/^ws:/, 'http:')).port;
    let url = '', loaded = false, started = Date.now();
    while (Date.now() - started < timeoutMs) {
      try {
        const page = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(item => item.type === 'page');
        url = page?.url || '';
        const host = url ? new URL(url).hostname : '';
        // A loaded page has a real title; until then the title is its address.
        loaded = !!page?.title && !/^(https?:\/\/|about:|myaccount\.google\.com)/i.test(page.title);
        // Settled: redirected away from Google's account hosts, or myaccount itself
        // has loaded and stayed put.
        if (host && host !== 'myaccount.google.com' && !/^accounts\.(google|youtube)\.com$/.test(host)) break;
        if (host === 'myaccount.google.com' && loaded && Date.now() - started > 2000) break;
        if (host === 'accounts.google.com' && loaded && /\/(v3\/signin|ServiceLogin|signin)/i.test(new URL(url).pathname)) break;
      } catch {}
      await sleep(250);
    }
    const live = sessionLive(url) && loaded;
    const calls = [['Storage.getCookies'], ...(!live && clearIfDead ? [['Storage.clearCookies']] : []), ['Browser.close']];
    const [cookies] = await cdpCall(endpoint, calls);
    return {live, cookies:live ? cookies.cookies || [] : []};
  } finally {
    await releaseProfile(child, profileDir);
  }
}

async function readProfileCookies({executable, profileDir, spawn = spawnProcess}) {
  fs.rmSync(path.join(profileDir, 'DevToolsActivePort'), {force:true});
  const child = spawn(executable, [
    `--user-data-dir=${profileDir}`, '--headless=new', '--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check', 'about:blank',
  ], {stdio:'ignore', windowsHide:true});
  try {
    const endpoint = await readDevToolsEndpoint(profileDir, child);
    const [cookies] = await cdpCall(endpoint, [['Storage.getCookies'], ['Browser.close']]);
    return cookies.cookies || [];
  } finally {
    await releaseProfile(child, profileDir);
  }
}

// Sites whose cookies the import replaces: google.com, youtube.com, google.co.in...
function cookieSite(domain) {
  const labels = String(domain || '').replace(/^\./, '').toLowerCase().split('.').filter(Boolean);
  if (labels.length < 2) return '';
  const twoPart = labels.length > 2 && /^(co|com|org|net|ac|gov)$/.test(labels.at(-2)) && labels.at(-1).length === 2;
  return labels.slice(twoPart ? -3 : -2).join('.');
}

// Replace (not merge) the sites' cookies, so a signed-out or older session's
// cookies cannot mix with the new one.
async function importCookies(targetSession, cookies) {
  const sites = new Set(cookies.map(cookie => cookieSite(cookie.domain)).filter(Boolean));
  for (const existing of await targetSession.cookies.get({})) {
    if (!sites.has(cookieSite(existing.domain))) continue;
    const host = existing.domain.replace(/^\./, '');
    try { await targetSession.cookies.remove((existing.secure ? 'https://' : 'http://') + host + (existing.path || '/'), existing.name); } catch {}
  }
  let imported = 0;
  for (const cookie of cookies) {
    const details = electronCookie(cookie);
    if (!details) continue;
    try { await targetSession.cookies.set(details); imported += 1; } catch {}
  }
  await targetSession.cookies.flushStore?.();
  return imported;
}

// Load the check page in a hidden window on the embedded session itself: net
// fetches are rate-limited by Google and do not expose the final address.
async function targetSignedIn(targetSession) {
  const {BrowserWindow} = require('electron');
  const window = new BrowserWindow({show:false, webPreferences:{session:targetSession, sandbox:true, contextIsolation:true, nodeIntegration:false}});
  try {
    await Promise.race([window.loadURL(SESSION_CHECK_URL).catch(() => {}), sleep(15000)]);
    return !window.isDestroyed() && sessionLive(window.webContents.getURL());
  } catch { return false; }
  finally { if (!window.isDestroyed()) window.destroy(); }
}

// Google's sign-in pages keep a "Google Accounts"-style title; once the window
// shows anything else (YouTube, Gmail, the page that asked), sign-in finished.
function signInPageTitle(title) {
  return /google accounts|sign[ -]?in|verify it.s you|2-step|passkey|choose an account/i.test(String(title || ''));
}

function signInFinished(title) {
  const text = String(title || '').replace(/\s+-\s+(Brave|Google Chrome|Chromium|Microsoft​? Edge|Microsoft Edge)$/i, '').trim();
  if (!text || /^(new tab|about:blank|untitled|loading)/i.test(text)) return false;
  if (/^error \d{3}\b|that.s an error|\b[45]\d\d\b.*\berror\b/i.test(text)) return false;
  return !/google accounts|accounts\.google|accounts\.youtube|sign[ -]?in|couldn.t sign you in|verify it.s you|2-step|passkey/i.test(text);
}

// Windows: report the helper browser's window title about once a second, without
// attaching a debugger to the window the person signs in with.
function watchBrowserTitle({executable, profileDir, onTitle, spawn = spawnProcess}) {
  if (process.platform !== 'win32') return () => {};
  const quote = value => "'" + String(value).replace(/'/g, "''") + "'";
  const script = `$a=${quote('--user-data-dir=' + profileDir)};$n=${quote(path.basename(executable))};` +
    `while($true){$p=Get-CimInstance Win32_Process -Filter "Name='$n'"|?{$_.CommandLine -and $_.CommandLine.Contains($a) -and -not $_.CommandLine.Contains('--type=')}|select -First 1;` +
    `if($p){$t=(Get-Process -Id $p.ProcessId -EA SilentlyContinue).MainWindowTitle;[Console]::Out.WriteLine("$($p.ProcessId)\`t$t")}else{[Console]::Out.WriteLine("0\`t")};` +
    `[Console]::Out.Flush();Start-Sleep -Milliseconds 800}`;
  const child = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', Buffer.from(script, 'utf16le').toString('base64')], {stdio:['ignore', 'pipe', 'ignore'], windowsHide:true});
  let buffer = '';
  child.stdout?.on('data', chunk => {
    buffer += chunk.toString('utf8');
    const lines = buffer.split(/\r?\n/); buffer = lines.pop();
    for (const line of lines) { const [pid, ...title] = line.split('\t'); onTitle({pid:Number(pid) || 0, title:title.join('\t')}); }
  });
  return () => { if (child.exitCode === null) child.kill(); };
}

// A normal window close lets the browser write its cookies before exiting.
// taskkill's WM_CLOSE lands on Chromium's hidden windows and is ignored, so post
// it to the visible browser windows themselves.
function closeBrowserGracefully(pid, spawn = spawnProcess) {
  if (!pid) return;
  if (process.platform !== 'win32') { try { process.kill(pid, 'SIGTERM'); } catch {} return; }
  const script = `Add-Type @"
using System;using System.Text;using System.Runtime.InteropServices;
public class VellumClose{public delegate bool P(IntPtr h,IntPtr l);
[DllImport("user32.dll")]public static extern bool EnumWindows(P p,IntPtr l);
[DllImport("user32.dll")]public static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
[DllImport("user32.dll")]public static extern bool IsWindowVisible(IntPtr h);
[DllImport("user32.dll",CharSet=CharSet.Unicode)]public static extern int GetWindowTextLength(IntPtr h);
[DllImport("user32.dll",CharSet=CharSet.Unicode)]public static extern int GetClassName(IntPtr h,StringBuilder s,int n);
[DllImport("user32.dll")]public static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
public static void Close(uint pid){EnumWindows((h,l)=>{uint p;GetWindowThreadProcessId(h,out p);var c=new StringBuilder(64);GetClassName(h,c,64);
if(p==pid&&IsWindowVisible(h)&&GetWindowTextLength(h)>0&&c.ToString()=="Chrome_WidgetWin_1")PostMessage(h,0x0010,IntPtr.Zero,IntPtr.Zero);return true;},IntPtr.Zero);}}
"@
[VellumClose]::Close(${Number(pid)})`;
  spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', Buffer.from(script, 'utf16le').toString('base64')], {stdio:'ignore', windowsHide:true});
}

// Start the visible sign-in window clean: no tabs restored from earlier runs
// (they hide the sign-in page and make closing ask "Close all tabs?") and no
// "Restore pages?" prompt after a background run.
function prepareSignInProfile(profileDir) {
  const profile = path.join(profileDir, 'Default');
  for (const name of ['Sessions', 'Sessions_Encrypted', 'Current Session', 'Current Tabs', 'Last Session', 'Last Tabs']) {
    try { fs.rmSync(path.join(profile, name), {recursive:true, force:true}); } catch {}
  }
  const file = path.join(profile, 'Preferences');
  try {
    const preferences = JSON.parse(fs.readFileSync(file, 'utf8'));
    preferences.session = {...preferences.session, restore_on_startup:5};
    preferences.profile = {...preferences.profile, exit_type:'Normal', exited_cleanly:true};
    fs.writeFileSync(file, JSON.stringify(preferences));
  } catch {}
}

async function runBrowserSignIn({browser, profileDir, url, targetSession, onStatus = () => {}, signal, spawn = spawnProcess,
  watchTitle = watchBrowserTitle, probe = probeProfile, verify = targetSignedIn}) {
  const existing = fs.existsSync(profileDir);
  fs.mkdirSync(profileDir, {recursive:true});
  // A live session in the sign-in profile needs no window at all.
  if (existing) {
    onStatus({status:'checking', browser:browser.name});
    const found = await probe({executable:browser.path, profileDir, spawn, clearIfDead:true});
    if (found.live) {
      const imported = await importCookies(targetSession, found.cookies);
      if (await verify(targetSession)) return {imported, total:found.cookies.length, reused:true};
    }
  }
  if (signal?.aborted) throw new Error('Sign-in was cancelled.');
  onStatus({status:'waiting', browser:browser.name});
  prepareSignInProfile(profileDir);
  const child = spawn(browser.path, [
    `--user-data-dir=${profileDir}`, '--no-first-run', '--no-default-browser-check', '--new-window', url,
  ], {stdio:'ignore', detached:false});
  const abort = () => { if (child.exitCode === null) child.kill(); };
  signal?.addEventListener('abort', abort, {once:true});
  let finishedTitle = '', closing = false, sawWindow = false, sawSignIn = false;
  const stopWatching = watchTitle({executable:browser.path, profileDir, spawn, onTitle:({pid, title}) => {
    if (pid && title) sawWindow = true;
    // Require the finished title twice in a row so a redirect flash does not count.
    if (closing || !pid) return;
    if (!signInFinished(title)) { if (signInPageTitle(title)) sawSignIn = true; finishedTitle = ''; return; }
    // Only a page reached after Google's sign-in page counts as finished.
    if (!sawSignIn) return;
    if (finishedTitle !== title) { finishedTitle = title; return; }
    closing = true;
    onStatus({status:'finishing', browser:browser.name});
    closeBrowserGracefully(pid, spawn);
  }});
  try {
    await waitForProfileClosed(profileDir, child, signal);
  } finally {
    stopWatching();
    signal?.removeEventListener('abort', abort);
  }
  // The title watcher only runs on Windows; elsewhere the window is assumed.
  if (!sawWindow && process.platform === 'win32' && watchTitle === watchBrowserTitle) throw new Error(`${browser.name} didn’t open its sign-in window. Try again.`);
  onStatus({status:'importing', browser:browser.name});
  const found = await probe({executable:browser.path, profileDir, spawn});
  if (!found.live) throw new Error(`Google sign-in didn’t finish in ${browser.name}. Try again and wait until Google shows you signed in.`);
  const imported = await importCookies(targetSession, found.cookies);
  if (!await verify(targetSession)) throw new Error('Google didn’t accept the copied sign-in. Try signing in again.');
  return {imported, total:found.cookies.length};
}

module.exports = {needsBrowserSignIn, signInBrowsers, findSignInBrowser, defaultBrowser, electronCookie, readProfileCookies, probeProfile, importCookies, cookieSite, runBrowserSignIn, signInFinished, signInPageTitle, prepareSignInProfile, watchBrowserTitle};
