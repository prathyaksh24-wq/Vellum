const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {createDesktopHost}=require('../electron/host.cjs');
const {workspaceURL}=require('../electron/policy.cjs');

function fixture(){
  const instances=[],prompts=[],workspace=workspaceURL();
  class Window extends EventEmitter{
    constructor(options){
      super();this.options=options;this.destroyed=false;this.focused=0;instances.push(this);
      this.webContents=new EventEmitter();
      Object.assign(this.webContents,{id:instances.length,getURL:()=>this.url,
        setWindowOpenHandler:fn=>this.openHandler=fn,
        session:{setPermissionCheckHandler:fn=>this.check=fn,setPermissionRequestHandler:fn=>this.permission=fn}});
    }
    isDestroyed(){return this.destroyed;}
    isMinimized(){return false;}
    show(){}
    focus(){this.focused++;}
    loadURL(url){this.url=url;return Promise.resolve();}
    close(){this.destroyed=true;this.emit('closed');}
    destroy(){this.close();}
  }
  const host=createDesktopHost({BrowserWindow:Window,ipcMain:{handle(){}},screen:{},
    dialog:{showMessageBox(_window,options){prompts.push(options);return Promise.resolve({response:0});}},shell:{}},
    {workspace,showWindows:false});
  const owner=host.openWorkspace();
  return {host,owner,instances,prompts,workspace};
}

test('GitHub OAuth gets an isolated child and returning to Vellum closes it',()=>{
  const f=fixture();
  const url='http://127.0.0.1:8000/api/plugins/github/oauth/open?flow_id='+'a'.repeat(43);
  assert.deepEqual(f.owner.openHandler({url}),{action:'deny'});
  assert.equal(f.instances.length,2);assert.equal(f.prompts.length,0);
  const auth=f.instances[1],preferences=auth.options.webPreferences;
  assert.equal(auth.options.parent,f.owner);
  assert.equal(preferences.preload,undefined);
  assert.equal(preferences.nodeIntegration,false);
  assert.equal(preferences.contextIsolation,true);
  assert.equal(preferences.sandbox,true);
  assert.equal(auth.check(),false);
  let permission;auth.permission({},'media',allowed=>permission=allowed);assert.equal(permission,false);
  let prevented=false;
  auth.webContents.emit('will-navigate',{preventDefault(){prevented=true;}},f.workspace);
  assert.equal(prevented,true);assert.equal(auth.destroyed,true);assert.equal(f.owner.focused,1);
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
