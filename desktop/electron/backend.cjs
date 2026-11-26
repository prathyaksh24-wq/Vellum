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
  for (const name of ['backend/pyproject.toml','docs/main.md','docs/SOUL.md','docs/PERSONALITY.md']) if(fs.existsSync(path.join(root,name)))files.push(path.join(root,name));
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

// Stop a process and everything it started. On Windows the venv python.exe is
// a launcher whose real interpreter is a child process, so the tree must go.
function killTree(pid) {
  if (!pid) return;
  try {
    if (process.platform === 'win32') {
      require('node:child_process').spawnSync('taskkill',['/PID',String(pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});
    } else process.kill(pid,'SIGKILL');
  } catch {}
}

// Find a Vellum backend that holds port 8000 but no longer answers. Only a
// process running Vellum's own backend entry point qualifies.
function stalledVellumBackend(port=8000) {
  if (process.platform !== 'win32') return null;
  try {
    const script=`$c=Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue|Select-Object -First 1;if($c){$p=Get-CimInstance Win32_Process -Filter ("ProcessId="+$c.OwningProcess);if($p){[string]$p.ProcessId+"|"+[string]$p.ParentProcessId+"|"+$p.CommandLine}}`;
    const result=require('node:child_process').spawnSync('powershell',['-NoProfile','-NonInteractive','-Command',script],{windowsHide:true,encoding:'utf8',timeout:15000});
    const [pid,parent,...command]=String(result.stdout||'').trim().split('|');
    if (!/^\d+$/.test(pid) || !/-m\s+agent\.desktop_entry\b/.test(command.join('|'))) return null;
    return {pid:Number(pid),parent:Number(parent)};
  } catch { return null; }
}

// The backend that holds this workspace's lease (it writes its PID beside the
// lock). Only a live process running Vellum's own backend entry point counts.
function leaseHolderBackend(workspaceRoot) {
  if (process.platform !== 'win32') return null;
  try {
    const recorded=JSON.parse(fs.readFileSync(path.join(workspaceRoot,'.api-runtime','backend.pid'),'utf8'));
    const pid=Number(recorded?.pid);
    if (!Number.isInteger(pid) || pid<=0 || pid===process.pid) return null;
    const script=`$p=Get-CimInstance Win32_Process -Filter "ProcessId=${pid}";if($p){[string]$p.ProcessId+"|"+$p.CommandLine}`;
    const result=require('node:child_process').spawnSync('powershell',['-NoProfile','-NonInteractive','-Command',script],{windowsHide:true,encoding:'utf8',timeout:15000});
    const [found,...command]=String(result.stdout||'').trim().split('|');
    if (Number(found)!==pid || !/-m\s+agent\.desktop_entry\b/.test(command.join('|'))) return null;
    return {pid};
  } catch { return null; }
}

function createBackendManager(spec,{spawnProcess=spawn,probe=readIdentity,occupied=portOccupied,findStalled=stalledVellumBackend,findLeaseHolder=leaseHolderBackend,terminate=killTree,timeoutMs=120000,pollMs=300,stopTimeoutMs=15000,busyWaitMs=20000,onExit=()=>{}}={}) {
  let child=null, exitPromise=null, exited=false, stopping=false;
  const outdated=identity=>{
    try {
      return identity?.service==='vellum' && identity.protocol_version===1 && Number.isInteger(identity.pid) && identity.pid>0 &&
        typeof identity.workspace_root==='string' && normalized(identity.workspace_root)===normalized(spec.workspaceRoot) &&
        identity.build_id!==spec.buildId;
    } catch { return false; }
  };
  async function start(onProgress=()=>{}) {
    let existing=await probe();
    // An older build of this same workspace's backend (left by a crash, a
    // restart race or an earlier session) is replaced, never reused. A
    // shutdown in progress can still answer briefly, so check until it is gone.
    for (let attempt=0; existing && outdated(existing) && attempt<3; attempt++) {
      terminate(existing.pid);
      const freed=Date.now()+10000;
      while (Date.now()<freed && await occupied()) await new Promise(resolve=>setTimeout(resolve,pollMs));
      existing=await probe();
    }
    if (existing) {validateIdentity(existing,spec.workspaceRoot,spec.buildId);return {url:BACKEND,reused:true};}
    if (await occupied()) {
      // A backend that is still booting answers shortly; give it time first.
      const until=Date.now()+busyWaitMs;
      while (!existing && Date.now()<until && await occupied()) {
        await new Promise(resolve=>setTimeout(resolve,pollMs));
        existing=await probe();
      }
      if (existing) {validateIdentity(existing,spec.workspaceRoot,spec.buildId);return {url:BACKEND,reused:true};}
      if (await occupied()) {
        // A hung Vellum backend from an earlier run is replaced; anything else is left alone.
        const stalled=findStalled();
        if (!stalled) throw new Error('Port 8000 is in use, but its backend could not be identified. Vellum will not stop or replace it. Quit the older server and try again.');
        terminate(stalled.parent && stalled.parent!==process.pid ? stalled.parent : stalled.pid);
        terminate(stalled.pid);
        const freed=Date.now()+10000;
        while (Date.now()<freed && await occupied()) await new Promise(resolve=>setTimeout(resolve,pollMs));
      }
    }
    // Nothing answers on the port, yet a backend may still hold the workspace
    // lease (one stuck while shutting down). Starting another would fail on the
    // lease forever, so the unresponsive holder is replaced.
    const holder=findLeaseHolder(spec.workspaceRoot);
    if (holder) {
      terminate(holder.pid);
      await new Promise(resolve=>setTimeout(resolve,1500));
    }
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
          VELLUM_DESKTOP_LAUNCH_ID:launchId,VELLUM_DESKTOP_BUILD_ID:spec.buildId,
          API_HOST:'127.0.0.1',API_PORT:'8000'},
      });
    } finally {fs.closeSync(output);fs.closeSync(errors);}
    let launchError;
    child.once('error',()=>{launchError=true;});
    child.stdin.on('error',()=>{});
    exitPromise=new Promise(resolve=>child.once('exit',code=>{exited=true;resolve();if(!stopping){try{onExit(code);}catch{}}}));
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
    if(!stopping){stopping=true;try{child.stdin.end('stop\n');}catch{}}
    let timer;
    const timedOut=await Promise.race([exitPromise.then(()=>false),new Promise(resolve=>{timer=setTimeout(()=>resolve(true),stopTimeoutMs);})]);
    clearTimeout(timer);
    // A backend that cannot finish shutting down must never block quitting or
    // restarting Vellum; its SQLite stores are transactional.
    if (timedOut) {terminate(child.pid);await Promise.race([exitPromise,new Promise(resolve=>setTimeout(resolve,5000))]);}
  }
  // Replace an owned backend that crashed or stopped answering.
  function kill() {
    if (!child?.pid || exited) return Promise.resolve();
    stopping=true;terminate(child.pid);
    return Promise.race([exitPromise,new Promise(resolve=>setTimeout(resolve,5000))]);
  }
  return {start,stop,kill,get workspaceRoot(){return spec.workspaceRoot;},get owned(){return Boolean(child?.pid&&!exited);}};
}

// Health of the backend's HTTP loop, independent of identity checks.
async function backendResponds(base=BACKEND,timeoutMs=4000) {
  try {
    const response=await fetch(base+'/health',{signal:AbortSignal.timeout(timeoutMs),redirect:'error'});
    return response.ok;
  } catch { return false; }
}

module.exports={BACKEND,UI_PORT,sourceBuildId,validateIdentity,launchSpec,createBackendManager,backendResponds,killTree,leaseHolderBackend};
