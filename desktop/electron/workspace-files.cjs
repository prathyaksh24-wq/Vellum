const fs=require('node:fs/promises');
const path=require('node:path');

const blocked=part=>part==='.git'||part==='.env'||part.startsWith('.env.')||['node_modules','.venv','.desktop-runtime','.api-runtime'].includes(part);
async function readWorkspaceFiles(workspaceRoot,{operation='list',relativePath=''}){
  const root=await fs.realpath(workspaceRoot);
  if(typeof relativePath!=='string'||relativePath.length>2048||path.isAbsolute(relativePath)||relativePath.includes('\0'))throw new Error('Choose a workspace file.');
  if(relativePath.split(/[\\/]/).some(blocked))throw new Error('This path is not available in the file browser.');
  const target=await fs.realpath(path.resolve(root,relativePath)),relative=path.relative(root,target);
  if(relative==='..'||relative.startsWith('..'+path.sep)||path.isAbsolute(relative)||relative.split(path.sep).some(blocked))throw new Error('Choose a file inside this workspace.');
  const stat=await fs.stat(target);
  if(operation==='list'){
    if(!stat.isDirectory())throw new Error('Choose a workspace folder.');
    const entries=(await fs.readdir(target,{withFileTypes:true})).filter(item=>!item.name.startsWith('.')&&!blocked(item.name));
    return {workspace_root:root,path:relative,entries:entries.filter(item=>item.isDirectory()||item.isFile()).sort((a,b)=>Number(b.isDirectory())-Number(a.isDirectory())||a.name.localeCompare(b.name)).slice(0,500).map(item=>({name:item.name,path:path.join(relative,item.name),directory:item.isDirectory()})),truncated:entries.length>500};
  }
  if(operation!=='read'||!stat.isFile())throw new Error('Choose a readable workspace file.');
  if(stat.size>2*1024*1024)throw new Error('Preview is limited to files smaller than 2 MB.');
  const bytes=await fs.readFile(target),extension=path.extname(target).toLowerCase();
  const mime={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.gif':'image/gif','.webp':'image/webp','.pdf':'application/pdf'}[extension];
  if(mime)return {id:relative,name:path.basename(target),mime_type:mime,data_url:'data:'+mime+';base64,'+bytes.toString('base64')};
  if(bytes.includes(0))throw new Error('A text preview is unavailable for this file type.');
  return {id:relative,name:path.basename(target),mime_type:extension==='.html'?'text/html':'text/plain',text_content:bytes.toString('utf8')};
}
module.exports={readWorkspaceFiles};
