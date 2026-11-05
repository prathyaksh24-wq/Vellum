/* Views project existing attachment, conversation and terminal owners. */
(function(){
  const {useEffect,useRef,useState}=React;
  const Icon=props=><window.VellumUI.AppIcon {...props}/>;
  const safeURL=value=>{
    if(!value)return '';
    try{const url=new URL(value,location.href);return ['http:','https:','blob:'].includes(url.protocol)||/^data:(?:image\/|application\/pdf[;,])/.test(value)?url.href:'';}catch{return '';}
  };
  function collectWorkspaceFiles(chat,library=[]){
    const rows=[],seen=new Set();
    const add=(file,key)=>{if(!file)return;const identity=file.digest||file.id||key;if(seen.has(identity))return;seen.add(identity);rows.push({...file,id:identity,name:file.name||'Untitled file'});};
    for(const message of chat?.messages||[]){
      (message.attachments||[]).forEach((file,index)=>add(file,message.id+':attachment:'+index));
      (message.artifacts||[]).forEach((file,index)=>add({...file,text_content:file.text_content||file.content},message.id+':artifact:'+index));
      if(message.role==='assistant'){
        let index=0;for(const match of String(message.text||'').matchAll(/```([\w.+-]*)[^\n]*\n([\s\S]*?)```/g)){
          const language=match[1]||'text',number=++index;
          add({name:'Response '+language+' '+number,kind:'code',language,text_content:match[2],generated:true},message.id+':code:'+number);
        }
      }
    }
    if(!chat)for(const item of library)if(item.attachment||item.content||item.text_content)add(item.attachment||{...item,text_content:item.text_content||item.content},'library:'+item.id);
    return rows;
  }
  function DeviceFiles({visible}){
    const [folder,setFolder]=useState(null),[address,setAddress]=useState(''),[file,setFile]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
    const sequence=useRef(0),started=useRef(false);
    const read=async(operation,path)=>{
      const token=++sequence.current;setBusy(true);setError('');
      try{const result=await window.VellumDesktop.invoke('local_files',{operation,...(path?{path}:{})});if(token!==sequence.current)return;if(operation==='list'){setFolder(result);setAddress(result.path);setFile(null);}else setFile(result);}
      catch(failure){if(token===sequence.current)setError(failure.message==='Unknown desktop command.'?'Restart Vellum to enable local file browsing.':failure.message||'This location could not be opened.');}
      finally{if(token===sequence.current)setBusy(false);}
    };
    useEffect(()=>{if(visible&&!started.current){started.current=true;read('list');}},[visible]);
    useEffect(()=>()=>{sequence.current++;},[]);
    return <section className="workspace-device-files" aria-label="Files on this device">
      <form className="workspace-file-location" onSubmit={event=>{event.preventDefault();if(address.trim())read('list',address.trim());}}><button type="button" className="tbtn" aria-label="Parent folder" disabled={!folder?.parent||busy} onClick={()=>read('list',folder.parent)}><Icon name="ArrowUp" size={17}/></button><input aria-label="Folder path" placeholder="Local folder path" value={address} onChange={event=>setAddress(event.target.value)}/><button type="submit" className="tbtn" aria-label="Open folder" disabled={busy||!address.trim()}><Icon name="ArrowRight" size={17}/></button></form>
      {error&&<p className="workspace-file-error" role="alert">{error}</p>}
      <div className="workspace-device-body"><nav className="workspace-file-list" aria-label="Local folders and files">{busy&&<p role="status">Opening…</p>}{folder?.entries.map(entry=><button type="button" key={entry.path} title={entry.name} aria-current={file?.path===entry.path?'true':undefined} onClick={()=>read(entry.kind==='directory'?'list':'preview',entry.path)}><Icon name={entry.kind==='directory'?'Folder':'FileDocument'} size={16}/><span>{entry.name}</span></button>)}{folder&&!folder.entries.length&&<p>This folder is empty.</p>}{folder?.truncated&&<p>Showing the first 2,000 entries.</p>}</nav><div className="workspace-file-preview">{file?<><header><span>{file.name}</span></header>{file.kind==='image'?<img className="workspace-preview-image" src={file.data_url} alt={file.name}/>:file.kind==='text'?<pre tabIndex="0">{file.text}</pre>:<div className="workspace-empty"><p>{file.message}</p></div>}</>:<div className="workspace-empty"><Icon name="Folder" size={24}/><h3>On this device</h3><p>Choose a folder or file. Files stay on your laptop unless you attach them to a message.</p></div>}</div></div>
    </section>;
  }
  function WorkspaceFiles({chat,library,visible}){
    const desktop=window.VellumDesktop?.runtime==='electron', [device,setDevice]=useState(desktop);
    return <section className="workspace-file-workspace"><header className="workspace-file-sources">{desktop&&<button type="button" aria-pressed={device} onClick={()=>setDevice(true)}>On this device</button>}<button type="button" aria-pressed={!device} onClick={()=>setDevice(false)}>Chat files</button></header>{device?<DeviceFiles visible={visible}/>:<ChatFiles chat={chat} library={library}/>}</section>;
  }
  function ChatFiles({chat,library}){
    const files=collectWorkspaceFiles(chat,library),[selected,setSelected]=useState(''),[source,setSource]=useState(false);
    const file=files.find(file=>file.id===selected)||files[0];
    useEffect(()=>setSource(false),[file?.id]);
    const url=safeURL(file?.data_url||file?.url),mime=file?.mime_type||'',rawText=file?.text_content||file?.content||'';
    const text=typeof rawText==='string'?rawText:JSON.stringify(rawText,null,2);
    const image=mime.startsWith('image/')||file?.kind==='image'||/^data:image\//.test(url);
    const html=file?.language==='html'||mime==='text/html'||/\.html?$/i.test(file?.name||'');
    const pdf=mime==='application/pdf'||/\.pdf$/i.test(file?.name||'');
    return <section className="workspace-files" aria-label="Files and previews">
      <nav className="workspace-file-list" aria-label="Available files">{files.length?files.map(item=><button type="button" key={item.id} aria-current={file?.id===item.id?'true':undefined} onClick={()=>setSelected(item.id)}><Icon name={item.kind==='image'?'FileImage':'FileDocument'} size={16}/><span>{item.name}</span></button>):<div className="workspace-empty"><Icon name="FileDocument" size={24}/><h3>No files yet</h3><p>Attachments and generated code from {chat?'this chat':'your library'} appear here.</p></div>}</nav>
      {file&&<div className="workspace-file-preview"><header><span>{file.name}</span>{html&&text&&<button type="button" onClick={()=>setSource(!source)}>{source?'Preview':'Source'}</button>}{url&&<a href={url} download={file.name}>Download</a>}</header>
        {image&&url?<img className="workspace-preview-image" src={url} alt={file.name}/>:html&&text&&!source?<iframe title={file.name+' preview'} sandbox="" referrerPolicy="no-referrer" srcDoc={text}/>:text?<pre tabIndex="0">{text}</pre>:pdf&&url?<iframe title={file.name+' preview'} sandbox="" referrerPolicy="no-referrer" src={url}/>:<div className="workspace-empty"><p>This file has no readable preview saved with it.</p>{url&&<a href={url} download={file.name}>Download file</a>}</div>}
      </div>}
    </section>;
  }
  function WorkspaceTerminal({visible}){
    const mount=useRef(null),owner=useRef(null),[state,setState]=useState('loading'),[error,setError]=useState('');
    useEffect(()=>{
      let cancelled=false,observer,started=false;
      const start=async()=>{
        if(started||!window.VellumUI.createTerminalWorkspace)return;started=true;
        try{
          const contract=await window.VellumApi.plugins.capabilities(),feature=contract.features?.terminal;
          if(!feature?.enabled)throw new Error('The local terminal is unavailable. Restart the updated backend.');
          const result=await window.VellumApi.client.request(feature.endpoints.profiles);
          const profiles=(result.profiles||[]).filter(profile=>profile.available);
          if(!profiles.length)throw new Error('No supported local shell was found.');
          if(cancelled)return;
          const style=getComputedStyle(mount.current),base=window.VellumApi.client.backendBase();
          const current=window.VellumUI.createTerminalWorkspace(mount.current,{apiBase:base,profiles,rawInput:true,
            theme:{background:style.getPropertyValue('--bg').trim()||'#10151d',foreground:style.getPropertyValue('--txt').trim()||'#e6edf4'}});
          owner.current=current;await current.mount();
          if(cancelled){current.dispose();return;}
          setState('ready');observer=new ResizeObserver(()=>current.resize());observer.observe(mount.current);
        }catch(failure){if(!cancelled){setError(failure.message);setState('error');}}
      };
      start();window.addEventListener('vellum:workspace-transport-ready',start);
      return()=>{cancelled=true;observer?.disconnect();window.removeEventListener('vellum:workspace-transport-ready',start);owner.current?.dispose();owner.current=null;};
    },[]);
    useEffect(()=>{if(visible&&state==='ready')requestAnimationFrame(()=>owner.current?.resize());},[visible,state]);
    return <section className="workspace-terminal" aria-label="Local terminal"><div className="workspace-terminal-mount" ref={mount}/>{state!=='ready'&&<div className="workspace-empty" role="status">{error||'Opening local shell…'}</div>}</section>;
  }
  function WorkspaceLauncher({item,browserAvailable,terminalAvailable,onOpenTool}){
    const [address,setAddress]=useState('');
    const open=(kind,reference)=>onOpenTool(kind,reference,item.id);
    return <section className="workspace-new-tab-page" aria-label="New tab">
      {browserAvailable&&<form className="workspace-new-address" onSubmit={event=>{event.preventDefault();if(address.trim())open('browser',address.trim());}}><Icon name="Search" size={18}/><input aria-label="Search or enter a URL" placeholder="Search or enter a URL" value={address} onChange={event=>setAddress(event.target.value)}/><button type="submit" className="tbtn" aria-label="Open address" disabled={!address.trim()}><Icon name="ArrowRight" size={18}/></button></form>}
      <div className="workspace-tool-section"><h2>Tools</h2><div className="workspace-tool-grid">
        <button type="button" onClick={()=>open('files')}><Icon name="Folder" size={18}/><span>Files and previews</span></button>
        {terminalAvailable&&<button type="button" onClick={()=>open('terminal')}><Icon name="Terminal" size={18}/><span>Terminal</span></button>}
        <button type="button" onClick={()=>open('chat')}><Icon name="Chat" size={18}/><span>Side chat</span></button>
        {browserAvailable&&<button type="button" onClick={()=>open('browser')}><Icon name="Globe" size={18}/><span>Browser</span></button>}
      </div></div>
    </section>;
  }
  function WorkspaceContent({items,activeId,visible,chats,mainChatId,library,renderChat,onSelectChat,onOpenMain,onOpenFiles,browserAvailable,terminalAvailable,onOpenTool}){
    return <>{items.map(item=>{
      const active=item.id===activeId,chat=chats.find(chat=>chat.id===item.reference_id);
      return <div className="workspace-content-view" key={item.id} hidden={!active} inert={!active?'':undefined}>
        {item.kind==='launcher'?<WorkspaceLauncher item={item} browserAvailable={browserAvailable} terminalAvailable={terminalAvailable} onOpenTool={onOpenTool}/>:item.kind==='terminal'?<WorkspaceTerminal visible={visible&&active}/>:item.kind==='files'?<WorkspaceFiles visible={visible&&active} chat={chat} library={item.reference_id==='library'?library:[]}/>:<section className="workspace-side-chat" aria-label="Side chat">
          <header className="workspace-side-chat-heading"><label><span className="sr-only">Side conversation</span><select aria-label="Side conversation" value={item.reference_id} onChange={event=>onSelectChat(item,event.target.value)}>{chats.filter(chat=>!chat.archived&&chat.id!==mainChatId).map(chat=><option key={chat.id} value={chat.id}>{chat.title||'New chat'}</option>)}</select></label><button type="button" className="tbtn" aria-label="Open conversation in main view" onClick={()=>onOpenMain(item.reference_id)}><Icon name="ExternalLink" size={16}/></button><button type="button" className="tbtn" aria-label="Files in side chat" onClick={()=>onOpenFiles(item.reference_id)}><Icon name="FileDocument" size={16}/></button></header>
          {chat&&chat.id!==mainChatId?renderChat(chat):<div className="workspace-empty"><p>{chat?'This conversation is already in the main view. Choose another chat.':'This conversation is no longer available.'}</p></div>}
        </section>}
      </div>;
    })}</>;
  }
  window.VellumUI=Object.assign(window.VellumUI||{}, {WorkspaceContent,collectWorkspaceFiles});
})();
