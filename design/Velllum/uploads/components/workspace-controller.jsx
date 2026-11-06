/* Presentation over Workspace Layout and the existing browser session owner.
   Tabs and saved layout never live in this hook. Only pending UI/focus work does. */
(function () {
  const {useEffect,useLayoutEffect,useRef,useState}=React;
  const Icon=props=>React.createElement(window.VellumUI.WorkspaceIcon||window.VellumUI.AppIcon,props);
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
  function WorkspaceToolbar({controller:c,workspace:w,sidebar,title,conversation,project,sidebarVisible=true,onNewChat,onOpenProject,onDetails,detailsOpen,onOptions}) {
    const full=w.mode==='full'&&w.tabs.length>0;
    const tabIcon=tab=>tab.kind==='chat'?'Chat':['files','directory'].includes(tab.kind)?'Files':tab.kind==='terminal'?'Terminal':tab.kind==='integration'?'ConnectApps':tab.kind==='launcher'?'Tabs':'Globe';
    const count=w.tabs.length,showRetained=!w.visible&&count>0;
    const fullSideChat=full&&w.visible&&w.tabs.some(tab=>tab.id===w.activeId&&tab.kind==='chat');
    const newTab=<button ref={c.trigger} type="button" className="tbtn workspace-new-tab" aria-label={showRetained?'Show tabs':'New workspace tab'} data-tip={showRetained?'Show tabs':'New tab'} onClick={()=>showRetained?w.reveal():w.open('launcher',w.mode==='full'?'full':'split')}>
      <Icon name={full&&!showRetained?'Plus':count?'Tabs':'PlusSquareAdd'} size={18}/>{showRetained&&<span className="workspace-tab-count" aria-hidden="true">{count>9?'9+':count}</span>}
    </button>;
    const actions=<div className="workspace-header-actions">
      {full&&!fullSideChat&&<><button type="button" className="tbtn" aria-label="Restore split view" data-tip="Restore split view" onClick={()=>w.layout('split')}><Icon name="Restore" size={17}/></button><button type="button" className="tbtn" aria-label="Hide workspace views" onClick={w.hide}><Icon name="X" size={17}/></button></>}
      {conversation&&!fullSideChat&&<><button type="button" className="tbtn" aria-label="Chat options" data-tip="Chat options" onClick={onOptions}><Icon name="DotsHorizontal" size={18}/></button><button type="button" className="tbtn workspace-summary-toggle" data-tip="Toggle summary" data-command="workspace.summary" aria-label="Toggle summary" aria-pressed={detailsOpen} aria-expanded={detailsOpen} aria-controls="workspace-summary" aria-keyshortcuts="Control+Shift+S Meta+Shift+S" onClick={onDetails}><Icon name="Summary" size={18}/></button></>}
      {!full&&!w.visible&&<>{conversation&&<span className="workspace-control-divider"/>}{newTab}</>}
    </div>;
    return <header className={'workspace-header'+(full?' workspace-unified-tabs':'')} aria-label="Workspace controls">
      {full?<div className="workspace-view-tabs" role="tablist" aria-label="Workspace views" onKeyDown={event=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
        const tabs=[...event.currentTarget.querySelectorAll('[role=tab]')],index=tabs.indexOf(document.activeElement);
        if(index<0)return;event.preventDefault();tabs[event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length].focus();
      }}><button type="button" role="tab" aria-selected={!w.visible} className={'workspace-chat-tab'+(!w.visible?' active':'')} onClick={w.showMain}><Icon name="Chat" size={15}/><span>{title||'Current chat'}</span></button>{w.tabs.map(tab=><div className={'workspace-view-tab'+(w.visible&&w.activeId===tab.id?' active':'')} key={tab.id}><button type="button" role="tab" aria-selected={w.visible&&w.activeId===tab.id} onClick={()=>w.select(tab)}><Icon name={tabIcon(tab)} size={15}/><span>{tab.title}</span></button><button type="button" aria-label={'Close '+tab.title} onClick={()=>w.close(tab)}><Icon name="X" size={13}/></button></div>)}{newTab}</div>:<div className="workspace-header-start">{sidebar}{conversation&&!sidebarVisible&&<button type="button" className="tbtn" aria-label="New chat" data-command="chat.new" onClick={onNewChat}><Icon name="PencilSquare" size={18}/></button>}{conversation&&project&&!sidebarVisible&&<button type="button" className="tbtn workspace-project-context" aria-label={'Project: '+project.name} onClick={()=>onOpenProject(project.id)}><Icon name="Folder" size={17}/></button>}<span className="workspace-title">{title}</span></div>}
      {full&&<button type="button" className="tbtn" aria-label={w.visible?'Enter split view':'Enter full view'} data-tip={w.visible?'Enter split view':'Enter full view'} onClick={()=>w.layout(w.visible?'split':'full')}><Icon name={w.visible?'Split':'Full'} size={18}/></button>}
      {actions}{(c.error||w.error)&&<div className="workspace-control-error" role="alert">{w.error||c.error}</div>}
    </header>;
  }
  function WorkspacePaneTabs({workspace:w,controller:c}){
    const tabIcon=tab=>tab.kind==='chat'?'Chat':['files','directory'].includes(tab.kind)?'Files':tab.kind==='terminal'?'Terminal':tab.kind==='integration'?'ConnectApps':tab.kind==='launcher'?'Tabs':'Globe';
    const sideChatActive=w.tabs.some(tab=>tab.id===w.activeId&&tab.kind==='chat');
    return <header className="workspace-pane-tabs">
      <div className="workspace-view-tabs" role="tablist" aria-label="Open workspace views">
        {w.tabs.map(tab=><div className={'workspace-view-tab'+(w.activeId===tab.id?' active':'')} key={tab.id}>
          <button type="button" role="tab" aria-selected={w.activeId===tab.id} onClick={()=>w.select(tab)}><Icon name={tabIcon(tab)} size={15}/><span>{tab.title}</span></button>
          <button type="button" aria-label={'Close '+tab.title} onClick={()=>w.close(tab)}><Icon name="X" size={13}/></button>
        </div>)}
        <button type="button" ref={c.trigger} className="tbtn" aria-label="New workspace tab" onClick={()=>w.open('launcher','split')}><Icon name="Plus" size={18}/></button>
      </div>
      {!sideChatActive&&<div className="workspace-pane-actions">
        <button type="button" className="tbtn" aria-label="Enter full view" onClick={()=>w.layout('full')}><Icon name="Full" size={16}/></button>
        <button type="button" className="tbtn" aria-label="Hide workspace views" onClick={w.hide}><Icon name="X" size={16}/></button>
      </div>}
    </header>;
  }
  function SummarySection({id,title,rows,chatId,onOpen}){
    const storage='vellum-summary:'+chatId+':'+id;
    const [expanded,setExpanded]=useState(()=>{try{return sessionStorage.getItem(storage)!=='closed';}catch{return true;}}),[all,setAll]=useState(false);
    if(!rows.length)return null;
    const visible=all?rows:rows.slice(0,6);
    return <section className="workspace-summary-section"><button type="button" className="workspace-summary-section-title" aria-expanded={expanded} onClick={()=>{const next=!expanded;setExpanded(next);try{sessionStorage.setItem(storage,next?'open':'closed');}catch{}}}><Icon name={expanded?'ChevronDown':'ChevronRight'} size={12}/><span>{title}</span><small>{rows.length}</small></button>
      {expanded&&<div className="workspace-summary-section-rows">{visible.map(row=><button type="button" className="workspace-resource-row" key={row.id} onClick={()=>onOpen(row)} title={row.label} data-status={row.status}>
        <span className="workspace-resource-icon"><Icon name={row.icon||'FileDocument'} size={17}/></span><span className="workspace-resource-copy"><span>{row.label}</span>{row.meta&&<small>{String(row.meta).replace(/_/g,' ')}</small>}</span><Icon name={row.kind==='url'?'ExternalLink':'ChevronRight'} size={12}/>
      </button>)}{rows.length>6&&<button type="button" className="workspace-summary-view-all" onClick={()=>setAll(!all)}>{all?'Show less':'View all '+rows.length}</button>}</div>}
    </section>;
  }
  function WorkspaceDetails({chat,activity,pinned,onPin,onClose,resources,onOpen,tabsVisible=false}) {
    const panel=useRef(null),[mode,setMode]=useState('overlay');
    useLayoutEffect(()=>{
      const root=panel.current?.closest('.workspace-content');if(!root)return;
      const measure=()=>{const width=root.clientWidth;setMode(!pinned||tabsVisible||width<1096?'overlay':width<1536?'shift':'gutter');};
      const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(measure);observer?.observe(root);measure();return()=>observer?.disconnect();
    },[pinned,tabsVisible]);
    useEffect(()=>{
      const key=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();onClose();}};
      const outside=event=>{if(!pinned&&!panel.current?.contains(event.target)&&!event.target.closest?.('.workspace-summary-toggle'))onClose();};
      document.addEventListener('keydown',key);document.addEventListener('pointerdown',outside);
      return()=>{document.removeEventListener('keydown',key);document.removeEventListener('pointerdown',outside);};
    },[pinned,onClose]);
    const sections=resources||window.VellumUI.taskResources(chat),titles={progress:'Progress',outputs:'Outputs',inputs:'Inputs',sources:'Sources',chats:'Side chats',agents:'Subagents',browser:'Browser activity',automations:'Scheduled tasks',environment:'Environment'};
    const hasContent=Object.values(sections).some(rows=>rows.length);
    return <aside ref={panel} id="workspace-summary" className="workspace-details workspace-task-summary" data-mode={mode} data-pinned={pinned} data-ui-reference="chat-details" aria-label="Task summary">
      <div className="workspace-details-heading"><h2>Summary</h2><button type="button" className="tbtn" aria-label={pinned?'Unpin summary':'Pin summary'} aria-pressed={pinned} onClick={onPin}><Icon name="Pin" size={16}/></button><button type="button" className="tbtn" aria-label="Close summary" onClick={onClose}><Icon name="X" size={16}/></button></div>
      <div className="workspace-details-body">{activity&&<div className="workspace-summary-activity"><window.VellumUI.ActivityInspector msg={activity}/></div>}
        {Object.entries(titles).map(([id,title])=><SummarySection key={chat?.id+':'+id} id={id} title={title} rows={sections[id]||[]} chatId={chat?.id||'task'} onOpen={onOpen}/>)}
        {!hasContent&&!activity&&<p className="workspace-detail-meta">Resources and task progress will appear here as you work.</p>}
      </div>
    </aside>;
  }
  window.VellumUI=Object.assign(window.VellumUI||{}, {useWorkspaceController,WorkspaceToolbar,WorkspacePaneTabs,WorkspaceDetails});
})();
