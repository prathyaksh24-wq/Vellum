const fs=require('node:fs');
const path=require('node:path');

async function selectWorkspace(app,dialog,{sourceRoot,configured=process.env.VELLUM_WORKSPACE_ROOT}={}) {
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
    const result=await dialog.showOpenDialog({title:'Choose your existing Vellum workspace',
      message:'Choose the Vellum folder containing your data directory. Your chats, accounts and settings stay there.',
      properties:['openDirectory']});
    if(result.canceled)return null;
    selected=result.filePaths[0];
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

module.exports={selectWorkspace};
