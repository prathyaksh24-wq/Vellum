/* Presentation over Workspace Layout and the existing browser session owner.
   Tabs and saved layout never live in this hook. Only pending UI/focus work does. */
(function () {
  const {useEffect,useLayoutEffect,useRef,useState}=React;
  const Icon=props=><window.VellumUI.AppIcon {...props}/>;
  function useWorkspaceController({routeKey,visible,mode,state,available,openBrowser,hideBrowser,setMode,browserRef,selectTab}) {
    const [pending,setPending]=useState(false),[error,setError]=useState('');
    const trigger=useRef(null),lock=useRef(false),epoch=useRef(0),focusRequest=useRef(null);
    const current=useRef(null);
    current.current={routeKey,visible,mode,state,openBrowser,hideBrowser,setMode,browserRef,selectTab};
    useEffect(()=>{epoch.current++;focusRequest.current=null;setError('');},[routeKey]);
    useLayoutEffect(()=>{
      const request=focusRequest.current;
      if(!request || !visible || request.mode!==mode || request.tabId!==state.active_tab_id)return;
      const frame=requestAnimationFrame(()=>{
        const latest=current.current,focused=document.activeElement;
        focusRequest.current=null;
        if(request.routeKey!==latest.routeKey || !latest.visible || request.mode!==latest.mode || request.tabId!==latest.state.active_tab_id || !document.hasFocus())return;
        // A click in content or another input wins over delayed chrome focus.
        if(focused!==document.body && focused!==request.from && !focused?.closest?.('.workspace-header'))return;
        latest.browserRef.current?.focusAddress();
      });
      return()=>cancelAnimationFrame(frame);
    },[visible,mode,state.active_tab_id,pending]);
    const run=async operation=>{
      if(lock.current)return;
      lock.current=true;setPending(true);setError('');
      const token=++epoch.current,key=current.current.routeKey,from=document.activeElement;
      try{
        const result=await operation();
        if(token!==epoch.current || key!==current.current.routeKey)return;
        if(result?.focus)focusRequest.current={routeKey:key,mode:result.mode,tabId:result.tabId,from};
      }catch(failure){if(token===epoch.current)setError(failure.message || 'Unable to open workspace tabs.');}
      finally{lock.current=false;setPending(false);}
    };
    const show=(nextMode=mode,create=false)=>run(async()=>{
      const result=await current.current.openBrowser({mode:nextMode,newTab:create,throwOnError:true});
      if(!result)return;
      if(!result.running)throw new Error('The embedded browser is unavailable. Check Browser settings.');
      return {focus:true,mode:nextMode,tabId:result.active_tab_id};
    });
    const layout=nextMode=>run(async()=>{
      const receipt=await current.current.setMode(nextMode);
      if(!receipt || receipt.status!=='applied')throw new Error(receipt?.message || 'Workspace layout could not be changed.');
      return {focus:true,mode:nextMode,tabId:current.current.state.active_tab_id};
    });
    const select=tabId=>run(async()=>{
      if(!current.current.state.tabs.some(tab=>tab.id===tabId))return;
      const result=await current.current.openBrowser({mode:current.current.mode,throwOnError:true});
      if(!result)return;
      if(!result.running)throw new Error('The browser session is no longer running.');
      const applied=await current.current.selectTab(tabId);
      if(!applied)throw new Error('The tab could not be selected.');
      return {focus:true,mode:current.current.mode,tabId};
    });
    const hide=async()=>{
      const token=++epoch.current,key=current.current.routeKey;
      focusRequest.current=null;setError('');
      await current.current.hideBrowser();
      requestAnimationFrame(()=>{
        const focused=document.activeElement;
        if(token===epoch.current && key===current.current.routeKey && !current.current.visible && document.hasFocus() &&
          (focused===document.body || focused?.closest?.('.workspace-header,.browser-panel[hidden]')))trigger.current?.focus({preventScroll:true});
      });
    };
    return {available,visible,mode,tabs:state.tabs||[],trigger,pending,error,show,layout,select,hide};
  }
  function SummaryIcon({size=18}) {
    return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true"><circle cx="5" cy="5" r="2"/><circle cx="5" cy="12" r="2"/><circle cx="5" cy="19" r="2"/><path d="M11 5h10M11 12h10M11 19h10"/></svg>;
  }
  function WorkspaceToolbar({controller:c,workspace:w,sidebar,title,conversation,project,sidebarVisible=true,onNewChat,onOpenProject,onDetails,detailsOpen,onOptions}) {
    const full=w.mode==='full'&&w.tabs.length>0;
    const tabIcon=tab=>tab.kind==='chat'?'Chat':tab.kind==='files'?'FileDocument':tab.kind==='terminal'?'Terminal':'Globe';
    const newTab=<button ref={c.trigger} type="button" className="tbtn workspace-new-tab" aria-label="New workspace tab" data-tip="New tab" onClick={()=>w.open('launcher',w.mode==='full'?'full':'split')}><Icon name={full?'Plus':'PlusSquareAdd'} size={19}/></button>;
    const actions=<div className="workspace-header-actions">
      {full&&<><button type="button" className="tbtn" aria-label="Restore split view" data-tip="Restore split view" onClick={()=>w.layout('split')}><Icon name="Restore" size={17}/></button><button type="button" className="tbtn" aria-label="Hide workspace views" onClick={w.hide}><Icon name="X" size={17}/></button></>}
      {conversation&&<><button type="button" className="tbtn" aria-label="Chat options" data-tip="Chat options" onClick={onOptions}><Icon name="DotsHorizontal" size={18}/></button><button type="button" className="tbtn workspace-summary-toggle" data-tip="Summary" aria-label={detailsOpen?'Hide summary':'Show summary'} aria-expanded={detailsOpen} onClick={onDetails}><SummaryIcon/></button></>}
      {!full&&!w.visible&&<>{conversation&&<span className="workspace-control-divider"/>}{newTab}</>}
    </div>;
    return <header className={'workspace-header'+(full?' workspace-unified-tabs':'')} aria-label="Workspace controls">
      {full?<div className="workspace-view-tabs" role="tablist" aria-label="Workspace views" onKeyDown={event=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
        const tabs=[...event.currentTarget.querySelectorAll('[role=tab]')],index=tabs.indexOf(document.activeElement);
        if(index<0)return;event.preventDefault();tabs[event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length].focus();
      }}><button type="button" role="tab" aria-selected={!w.visible} className={'workspace-chat-tab'+(!w.visible?' active':'')} onClick={w.showMain}><Icon name="Chat" size={15}/><span>{title||'Current chat'}</span></button>{w.tabs.map(tab=><div className={'workspace-view-tab'+(w.visible&&w.activeId===tab.id?' active':'')} key={tab.id}><button type="button" role="tab" aria-selected={w.visible&&w.activeId===tab.id} onClick={()=>w.select(tab)}><Icon name={tabIcon(tab)} size={15}/><span>{tab.title}</span></button><button type="button" aria-label={'Close '+tab.title} onClick={()=>w.close(tab)}><Icon name="X" size={13}/></button></div>)}{newTab}</div>:<div className="workspace-header-start">{sidebar}{conversation&&!sidebarVisible&&<button type="button" className="tbtn" aria-label="New chat" data-command="chat.new" onClick={onNewChat}><Icon name="PencilSquare" size={18}/></button>}{conversation&&project&&!sidebarVisible&&<button type="button" className="tbtn workspace-project-context" aria-label={'Project: '+project.name} onClick={()=>onOpenProject(project.id)}><Icon name="Folder" size={17}/></button>}<span className="workspace-title">{title}</span></div>}
      {actions}{(c.error||w.error)&&<div className="workspace-control-error" role="alert">{w.error||c.error}</div>}
    </header>;
  }
  function WorkspacePaneTabs({workspace:w,controller:c}){
    const tabIcon=tab=>tab.kind==='chat'?'Chat':tab.kind==='files'?'FileDocument':tab.kind==='terminal'?'Terminal':'Globe';
    return <header className="workspace-pane-tabs"><div className="workspace-view-tabs" role="tablist" aria-label="Open workspace views">{w.tabs.map(tab=><div className={'workspace-view-tab'+(w.activeId===tab.id?' active':'')} key={tab.id}><button type="button" role="tab" aria-selected={w.activeId===tab.id} onClick={()=>w.select(tab)}><Icon name={tabIcon(tab)} size={15}/><span>{tab.title}</span></button><button type="button" aria-label={'Close '+tab.title} onClick={()=>w.close(tab)}><Icon name="X" size={13}/></button></div>)}</div><button type="button" ref={c.trigger} className="tbtn" aria-label="New workspace tab" onClick={()=>w.open('launcher','split')}><Icon name="Plus" size={18}/></button><button type="button" className="tbtn" aria-label="Enter full view" onClick={()=>w.layout('full')}><Icon name="Expand" size={16}/></button><button type="button" className="tbtn" aria-label="Hide workspace views" onClick={w.hide}><Icon name="X" size={16}/></button></header>;
  }
  function WorkspaceDetails({chat,activity,pinned,onPin,onClose,onViewImage}) {
    const files=(chat?.messages||[]).flatMap(message=>message.attachments||[]);
    return <aside className="workspace-details" data-pinned={pinned} data-ui-reference="chat-details" aria-label={activity?'Agent activity':'Conversation summary'}>
      <div className="workspace-details-heading"><h2>{activity?'Agent activity':'Summary'}</h2><button type="button" className="tbtn" aria-label={pinned?'Unpin chat details':'Pin chat details'} aria-pressed={pinned} onClick={onPin}><Icon name="Pin" size={17}/></button><button type="button" className="tbtn" aria-label="Close chat details" onClick={onClose}><Icon name="X" size={17}/></button></div>
      <div className="workspace-details-body">{activity?<window.VellumUI.ActivityInspector msg={activity}/>:<>
        <h3>{chat?.title || 'New chat'}</h3><p className="workspace-detail-meta">{(chat?.messages||[]).filter(message=>message.role==='user').length} messages from you</p>
        {typeof chat?.summary==='string' && chat.summary.trim() ? <section><h4>Conversation summary</h4><p>{chat.summary}</p></section> : <section><h4>Conversation outline</h4><ol className="workspace-summary-outline">{(chat?.messages||[]).filter(message=>message.role==='user').map(message=><li key={message.id}><button type="button" onClick={()=>document.getElementById('m-'+message.id)?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth',block:'start'})}>{String(message.text||'Attachment').slice(0,160)}</button></li>)}</ol></section>}
        <section><h4>Files in chat <small>{files.length}</small></h4>{!files.length && <p className="workspace-detail-meta">No files attached.</p>}{files.map((file,index)=><button type="button" className="workspace-detail-file" key={index} disabled={!file.url} onClick={()=>onViewImage?.(file.url)}><Icon name={file.kind==='image'?'FileImage':'FileDocument'}/><span>{file.name || 'Attachment'}</span></button>)}</section>
      </>}</div>
    </aside>;
  }
  window.VellumUI=Object.assign(window.VellumUI||{}, {useWorkspaceController,WorkspaceToolbar,WorkspacePaneTabs,WorkspaceDetails});
})();
