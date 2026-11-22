const {test}=require('node:test');
const assert=require('node:assert/strict');
const {needsBrowserSignIn,findSignInBrowser,electronCookie,signInFinished,defaultBrowser}=require('../electron/browser-signin.cjs');

test('only Google account sign-in pages ask for a real browser',()=>{
  for(const url of ['https://accounts.google.com/v3/signin/identifier?service=youtube','https://accounts.google.com/ServiceLogin?continue=https://www.youtube.com/','https://accounts.google.com/v3/signin/rejected?x=1','https://accounts.google.com/o/oauth2/v2/auth?client_id=x'])
    assert.equal(needsBrowserSignIn(url),true,url);
  for(const url of ['https://www.youtube.com/','https://accounts.google.com/','http://accounts.google.com/signin','https://accounts.google.com.evil.test/signin','https://myaccount.google.com/signin','not a url'])
    assert.equal(needsBrowserSignIn(url),false,url);
});

test('the sign-in browser prefers Brave, then the default browser, then any installed one, and honours an explicit override',()=>{
  const present=new Set();
  const find=(env,preferred=()=>null)=>findSignInBrowser({env,exists:file=>present.has(file),preferred});
  const env={PROGRAMFILES:'P',['PROGRAMFILES(X86)']:'X',LOCALAPPDATA:'L'};
  assert.equal(find(env),null);
  const candidates=require('../electron/browser-signin.cjs').signInBrowsers(env);
  const edge=candidates.find(item=>item.name==='Edge'),brave=candidates.find(item=>item.name==='Brave');
  present.add(edge.path); assert.equal(find(env).name,'Edge');
  const chrome=candidates.find(item=>item.name==='Chrome');present.add(chrome.path);
  assert.equal(find(env,()=>({name:'Edge',path:edge.path})).name,'Edge','without Brave the default browser wins');
  assert.equal(find(env,()=>({name:'Edge',path:'C:/missing/msedge.exe'})).name,'Chrome');
  present.add(brave.path); assert.equal(find(env,()=>({name:'Edge',path:edge.path})).name,'Brave','Brave wins when installed');
  present.add('D:/tools/chromium.exe'); assert.equal(find({...env,VELLUM_SIGNIN_BROWSER:'D:/tools/chromium.exe'}).path,'D:/tools/chromium.exe');
});

test('imported cookies keep their scope, expiry and flags',()=>{
  assert.deepEqual(electronCookie({name:'SID',value:'v',domain:'.google.com',path:'/',secure:true,httpOnly:true,sameSite:'None',expires:1900000000,session:false}),
    {url:'https://google.com/',name:'SID',value:'v',path:'/',secure:true,httpOnly:true,sameSite:'no_restriction',domain:'.google.com',expirationDate:1900000000});
  // Host-only and __Host- cookies must stay host-only; session cookies carry no expiry.
  const host=electronCookie({name:'__Host-GAPS',value:'v',domain:'accounts.google.com',path:'/',secure:true,httpOnly:true,expires:-1,session:true});
  assert.equal(host.domain,undefined); assert.equal(host.expirationDate,undefined); assert.equal(host.url,'https://accounts.google.com/'); assert.equal(host.sameSite,'unspecified');
  assert.equal(electronCookie({name:'__Host-x',value:'v',domain:'.example.com',path:'/',secure:true}).domain,undefined);
  assert.equal(electronCookie({name:'p',value:'v',domain:'.example.com',partitionKey:{topLevelSite:'https://a.test'}}),null);
  assert.equal(electronCookie({name:'p',value:'v',domain:'.youtube.com',partitionKey:{topLevelSite:'https://youtube.com',hasCrossSiteAncestor:true}}),null);
  assert.equal(electronCookie({name:'__Secure-YNID',value:'v',domain:'.youtube.com',path:'/',secure:true,partitionKey:{topLevelSite:'https://youtube.com',hasCrossSiteAncestor:false}}).domain,'.youtube.com');
  assert.equal(electronCookie({name:'',domain:'.example.com'}),null);
});

test('sign-in counts as finished once the window leaves Google account pages',()=>{
  for(const title of ['Error 400 (Bad Request)!!1 - Brave','Sign in - Google Accounts - Brave','accounts.google.com/v3/signin - Brave','Couldn’t sign you in - Brave','Verify it’s you - Google Chrome','New Tab - Brave','',
    'Sign in - Google Accounts - Personal - Microsoft​ Edge']) assert.equal(signInFinished(title),false,title);
  for(const title of ['YouTube - Brave','Inbox (3) - you@example.com - Gmail - Google Chrome','YouTube and 1 more page - Personal - Microsoft​ Edge']) assert.equal(signInFinished(title),true,title);
});

test('the default browser is used only when it is Chromium-based',()=>{
  const chrome=String.raw`C:\Program Files\Google\Chrome\Application\chrome.exe`;
  const commands={ChromeHTML:`"${chrome}" --single-argument %1`,MSEdgeHTM:String.raw`"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --single-argument %1`,
    'FirefoxURL-308046B0AF4A39CB':String.raw`"C:\Program Files\Mozilla Firefox\firefox.exe" -osint -url "%1"`,'bad;id':'x'};
  const registry=(legacy,latest='')=>(_exe,args)=>{
    const key=args[1];
    if(key.endsWith('UserChoiceLatest\\ProgId')){if(!latest)throw new Error('missing');return `    ProgId    REG_SZ    ${latest}\r\n`;}
    if(key.endsWith('UserChoice'))return `    ProgId    REG_SZ    ${legacy}\r\n`;
    const progId=/^HKCR\\(.+)\\shell\\open\\command$/.exec(key)?.[1];
    return `    (Default)    REG_SZ    ${commands[progId]}\r\n`;
  };
  if(process.platform!=='win32'){assert.equal(defaultBrowser({run:registry('ChromeHTML')}),null);return;}
  assert.deepEqual(defaultBrowser({run:registry('ChromeHTML')}),{name:'Chrome',path:chrome});
  assert.equal(defaultBrowser({run:registry('FirefoxURL-308046B0AF4A39CB')}),null);
  // Windows 11 keeps the live choice in UserChoiceLatest and leaves UserChoice stale.
  assert.equal(defaultBrowser({run:registry('MSEdgeHTM','ChromeHTML')}).name,'Chrome');
  assert.equal(defaultBrowser({run:registry('bad;id')}),null);
  assert.equal(defaultBrowser({run:()=>{throw new Error('no key');}}),null);
});

const {runBrowserSignIn,importCookies,cookieSite}=require('../electron/browser-signin.cjs');
const os=require('node:os'),fsp=require('node:fs'),path=require('node:path');
const {EventEmitter}=require('node:events');
function fakeSession(initial=[]){
  const jar=new Map(initial.map(c=>[c.domain+'|'+c.name,c]));
  return {jar,cookies:{
    get:async()=>[...jar.values()],
    remove:async(url,name)=>{const host=new URL(url).hostname;for(const [key,c] of jar)if(c.name===name&&c.domain.replace(/^\./,'')===host)jar.delete(key);},
    set:async d=>{jar.set((d.domain||new URL(d.url).hostname)+'|'+d.name,{domain:d.domain||new URL(d.url).hostname,name:d.name,value:d.value,secure:d.secure,path:d.path});},
    flushStore:async()=>{}}};
}
const live=[{name:'SID',value:'new',domain:'.google.com',path:'/',secure:true},{name:'LOGIN_INFO',value:'new',domain:'.youtube.com',path:'/',secure:true}];
const browser={name:'Brave',path:'brave.exe'};
const visibleSpawn=launches=>(exe,args)=>{launches.push(args);const child=new EventEmitter();child.exitCode=0;child.kill=()=>{};return child;};

test('the import replaces a site’s old cookies instead of mixing sessions',async()=>{
  assert.equal(cookieSite('.accounts.google.com'),'google.com');assert.equal(cookieSite('www.google.co.in'),'google.co.in');assert.equal(cookieSite('localhost'),'');
  const target=fakeSession([{name:'SID',value:'dead',domain:'.google.com',secure:true,path:'/'},{name:'OLD',value:'x',domain:'.youtube.com',secure:true,path:'/'},{name:'keep',value:'k',domain:'github.com',secure:true,path:'/'}]);
  assert.equal(await importCookies(target,live),2);
  const names=[...target.jar.values()].map(c=>c.domain+':'+c.name+'='+c.value).sort();
  assert.deepEqual(names,['.google.com:SID=new','.youtube.com:LOGIN_INFO=new','github.com:keep=k']);
});

test('a live saved session signs in without opening a window',async()=>{
  const dir=fsp.mkdtempSync(path.join(os.tmpdir(),'vellum-signin-'));const launches=[],statuses=[];
  const result=await runBrowserSignIn({browser,profileDir:dir,url:'https://accounts.google.com/ServiceLogin',targetSession:fakeSession(),onStatus:s=>statuses.push(s.status),
    spawn:visibleSpawn(launches),probe:async()=>({live:true,cookies:live}),verify:async()=>true,watchTitle:()=>()=>{}});
  assert.equal(result.reused,true);assert.equal(launches.length,0);assert.deepEqual(statuses,['checking']);
});

test('a dead saved session is cleared and the person signs in again in the real browser',async()=>{
  const dir=fsp.mkdtempSync(path.join(os.tmpdir(),'vellum-signin-'));const launches=[],probes=[],statuses=[];
  let signedIn=false;
  const result=await runBrowserSignIn({browser,profileDir:dir,url:'https://accounts.google.com/ServiceLogin',targetSession:fakeSession(),onStatus:s=>statuses.push(s.status),
    spawn:visibleSpawn(launches),probe:async options=>{probes.push(options.clearIfDead===true);return signedIn?{live:true,cookies:live}:{live:false,cookies:[]};},
    verify:async()=>signedIn,watchTitle:()=>{signedIn=true;return()=>{};}});
  assert.deepEqual(probes,[true,false],'the first probe clears the dead session');
  assert.equal(launches.length,1);assert.ok(launches[0].includes('https://accounts.google.com/ServiceLogin'));
  assert.deepEqual(statuses,['checking','waiting','importing']);assert.equal(result.imported,2);
});

test('only a page reached after Google’s sign-in page finishes the hand-off, and old tabs are cleared',async()=>{
  const dir=fsp.mkdtempSync(path.join(os.tmpdir(),'vellum-signin-'));
  fsp.mkdirSync(path.join(dir,'Default','Sessions'),{recursive:true});fsp.writeFileSync(path.join(dir,'Default','Sessions','Tabs_1'),'old');
  fsp.writeFileSync(path.join(dir,'Default','Preferences'),JSON.stringify({profile:{exit_type:'Crashed'}}));
  const {prepareSignInProfile}=require('../electron/browser-signin.cjs');prepareSignInProfile(dir);
  assert.equal(fsp.existsSync(path.join(dir,'Default','Sessions')),false);
  const prefs=JSON.parse(fsp.readFileSync(path.join(dir,'Default','Preferences'),'utf8'));assert.equal(prefs.session.restore_on_startup,5);assert.equal(prefs.profile.exit_type,'Normal');
  const statuses=[];let report;
  const run=runBrowserSignIn({browser,profileDir:dir,url:'https://accounts.google.com/ServiceLogin',targetSession:fakeSession(),onStatus:s=>statuses.push(s.status),
    spawn:(exe,args)=>{const child=new EventEmitter();child.exitCode=null;child.kill=()=>{};if(!args.includes('--new-window'))return child;setTimeout(()=>{child.exitCode=0;child.emit('exit',0);},30);return child;},
    probe:async()=>({live:false,cookies:[]}),verify:async()=>false,watchTitle:({onTitle})=>{report=onTitle;return()=>{};}});
  await new Promise(r=>setTimeout(r,10));
  // A restored YouTube tab before any sign-in page must not count.
  report({pid:7,title:'YouTube - Brave'});report({pid:7,title:'YouTube - Brave'});
  assert.ok(!statuses.includes('finishing'));
  report({pid:7,title:'Sign in - Google Accounts - Brave'});report({pid:7,title:'YouTube - Brave'});report({pid:7,title:'YouTube - Brave'});
  assert.ok(statuses.includes('finishing'));
  await assert.rejects(run,/didn’t finish/);
});

test('closing the browser before signing in reports it instead of importing a dead session',async()=>{
  const dir=fsp.mkdtempSync(path.join(os.tmpdir(),'vellum-signin-'));
  await assert.rejects(runBrowserSignIn({browser,profileDir:dir,url:'https://accounts.google.com/ServiceLogin',targetSession:fakeSession(),
    spawn:visibleSpawn([]),probe:async()=>({live:false,cookies:[]}),verify:async()=>false,watchTitle:()=>()=>{}}),/didn’t finish/);
});
