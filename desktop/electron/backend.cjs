// Only the main process owns backend lifecycle. Renderers cannot choose a
// command, executable, working directory or environment.
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const {spawn} = require('node:child_process');
const {createHash,randomBytes} = require('node:crypto');

const BACKEND = 'http://127.0.0.1:8000';
const UI_PORT = 5184;

function normalized(value) {
  const resolved = fs.realpathSync(value);
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved;
}

function sourceBuildId(root) {
  const files = [], extensions = new Set(['.py','.json','.yaml','.yml','.ps1','.md','.txt']);
  function visit(directory) {
    if (!fs.existsSync(directory)) return;
    for (const item of fs.readdirSync(directory,{withFileTypes:true})) {
      if (['__pycache__','node_modules','.git','tests'].includes(item.name) || item.isSymbolicLink()) continue;
      const file=path.join(directory,item.name);
      if (item.isDirectory()) visit(file);
      else if (extensions.has(path.extname(file)) && !['auth.json','oauth-flow.json'].includes(item.name)) files.push(file);
    }
  }
  for (const directory of ['backend/agent','plugins','scripts']) visit(path.join(root,directory));
  for (const name of ['backend/pyproject.toml','docs/SOUL.md']) if(fs.existsSync(path.join(root,name)))files.push(path.join(root,name));
  const relative=file=>path.relative(root,file).split(path.sep).join('/');
  files.sort((a,b)=>Buffer.compare(Buffer.from(relative(a)),Buffer.from(relative(b))));
  const hash=createHash('sha256');
  for (const file of files) hash.update(relative(file)+'\0').update(fs.readFileSync(file)).update('\0');
  return hash.digest('hex');
}

function validateIdentity(identity, root, buildId) {
  if (identity?.service !== 'vellum' || identity.protocol_version !== 1 ||
      typeof identity.workspace_root !== 'string' || !path.isAbsolute(identity.workspace_root) || normalized(identity.workspace_root) !== normalized(root)) {
    throw new Error('Port 8000 belongs to another service or Vellum workspace. Close that backend or select its workspace; Vellum has not changed it.');
  }
  if (identity.build_id !== buildId) {
    throw new Error('A different Vellum backend version is running for this workspace. Quit that instance before opening this version. Your data has not been moved.');
  }
}

async function readIdentity(base=BACKEND) {
  try {
    const response=await fetch(base+'/api/desktop/runtime',{signal:AbortSignal.timeout(1500),redirect:'error'});
    return response.ok ? await response.json() : null;
  } catch { return null; }
}

async function portOccupied(port=8000) {
  return new Promise(resolve=>{
    const socket=net.connect({host:'127.0.0.1',port});
    const finish=value=>{socket.destroy();resolve(value);};
    socket.once('connect',()=>finish(true));
    socket.once('error',()=>finish(false));
    socket.setTimeout(1000,()=>finish(true));
  });
}

function launchSpec({packaged,resourcesPath,sourceRoot,workspaceRoot}) {
  const runtime=packaged?path.join(resourcesPath,'backend-runtime'):null;
  const codeRoot=runtime?path.join(runtime,'app'):sourceRoot;
  const python=runtime?path.join(runtime,'python','python.exe'):path.join(sourceRoot,'.venv','Scripts','python.exe');
  if (!fs.existsSync(python)) throw new Error(packaged
    ? 'The bundled Vellum backend is missing. Use a complete desktop release.'
    : 'The Vellum Python environment is missing. Run the development setup first.');
  const manifest=runtime?JSON.parse(fs.readFileSync(path.join(codeRoot,'desktop-backend.json'),'utf8')):null;
  if (manifest && (manifest.protocol_version!==1 || !/^[a-f0-9]{64}$/.test(manifest.build_id)))throw new Error('The bundled backend manifest is invalid.');
  return {python,pythonHome:runtime?path.join(runtime,'python'):null,codeRoot,workspaceRoot,buildId:manifest?.build_id || sourceBuildId(codeRoot)};
}

function createBackendManager(spec,{spawnProcess=spawn,probe=readIdentity,occupied=portOccupied,timeoutMs=120000,pollMs=300,stopTimeoutMs=20000}={}) {
  let child=null, exitPromise=null, exited=false, stopping=false;
  async function start(onProgress=()=>{}) {
    const existing=await probe();
    if (existing) {validateIdentity(existing,spec.workspaceRoot,spec.buildId);return {url:BACKEND,reused:true};}
    if (await occupied()) throw new Error('Port 8000 is in use, but its backend could not be identified. Vellum will not stop or replace it. Quit the older server and try again.');
    onProgress('Starting your workspace…');
    const directory=path.join(spec.workspaceRoot,'.api-runtime');
    fs.mkdirSync(directory,{recursive:true});
    const output=fs.openSync(path.join(directory,'desktop-backend.log'),'a',0o600);
    const errors=fs.openSync(path.join(directory,'desktop-backend.err.log'),'a',0o600);
    const launchId=randomBytes(16).toString('hex');
    try {
      child=spawnProcess(spec.python,['-u','-m','agent.desktop_entry'],{
        cwd:spec.workspaceRoot,windowsHide:true,stdio:['pipe',output,errors],
        env:{...process.env,PYTHONPATH:[path.join(spec.codeRoot,'backend'),spec.codeRoot].join(path.delimiter),
          ...(spec.pythonHome?{PYTHONHOME:spec.pythonHome}:{}),
          VELLUM_WORKSPACE_ROOT:spec.workspaceRoot,PYTHONNOUSERSITE:'1',PYTHONDONTWRITEBYTECODE:'1',
          VELLUM_DESKTOP_LAUNCH_ID:launchId,
          API_HOST:'127.0.0.1',API_PORT:'8000'},
      });
    } finally {fs.closeSync(output);fs.closeSync(errors);}
    let launchError;
    child.once('error',()=>{launchError=true;});
    child.stdin.on('error',()=>{});
    exitPromise=new Promise(resolve=>child.once('exit',()=>{exited=true;resolve();}));
    const deadline=Date.now()+timeoutMs;
    while(Date.now()<deadline) {
      if (launchError || exited) throw new Error('The Vellum backend could not start. Open the startup logs for details.');
      const identity=await probe();
      if (identity) {
        validateIdentity(identity,spec.workspaceRoot,spec.buildId);
        // Windows venv python.exe may redirect to another interpreter process.
        // Match this launch, not the redirector's PID. Reused services never
        // acquire ownership of this private parent/child shutdown pipe.
        if(identity.launch_id!==launchId)throw new Error('Another backend started while Vellum was opening. Quit the competing instance and retry.');
        return {url:BACKEND,reused:false};
      }
      await new Promise(resolve=>setTimeout(resolve,pollMs));
    }
    throw new Error('The backend is taking longer than two minutes to start. Open the startup logs, then retry.');
  }
  async function stop() {
    if (!child?.pid || exited) return; // Never stop a reused development backend.
    if(!stopping){stopping=true;child.stdin.end('stop\n');}
    let timer;
    try {await Promise.race([exitPromise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Vellum is still finishing background work. Wait a moment and quit again.')),stopTimeoutMs);})]);}
    finally{clearTimeout(timer);}
  }
  return {start,stop,get workspaceRoot(){return spec.workspaceRoot;},get owned(){return Boolean(child?.pid&&!exited);}};
}

module.exports={BACKEND,UI_PORT,sourceBuildId,validateIdentity,launchSpec,createBackendManager};
