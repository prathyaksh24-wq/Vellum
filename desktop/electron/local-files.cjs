// Read-only, user-directed file browsing for the trusted desktop workspace.
const fs=require('node:fs/promises');
const path=require('node:path');
const os=require('node:os');
function createLocalFiles({root=path.parse(os.homedir()).root}={}){
  return async function localFiles({operation,path:requested}){
    if(!['list','preview'].includes(operation))throw new Error('Choose a read-only file operation.');
    const base=await fs.realpath(root);
    if(requested && (!path.isAbsolute(requested)||requested.startsWith('\\\\')||requested.startsWith('//')))throw new Error('Choose an absolute path on the local drive.');
    const target=await fs.realpath(requested||base),relative=path.relative(base,target);
    if(relative==='..'||relative.startsWith('..'+path.sep)||path.isAbsolute(relative))throw new Error('Choose a path on the local drive.');
    const stat=await fs.stat(target);
    if(operation==='list'){
      if(!stat.isDirectory())throw new Error('Choose a folder.');
      const entries=(await fs.readdir(target,{withFileTypes:true})).filter(item=>item.isDirectory()||item.isFile()).sort((a,b)=>Number(b.isDirectory())-Number(a.isDirectory())||a.name.localeCompare(b.name));
      return {path:target,parent:target===base?null:path.dirname(target),entries:entries.slice(0,2000).map(item=>({name:item.name,path:path.join(target,item.name),kind:item.isDirectory()?'directory':'file'})),truncated:entries.length>2000};
    }
    if(!stat.isFile())throw new Error('Choose a file.');
    const name=path.basename(target),extension=path.extname(name).toLowerCase();
    const images={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.gif':'image/gif'};
    const text=new Set(['.txt','.md','.json','.csv','.log','.py','.js','.jsx','.ts','.tsx','.css','.html','.xml','.yaml','.yml','.toml','.ini','.ps1','.c','.cpp','.h','.rs','.go','.sh','.sql']);
    const limit=images[extension]?4*1024*1024:256*1024;
    if(!images[extension]&&!text.has(extension))return {path:target,name,kind:'unsupported',message:'A preview is not available for this file type.'};
    if(stat.size>limit)return {path:target,name,kind:'unsupported',message:'This file is too large for an inline preview.'};
    const handle=await fs.open(target,'r');let data;
    try{const buffer=Buffer.alloc(limit+1);const {bytesRead}=await handle.read(buffer,0,buffer.length,0);if(bytesRead>limit)throw new Error('The file grew beyond the preview limit.');data=buffer.subarray(0,bytesRead);}finally{await handle.close();}
    return images[extension]?{path:target,name,kind:'image',data_url:'data:'+images[extension]+';base64,'+data.toString('base64')}:{path:target,name,kind:'text',text:data.toString('utf8')};
  };
}
module.exports={createLocalFiles};
