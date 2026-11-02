const net=require('node:net');
const path=require('node:path');
const fs=require('node:fs');
const {createHash}=require('node:crypto');

async function claimDesktopWorkspace(root,onFocus,{platform=process.platform}={}) {
  let identity=fs.realpathSync(root);
  if(platform==='win32')identity=identity.toLowerCase();
  const digest=createHash('sha256').update(identity).digest('hex').slice(0,32);
  // Windows named pipes disappear when the owner exits, including a crash.
  const endpoint=platform==='win32'?'\\\\.\\pipe\\vellum-desktop-'+digest:path.join(root,'.desktop-runtime','host.sock');
  fs.mkdirSync(path.join(root,'.desktop-runtime'),{recursive:true});
  const server=net.createServer(socket=>{socket.once('data',data=>{if(data.toString()==='focus')onFocus();socket.end();});socket.setTimeout(1000,()=>socket.destroy());});
  try {
    await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(endpoint,resolve);});
    return server;
  } catch(error) {
    if(error.code!=='EADDRINUSE')throw error;
    await new Promise((resolve,reject)=>{
      const socket=net.connect(endpoint,()=>socket.end('focus'));
      socket.once('close',resolve);socket.once('error',reject);socket.setTimeout(1500,()=>socket.destroy());
    });
    return null;
  }
}

module.exports={claimDesktopWorkspace};
