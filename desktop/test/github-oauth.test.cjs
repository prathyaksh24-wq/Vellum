const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {createDesktopHost}=require('../electron/host.cjs');
const {workspaceURL}=require('../electron/policy.cjs');

function fixture({openExternal}={}){
  const instances=[],prompts=[],external=[],workspace=workspaceURL();let invoke;
  class Window extends EventEmitter{
    constructor(options){
      super();this.options=options;this.destroyed=false;this.focused=0;instances.push(this);
      this.webContents=new EventEmitter();
      Object.assign(this.webContents,{id:instances.length,getURL:()=>this.url,
        setWindowOpenHandler:fn=>this.openHandler=fn,
        session:{setPermissionCheckHandler:fn=>this.check=fn,setPermissionRequestHandler:fn=>this.permission=fn}});
      this.webContents.mainFrame={url:workspace};
    }
    isDestroyed(){return this.destroyed;}
    isMinimized(){return false;}
    show(){}
    focus(){this.focused++;}
    loadURL(url){this.url=url;return Promise.resolve();}
    close(){this.destroyed=true;this.emit('closed');}
    destroy(){this.close();}
  }
  const host=createDesktopHost({BrowserWindow:Window,ipcMain:{handle(channel,fn){if(channel==='vellum:desktop')invoke=fn;}},screen:{},
    dialog:{showMessageBox(_window,options){prompts.push(options);return Promise.resolve({response:0});}},shell:{openExternal(url){external.push(url);return openExternal?openExternal(url):Promise.resolve();}}},
    {workspace,showWindows:false});
  const owner=host.openWorkspace();
  return {host,owner,instances,prompts,external,workspace,invoke:(command,args)=>invoke({sender:owner.webContents,senderFrame:owner.webContents.mainFrame},command,args)};
}

for(const provider of ['github','linear','slack','airtable','notion','firecrawl','apify','exa','tavily','supabase','district','zomato','swiggy','vercel','clickup','asana','hubspot'])test(provider+' OAuth opens the system browser without embedded auth content',async()=>{
  const f=fixture();
  const url='http://127.0.0.1:8000/api/plugins/'+provider+'/oauth/open?flow_id='+'a'.repeat(43);
  assert.deepEqual(f.owner.openHandler({url}),{action:'deny'});
  await Promise.resolve();
  assert.equal(f.instances.length,1);assert.equal(f.prompts.length,0);
  assert.deepEqual(f.external,[url]);
  f.owner.openHandler({url});assert.equal(f.external.length,1);
  f.owner.close();
});

test('explicit sign-in IPC waits for the system browser and reports launch failures',async()=>{
  let resolve;
  const f=fixture({openExternal:()=>new Promise(done=>{resolve=done;})});
  const url='http://127.0.0.1:8000/api/plugins/swiggy/oauth/open?flow_id='+'a'.repeat(43);
  let settled=false;
  const pending=f.invoke('open_plugin_oauth',{url}).then(value=>{settled=true;return value;});
  await Promise.resolve();assert.equal(settled,false);assert.deepEqual(f.external,[url]);
  resolve();assert.deepEqual(await pending,{opened:true});f.owner.close();
  const broken=fixture({openExternal:()=>Promise.reject(new Error('OS launch failed'))});
  await assert.rejects(broken.invoke('open_plugin_oauth',{url}),/Could not open your default browser/);
  broken.owner.close();
});

test('sign-in IPC rejects arbitrary links and unregistered flow entries',async()=>{
  const f=fixture();
  for(const url of ['https://example.test','http://127.0.0.1:8000/api/plugins/github/oauth/open?flow_id=short']){
    await assert.rejects(f.invoke('open_plugin_oauth',{url}));
  }
  assert.deepEqual(f.external,[]);f.owner.close();
});

test('arbitrary origins, extra parameters and ambiguous flow IDs cannot create auth children',()=>{
  const f=fixture(),id='a'.repeat(43);
  for(const url of [
    'https://example.test/api/plugins/github/oauth/open?flow_id='+id,
    'http://127.0.0.1:8000/unrelated?flow_id='+id,
    'http://127.0.0.1:8000/api/plugins/github/oauth/open?flow_id=short',
    'http://127.0.0.1:8000/api/plugins/github/oauth/open?flow_id='+id+'&next=https://example.test',
    'http://127.0.0.1:8000/api/plugins/github/oauth/open?flow_id='+id+'&flow_id='+id,
  ])assert.deepEqual(f.owner.openHandler({url}),{action:'deny'});
  assert.equal(f.instances.length,1);
});


test('external authorization is restricted to an exact local flow entry',()=>{
  const f=fixture(),id='a'.repeat(43);
  for(const url of [
    'http://127.0.0.1:8001/api/plugins/slack/oauth/open?flow_id='+id,
    'http://user:pass@127.0.0.1:8000/api/plugins/linear/oauth/open?flow_id='+id,
    'http://127.0.0.1:8000/api/plugins/linear/oauth/open?flow_id='+id+'#extra',
  ])f.owner.openHandler({url});
  assert.deepEqual(f.external,[]);assert.equal(f.instances.length,1);
});
