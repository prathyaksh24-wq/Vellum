/* Views project existing attachment, conversation and terminal owners. */
(function(){
  const {useEffect,useRef,useState}=React;
  const Icon=props=>React.createElement(window.VellumUI.WorkspaceIcon||window.VellumUI.AppIcon,props);
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
  function WorkspaceFiles({chat,library,selectedFile,records}){
    const files=records||collectWorkspaceFiles(chat,library),[selected,setSelected]=useState(''),[source,setSource]=useState(false);
    const file=files.find(file=>file.id===selected)||selectedFile||files[0];
    useEffect(()=>{if(selectedFile)setSelected(selectedFile.id||'');},[selectedFile]);
    useEffect(()=>setSource(false),[file?.id]);
    const url=safeURL(file?.data_url||file?.url),mime=file?.mime_type||'',rawText=file?.text_content||file?.content||'';
    const text=typeof rawText==='string'?rawText:JSON.stringify(rawText,null,2);
    const image=mime.startsWith('image/')||file?.kind==='image'||/^data:image\//.test(url);
    const html=file?.language==='html'||mime==='text/html'||/\.html?$/i.test(file?.name||'');
    const pdf=mime==='application/pdf'||/\.pdf$/i.test(file?.name||'');
    const downloadText=()=>{const href=URL.createObjectURL(new Blob([text],{type:mime||'text/plain'})),link=document.createElement('a');link.href=href;link.download=file.name;link.click();setTimeout(()=>URL.revokeObjectURL(href),0);};
    return <section className="workspace-files" aria-label="Files and previews">
      <nav className="workspace-file-list" aria-label="Available files">{files.length?files.map(item=><button type="button" key={item.id} aria-current={file?.id===item.id?'true':undefined} onClick={()=>setSelected(item.id)}><Icon name={item.kind==='image'?'FileImage':'FileDocument'} size={16}/><span>{item.name}</span></button>):<div className="workspace-empty"><Icon name="FileDocument" size={24}/><h3>No files yet</h3><p>Attachments and generated code from {chat?'this chat':'your library'} appear here.</p></div>}</nav>
      {file&&<div className="workspace-file-preview"><header><span>{file.name}</span>{html&&text&&<button type="button" onClick={()=>setSource(!source)}>{source?'Preview':'Source'}</button>}{url?<a href={url} download={file.name}>Download</a>:text&&<button type="button" onClick={downloadText}>Download</button>}</header>
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
  function WorkspaceDirectory({onEnvironment}){
    const [path,setPath]=useState(''),[page,setPage]=useState(null),[file,setFile]=useState(null),[pending,setPending]=useState(true),[error,setError]=useState(''),[retry,setRetry]=useState(0),revision=useRef(0);
    useEffect(()=>{
      const token=++revision.current;setPending(true);setError('');setFile(null);
      window.VellumDesktop.files.read({operation:'list',relativePath:path}).then(next=>{if(token===revision.current){setPage(next);onEnvironment?.({workspace_root:next.workspace_root});}},failure=>{if(token===revision.current)setError(failure.message||'The folder could not be read.');}).finally(()=>{if(token===revision.current)setPending(false);});
      return()=>{revision.current++;};
    },[path,retry]);
    const read=async entry=>{if(entry.directory){setPath(entry.path);return;}const token=++revision.current;setPending(true);setError('');try{const next=await window.VellumDesktop.files.read({operation:'read',relativePath:entry.path});if(token===revision.current)setFile(next);}catch(failure){if(token===revision.current)setError(failure.message);}finally{if(token===revision.current)setPending(false);}};
    const parent=()=>setPath(path.split(/[\\/]/).slice(0,-1).join('/'));
    return <section className="workspace-directory" aria-label="Workspace files"><header><button type="button" className="tbtn" aria-label="Parent folder" disabled={!path} onClick={parent}><Icon name="ArrowLeft"/></button><span title={page?.workspace_root}>{path||page?.workspace_root||'Workspace'}</span><button type="button" className="tbtn" aria-label="Refresh folder" onClick={()=>setRetry(value=>value+1)}><Icon name="ArrowRotateCw"/></button></header>
      {error&&<div className="workspace-file-error" role="alert">{error}<button type="button" onClick={()=>setRetry(value=>value+1)}>Retry folder</button></div>}
      <div className="workspace-directory-columns"><nav aria-label="Workspace folder contents" aria-busy={pending}>{page?.entries.map(entry=><button type="button" key={entry.path} onClick={()=>read(entry)}><Icon name={entry.directory?'FolderOpen':'FileDocument'} size={17}/><span>{entry.name}</span></button>)}{pending&&<p role="status">Loading…</p>}{!pending&&!page?.entries.length&&<p>This folder is empty.</p>}{page?.truncated&&<p>Showing the first 500 entries.</p>}</nav>{file?<WorkspaceFiles records={[file]} selectedFile={file}/>:<div className="workspace-empty"><p>Select a file to preview it.</p></div>}</div>
    </section>;
  }
  function WorkspaceLauncher({item,browserAvailable,terminalAvailable,directoryAvailable,suggestions,onOpenTool,onOpenResource}){
    const [address,setAddress]=useState('');
    const open=(kind,reference)=>onOpenTool(kind,reference,item.id);
    const tools=window.VellumUI.workspaceTools({browserAvailable,terminalAvailable,directoryAvailable,open});
    const toolButton=tool=><button type="button" key={tool.id} onClick={tool.open}><Icon name={tool.kind==='chat'?'SideChat':tool.kind==='directory'?'Files':tool.icon} size={18}/><span>{tool.title}</span></button>;
    return <section className="workspace-new-tab-page" aria-label="New tab">
      {browserAvailable&&<form className="workspace-new-address" onSubmit={event=>{event.preventDefault();if(address.trim())open('browser',address.trim());}}><Icon name="Search" size={18}/><input aria-label="Search or enter a URL" placeholder="Search or enter a URL" value={address} onChange={event=>setAddress(event.target.value)}/><button type="submit" className="tbtn" aria-label="Open address" disabled={!address.trim()}><Icon name="ArrowRight" size={18}/></button></form>}
      <div className="workspace-tool-section"><h2>Tools</h2><div className="workspace-tool-grid">{tools.map(toolButton)}</div></div>
      {!!suggestions?.length&&<div className="workspace-tool-section"><h2>Suggested</h2><div className="workspace-suggestions">{suggestions.map(row=><button type="button" key={row.id} disabled={row.kind==='url'&&!browserAvailable} onClick={()=>onOpenResource(row,item.id)}><Icon name={row.icon} size={23}/><span>{row.label}</span>{row.meta&&<small>{row.meta}</small>}</button>)}</div></div>}
    </section>;
  }
  function WorkspaceContent({items,activeId,visible,chats,library,renderChat,renderIntegration,browserAvailable,terminalAvailable,directoryAvailable,plugins=[],catalogState,suggestions,onOpenTool,onOpenResource,onEnvironment,fileFocus}){
    return <>{items.map(item=>{
      const active=item.id===activeId,chat=chats.find(chat=>chat.id===item.reference_id);
      return <div className="workspace-content-view" key={item.id} hidden={!active} inert={!active?'':undefined}>
        {item.kind==='launcher'?<WorkspaceLauncher item={item} browserAvailable={browserAvailable} terminalAvailable={terminalAvailable} directoryAvailable={directoryAvailable} suggestions={suggestions} onOpenTool={onOpenTool} onOpenResource={onOpenResource}/>:item.kind==='directory'?(directoryAvailable?<WorkspaceDirectory onEnvironment={onEnvironment}/>:<div className="workspace-empty"><p>Workspace files are available in the desktop app.</p></div>):item.kind==='integration'?(plugins.some(plugin=>plugin.id===item.reference_id&&plugin.enabled&&plugin.installed)?renderIntegration(item):<div className="workspace-empty" role="status"><p>{catalogState?.loading?'Loading connected tools…':catalogState?.error||'This integration is no longer available.'}</p></div>):item.kind==='terminal'?<WorkspaceTerminal visible={visible&&active}/>:item.kind==='files'?<WorkspaceFiles chat={chat} library={item.reference_id==='library'?library:[]} selectedFile={fileFocus?.chatId===item.reference_id?fileFocus.file:null}/>:<section className="workspace-side-chat" aria-label="Side chat">
          {chat&&(chat.temporary_side_chat||chat.parent_conversation_id)
            ?renderChat(chat)
            :<div className="workspace-empty"><p>Open a new side chat from the tab bar.</p></div>}
        </section>}
      </div>;
    })}</>;
  }
  window.VellumUI=Object.assign(window.VellumUI||{}, {WorkspaceContent,collectWorkspaceFiles});
})();
