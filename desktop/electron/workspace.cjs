const fs=require('node:fs');
const path=require('node:path');

// A first launch on a new computer gets a ready workspace (Documents\Vellum)
// instead of a folder picker; an existing saved or configured one always wins.
function defaultWorkspace(app) {
  let documents;
  try { documents=app.getPath('documents'); } catch { documents=path.join(app.getPath('home'),'Documents'); }
  return path.join(documents,'Vellum');
}

async function selectWorkspace(app,_dialog,{sourceRoot,configured=process.env.VELLUM_WORKSPACE_ROOT,fallback=()=>defaultWorkspace(app)}={}) {
  const file=path.join(app.getPath('userData'),'desktop-workspace.json');
  let selected=configured;
  if(!selected && !app.isPackaged) selected=sourceRoot;
  if(!selected) {
    try {
      const saved=JSON.parse(fs.readFileSync(file,'utf8'));
      if(saved.version!==1||typeof saved.workspaceRoot!=='string')throw new Error('Invalid workspace selection.');
      selected=saved.workspaceRoot;
    }
    catch(error){if(error.code!=='ENOENT')throw new Error('The saved workspace selection could not be read. Open your desktop profile and repair desktop-workspace.json.');}
  }
  if(!selected) {
    selected=fallback();
    fs.mkdirSync(path.join(selected,'data'),{recursive:true});
  }
  if(typeof selected!=='string'||!path.isAbsolute(selected))throw new Error('Choose an absolute Vellum workspace folder.');
  selected=fs.realpathSync(selected);
  if(!fs.existsSync(path.join(selected,'data'))||!fs.statSync(path.join(selected,'data')).isDirectory())throw new Error('This folder does not contain Vellum data. Choose the inner Vellum workspace folder.');
  if(app.isPackaged){
    fs.mkdirSync(path.dirname(file),{recursive:true});
    const staging=file+'.tmp';
    fs.writeFileSync(staging,JSON.stringify({version:1,workspaceRoot:selected}),{mode:0o600});
    fs.renameSync(staging,file);
  }
  return selected;
}

module.exports={selectWorkspace,defaultWorkspace};
