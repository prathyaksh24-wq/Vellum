/* Presentation over App's route, conversation, project and collection owners. */
(function () {
  const {useState,useEffect,useLayoutEffect,useRef,useMemo}=React;
  const Icon=props=><window.VellumUI.AppIcon {...props}/>;
  function useShellOverlay(active){useLayoutEffect(()=>{if(!active)return;window.dispatchEvent(new Event('vellum:shell-overlay'));return()=>requestAnimationFrame(()=>window.dispatchEvent(new Event('vellum:shell-overlay')));},[active]);}
  function ModeSwitcher(){
    const [open,setOpen]=useState(false),[position,setPosition]=useState({}),ref=useRef(null),trigger=useRef(null),option=useRef(null),popup=useRef(null);
    useShellOverlay(open);
    useLayoutEffect(()=>{if(!open)return;const rect=trigger.current?.getBoundingClientRect();if(rect)setPosition({left:Math.max(12,Math.min(rect.left,window.innerWidth-276)),top:rect.bottom+6});const close=()=>setOpen(false);window.addEventListener('resize',close);window.addEventListener('scroll',close,true);return()=>{window.removeEventListener('resize',close);window.removeEventListener('scroll',close,true);};},[open]);
    useEffect(()=>{
      if(!open)return;
      option.current?.focus();
      const close=event=>{if(!ref.current?.contains(event.target)&&!popup.current?.contains(event.target)){setOpen(false);}};
      document.addEventListener('pointerdown',close);
      return()=>document.removeEventListener('pointerdown',close);
    },[open]);
    return <div className="shell-mode" ref={ref} onKeyDown={event=>{
      if(event.key==='Escape'){event.preventDefault();setOpen(false);trigger.current?.focus();}
      if(open&&['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();option.current?.focus();}
    }}>
      <button ref={trigger} type="button" className="shell-mode-trigger" aria-label="Vellum mode" aria-haspopup="menu" aria-expanded={open} onClick={()=>setOpen(!open)}><span>Vellum</span><Icon name="ChevronDown" size={14}/></button>
      {open&&ReactDOM.createPortal(<div ref={popup} className="shell-mode-menu" data-shell-overlay="true" style={position} role="menu" aria-label="Vellum modes">
        <button ref={option} type="button" role="menuitemradio" aria-checked="true" onClick={()=>{setOpen(false);trigger.current?.focus();}}><Icon name="Chat"/><span><strong>Vellum</strong><small>Create, learn, and explore</small></span><Icon name="Check" size={15}/></button>
        <button type="button" role="menuitemradio" aria-checked="false" disabled><Icon name="Code"/><span><strong>Coding <em>Coming soon</em></strong><small>Build, debug, and ship</small></span></button>
      </div>,document.body)}
    </div>;
  }
  function NavigationRail({view,profile,onHome,onNav,onProfile,onSettings,onSearch,onNotifications,unread=0,notificationsOpen=false,onToggleSidebar,sidebarVisible,onPreviewSidebar,onLeaveSidebar,onDismissPreview}){
    const [more,setMore]=useState(false),[position,setPosition]=useState({}),ref=useRef(null),trigger=useRef(null),popup=useRef(null);
    useShellOverlay(more);
    useEffect(()=>{
      if(!more)return;
      const close=event=>{if(!ref.current?.contains(event.target)&&!popup.current?.contains(event.target))setMore(false);};
      document.addEventListener('pointerdown',close);return()=>document.removeEventListener('pointerdown',close);
    },[more]);
    const items=[['chat','Home','Home'],['library','Library','BookOpen'],['music','Music','Music'],['apps','Plugins','ConnectApps']];
    return <nav className="app-destination-rail" aria-label="App destinations" onPointerLeave={onLeaveSidebar}>
      <div className="app-rail-destinations">
        <button type="button" className="app-rail-button web-sidebar-toggle" data-command="sidebar.toggle" title={sidebarVisible?'Hide sidebar':'Show sidebar'} aria-label={sidebarVisible?'Hide sidebar':'Show sidebar'} aria-expanded={sidebarVisible} onClick={onToggleSidebar}><Icon name="SidebarLeft"/></button>
        {items.map(([id,label,icon])=><button key={id} type="button" className="app-rail-button" data-rail-preview-trigger={id} title={label} data-command={{chat:'app.home',library:'library.open'}[id]} data-tip={label} aria-label={label} aria-current={view===id||id==='chat'&&['project','projects','agent'].includes(view)?'page':undefined} onPointerEnter={()=>onPreviewSidebar?.(id)} onFocus={()=>onPreviewSidebar?.(id)} onClick={()=>{onDismissPreview?.();id==='chat'?onHome():onNav(id);}}><Icon name={icon} size={20}/></button>)}
        <div className="app-rail-more" ref={ref} onKeyDown={event=>{
          if(event.key==='Escape'){setMore(false);trigger.current?.focus();}
          if(more&&['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const rows=[...(popup.current?.querySelectorAll('[role=menuitem]')||[])],index=rows.indexOf(document.activeElement);rows[event.key==='Home'?0:event.key==='End'?rows.length-1:index<0?(event.key==='ArrowDown'?0:rows.length-1):(index+(event.key==='ArrowDown'?1:rows.length-1))%rows.length]?.focus();}
        }}>
          <button ref={trigger} type="button" className="app-rail-button" title="More destinations" data-tip="More destinations" aria-label="More destinations" aria-expanded={more} aria-haspopup="menu" onClick={()=>{onDismissPreview?.();const box=trigger.current.getBoundingClientRect();setPosition({left:box.right+8,top:Math.max(8,Math.min(box.top,window.innerHeight-218))});setMore(!more);}}><Icon name="DotsHorizontal"/></button>
          {more&&ReactDOM.createPortal(<div ref={popup} style={{...position,position:'fixed'}} role="menu" aria-label="More destinations" className="app-rail-menu" data-shell-overlay="true" onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();setMore(false);trigger.current?.focus();}if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const rows=[...popup.current.querySelectorAll('[role=menuitem]')],index=rows.indexOf(document.activeElement);rows[event.key==='Home'?0:event.key==='End'?rows.length-1:(index+(event.key==='ArrowDown'?1:rows.length-1))%rows.length]?.focus();}}}><window.VellumUI.SharedRowBackground className="app-rail-menu-list" activeSelector='[role="menuitem"]:focus'>{[['projects','Projects','Folder'],['scheduled','Scheduled','Calendar'],['memory','Memory','MemoryOnRemember'],['kg','Knowledge graph','Nodes']].map(([id,label,icon])=><button key={id} type="button" role="menuitem" data-shared-row="" onClick={()=>{setMore(false);onNav(id);}}><Icon name={icon}/>{label}</button>)}</window.VellumUI.SharedRowBackground></div>,document.body)}
        </div>
      </div>
      <div className="app-rail-account">
        <button type="button" className="app-rail-button" title="Search chats" data-command="commands.open" aria-label="Search chats" onClick={onSearch}><Icon name="Search"/></button>
        <button type="button" className="app-rail-button" title="Notifications" data-tip="Notifications" data-notification-trigger="" aria-controls="notification-panel" aria-expanded={notificationsOpen} aria-label={unread?`Notifications, ${unread} unread`:'Notifications'} onClick={onNotifications}><Icon name="Bell"/>{unread>0&&<span className="app-rail-unread"/>}</button>
        <button type="button" className="app-rail-button" title="Settings" data-command="settings.open" aria-label="Settings" onClick={onSettings}><Icon name="SettingsCog"/></button>
        <button type="button" className="app-rail-avatar" title={profile.displayName||'Account'} data-tip={profile.displayName||'Account'} aria-label="Open account menu" onClick={onProfile}>{String(profile.displayName||'V').split(/\s+/).slice(0,2).map(word=>word[0]).join('')}</button>
      </div>
    </nav>;
  }
  const SidebarHoverContext=React.createContext(null);
  function SidebarHoverProvider({children,enabled=true}) {
    const [active,setActive]=useState(null);
    const shown=useRef(null),pending=useRef(null),openTimer=useRef(null),closeTimer=useRef(null),blocked=useRef(null),dragging=useRef(false);
    const allowed=useRef(enabled);allowed.current=enabled;
    const api=useMemo(()=>{
      const cancelClose=()=>{clearTimeout(closeTimer.current);closeTimer.current=null;};
      const cancelOpen=()=>{clearTimeout(openTimer.current);openTimer.current=null;pending.current=null;};
      const hide=()=>{cancelOpen();cancelClose();shown.current=null;setActive(null);};
      const scheduleClose=()=>{if(!closeTimer.current)closeTimer.current=setTimeout(hide,450);};
      return {
        enter(record,event){
          if(!allowed.current||dragging.current||event?.pointerType==='touch'||blocked.current===record.id)return;
          cancelClose();
          if(shown.current?.id===record.id)return;
          if(pending.current?.id===record.id)return;
          cancelOpen();shown.current=null;setActive(null);pending.current=record;
          openTimer.current=setTimeout(()=>{shown.current=record;pending.current=null;setActive(record.id);},240);
        },
        keep(){cancelClose();window.dispatchEvent(new Event('vellum:sidebar-preview-enter'));},
        leave(record,event){
          if(blocked.current===record.id)blocked.current=null;
          if(pending.current?.id===record.id)cancelOpen();
          if(event?.relatedTarget?.closest?.('[data-sidebar-hover]')?.getAttribute('data-sidebar-hover')===record.id){cancelClose();return;}
          if(shown.current?.id===record.id)scheduleClose();
        },
        dismiss(id){if(shown.current?.id===id||pending.current?.id===id){blocked.current=id;hide();}},
        unregister(id){if(shown.current?.id===id||pending.current?.id===id)hide();},
        reset:hide,
        dragStart(){dragging.current=true;hide();},
        dragEnd(){dragging.current=false;},
        press(event){
          const record=shown.current||pending.current;
          if(record&&!record.anchor.current?.contains(event.target)&&!record.popup.current?.contains(event.target))hide();
        },
        pointer(event){
          const record=shown.current;if(!record)return;
          const row=record.anchor.current,card=record.popup.current;
          if(row?.contains(event.target)||card?.contains(event.target)){cancelClose();return;}
          const a=row?.getBoundingClientRect(),b=card?.getBoundingClientRect();
          // Keep the narrow path between the trigger and portal interactive.
          const inGap=a&&b&&event.clientX>=Math.min(a.right,b.right)&&event.clientX<=Math.max(a.left,b.left)&&event.clientY>=Math.min(a.top,b.top)-6&&event.clientY<=Math.max(a.bottom,b.bottom)+6;
          if(inGap){cancelClose();window.dispatchEvent(new Event('vellum:sidebar-preview-enter'));}
          else scheduleClose();
        },
        escape(event){
          const record=shown.current;if(!record||event.key!=='Escape')return;
          event.preventDefault();event.stopPropagation();blocked.current=record.id;
          const restore=record.popup.current?.contains(document.activeElement);hide();
          if(restore)(record.anchor.current?.querySelector('.project-open')||record.anchor.current)?.focus({preventScroll:true});
        },
        destroy(){cancelOpen();cancelClose();}
      };
    },[]);
    useEffect(()=>{if(!enabled)api.reset();},[enabled,api]);
    useEffect(()=>{document.addEventListener('pointermove',api.pointer);document.addEventListener('pointerdown',api.press,true);document.addEventListener('focusin',api.press,true);document.addEventListener('keydown',api.escape,true);document.addEventListener('dragstart',api.dragStart,true);document.addEventListener('dragend',api.dragEnd,true);document.addEventListener('drop',api.dragEnd,true);return()=>{document.removeEventListener('pointermove',api.pointer);document.removeEventListener('pointerdown',api.press,true);document.removeEventListener('focusin',api.press,true);document.removeEventListener('keydown',api.escape,true);document.removeEventListener('dragstart',api.dragStart,true);document.removeEventListener('dragend',api.dragEnd,true);document.removeEventListener('drop',api.dragEnd,true);api.destroy();};},[api]);
    return <SidebarHoverContext.Provider value={{active:enabled?active:null,api}}>{children}</SidebarHoverContext.Provider>;
  }
  function useSidebarHover(id,anchor,disabled=false){
    const context=React.useContext(SidebarHoverContext),popup=useRef(null),instance=React.useId();
    const key=id+':'+instance,record=useMemo(()=>({id:key,anchor,popup}),[key,anchor]);
    useEffect(()=>{if(disabled)context?.api.dismiss(key);},[disabled,key]);
    useEffect(()=>()=>context?.api.unregister(key),[key]);
    return {id:key,open:!disabled&&context?.active===key,popup,
      enter:event=>{if(!disabled)context?.api.enter(record,event);},
      leave:event=>context?.api.leave(record,event),keep:()=>context?.api.keep(),dismiss:()=>context?.api.dismiss(key)};
  }
  function useSidebarCardPosition(anchor,card,onDismiss){
    const [position,setPosition]=useState(null);
    useLayoutEffect(()=>{
      const place=()=>{
        const box=anchor.current?.getBoundingClientRect();if(!box)return;
        const width=Math.min(360,window.innerWidth-24),height=card.current?.offsetHeight||180;
        const left=box.right+8+width<=window.innerWidth-12?box.right+8:Math.max(12,box.left-width-8);
        const topInset=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--desktop-chrome-height'))||0;
        setPosition({left,width,top:Math.max(topInset+8,Math.min(box.top-3,window.innerHeight-height-12))});
      };
      const scroll=event=>{if(!card.current?.contains(event.target))onDismiss?.();};
      place();const observer=new ResizeObserver(place);if(card.current)observer.observe(card.current);if(anchor.current)observer.observe(anchor.current);
      window.addEventListener('resize',place);window.addEventListener('scroll',scroll,true);
      return()=>{observer.disconnect();window.removeEventListener('resize',place);window.removeEventListener('scroll',scroll,true);};
    },[anchor,card]);
    return position||{visibility:'hidden'};
  }

  function SidebarSectionMenu({label,groups}){
    const [open,setOpen]=useState(false),[pos,setPos]=useState({}),anchor=useRef(null),popup=useRef(null);
    useShellOverlay(open);
    useEffect(()=>{if(!open)return;const close=event=>{if(!anchor.current?.contains(event.target)&&!popup.current?.contains(event.target))setOpen(false);};document.addEventListener('pointerdown',close);popup.current?.querySelector('button')?.focus();return()=>document.removeEventListener('pointerdown',close);},[open]);
    const keys=event=>{if(event.key==='Escape'){event.stopPropagation();event.preventDefault();setOpen(false);anchor.current?.focus();}if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const rows=[...popup.current.querySelectorAll('button')],index=rows.indexOf(document.activeElement);rows[event.key==='Home'?0:event.key==='End'?rows.length-1:(index+(event.key==='ArrowDown'?1:rows.length-1))%rows.length]?.focus();}};
    return <><button ref={anchor} type="button" className="tbtn" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={()=>{const rect=anchor.current.getBoundingClientRect();setPos({left:Math.max(8,Math.min(rect.left,window.innerWidth-244)),top:Math.max(8,Math.min(rect.bottom+5,window.innerHeight-340))});setOpen(!open);}}><Icon name="DotsHorizontal" size={15}/></button>{open&&ReactDOM.createPortal(<div ref={popup} className="shell-section-menu" role="menu" aria-label={label} data-shell-overlay="true" data-sidebar-overlay="true" style={pos} onKeyDown={keys}>{groups.map(group=><section key={group.label}><h3>{group.label}</h3>{group.options.map(([value,name])=><button key={value} type="button" role="menuitemradio" aria-checked={group.value===value} onClick={()=>{group.onChange(value);setOpen(false);anchor.current?.focus();}}><span>{name}</span>{group.value===value&&<Icon name="Check" size={14}/>}</button>)}</section>)}</div>,document.body)}</>;
  }
  function ProjectHoverCard({project,chats,anchor,hoverId,hoverCardRef,onDismiss,onEnter,onClose,onOpen,onPin,onEdit}){
    const fallback=useRef(null),card=hoverCardRef||fallback,[pendingPin,setPendingPin]=useState(false);
    const position=useSidebarCardPosition(anchor,card,onDismiss);useShellOverlay(true);
    const working=chats.filter(chat=>chatStatus(chat)?.id==='working').length,attention=chats.filter(chat=>['attention','error','unread'].includes(chatStatus(chat)?.id)).length;
    return ReactDOM.createPortal(<aside ref={card} className="shell-chat-card shell-project-card" data-sidebar-hover={hoverId} data-shell-overlay="true" data-sidebar-overlay="true" aria-label={'Project details: '+project.name} style={position} onPointerEnter={onEnter} onPointerLeave={onClose} onFocus={onEnter} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))onClose(event);}}>
      <header className="project-card-header"><button type="button" className="project-card-title" aria-label={'Open project '+project.name} onClick={onOpen}><Icon name="Folder" size={17}/><strong>{project.name}</strong></button><button type="button" className="project-card-pin" aria-label={(project.pinned?'Unpin ':'Pin ')+project.name} aria-pressed={!!project.pinned} disabled={pendingPin||!onPin} onClick={async()=>{if(pendingPin)return;setPendingPin(true);try{await onPin();}finally{setPendingPin(false);onDismiss?.();}}}><Icon name="Pin" size={16}/></button></header>
      <div className="project-card-stat"><Icon name="Chat" size={16}/><span>{chats.length} {chats.length===1?'chat':'chats'}</span></div>
      {(working>0||attention>0)&&<div className="project-card-stat"><Icon name="Bell" size={16}/><span>{[working?working+' working':'',attention?attention+' need attention':''].filter(Boolean).join(' · ')}</span></div>}
      {project.sources?.length>0&&<div className="project-card-source"><Icon name="Folder" size={16}/><span>{project.sources.map(source=>source.name).filter(Boolean).join(', ')||project.sources.length+' sources'}</span></div>}
      <footer className="project-card-footer"><button type="button" onClick={onEdit}><Icon name="SettingsCog" size={16}/>Edit project</button></footer>
    </aside>,document.body);
  }
  function RailContextPreview({kind,apps,onChoose,Logo,onEnter,onLeave}){
    useShellOverlay(true);
    const plugin=kind==='apps';
    return <aside className="rail-context-preview sidebar" data-shell-overlay="true" data-sidebar-overlay="true" aria-label={plugin?'Plugins preview':'Music preview'} onPointerEnter={onEnter} onPointerLeave={onLeave}><div className="sb-head"><h2>{plugin?'Plugins':'Music'}</h2></div><div className="sb-scroll"><window.VellumUI.SharedRowBackground className="shell-nav-group">{(plugin?[['directory','Plugins','ConnectApps'],['skills','Skills','Grid']]:[['home','Home','Home'],['search','Search','Search'],['playlists','Playlists','Music'],['sources','Sources','ConnectApps']]).map(([id,label,icon])=><button type="button" key={id} className="sb-row" data-shared-row="" onClick={()=>onChoose(kind,id)}><Icon name={icon} size={18}/>{label}</button>)}</window.VellumUI.SharedRowBackground>{plugin&&<section className="shell-library-source"><h3>Installed</h3>{apps.filter(app=>app.installed!==false).map(app=><button type="button" className="sb-row" key={app.id} onClick={()=>onChoose(kind,'detail',app.id)}><Logo c={app} size={20}/><span className="shell-folder-name">{app.name}</span></button>)}</section>}</div></aside>;
  }

  function chatStatus(chat){
    const messages=chat.messages||[],last=[...messages].reverse().find(item=>item.role==='assistant');
    if(chat.organization?.status==='Follow-up'||last?.requires_approval)return {id:'attention',label:'Needs your attention',icon:'Bell'};
    if(last?.error||last?.responseStatus==='failed')return {id:'error',label:'Error',icon:'InfoCircle'};
    if(messages.some(item=>item.streaming||item.queued))return {id:'working',label:'Working'};
    if(chat.unread)return {id:'unread',label:'Unread'};
    return null;
  }
  function ChatStatus({chat}){const status=chatStatus(chat);return status?<span className={'shell-chat-status is-'+status.id} title={status.label} aria-label={status.label}>{status.icon&&<Icon name={status.icon} size={13}/>}</span>:null;}
  function ChatHoverCard({chat,project,anchor,hoverId,hoverCardRef,onOpen,onClose,onEnter,onDismiss}){
    const fallback=useRef(null),card=hoverCardRef||fallback,position=useSidebarCardPosition(anchor,card,onDismiss);useShellOverlay(true);
    const date=new Date(chat.updated_at||chat.created_at||'');
    return ReactDOM.createPortal(<aside ref={card} className="shell-chat-card" data-sidebar-hover={hoverId} data-sidebar-overlay="true" data-shell-overlay="true" aria-label="Conversation details" style={position} onPointerEnter={onEnter} onPointerLeave={onClose} onFocus={onEnter} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))onClose(event);}} onClick={event=>event.stopPropagation()}>
      <strong>{chat.title||'Untitled chat'}</strong><div className="shell-chat-card-meta"><ChatStatus chat={chat}/>{chatStatus(chat)?.label||'Conversation'}{!Number.isNaN(date.getTime())&&<time dateTime={date.toISOString()}>{date.toLocaleDateString(undefined,{month:'short',day:'numeric'})}</time>}</div>
      {(project||chat.organization?.space_label)&&<p><Icon name="Folder" size={15}/>{project?.name||chat.organization.space_label}</p>}{chat.organization?.topic_label&&<p>{chat.organization.topic_label}</p>}
      <button type="button" onClick={onOpen}>Open chat<Icon name="ArrowRight" size={14}/></button>
    </aside>,document.body);
  }
  function LibrarySidebar({section,onSection,items,projects=[]}){
    return <aside className="sidebar library-navigation" aria-label="Library navigation">
      <div className="sb-head"><h2>Library</h2></div>
      <div className="sb-scroll"><div className="shell-nav-group">{[['all','All files','FileDocument'],['favorites','Favorites','Heart'],['images','Images','ImageSquare'],['files','Documents','Folder'],['trash','Trash','Trash']].map(([id,label,icon])=><button type="button" className={'sb-row'+(section===id?' active':'')} aria-current={section===id?'page':undefined} key={id} onClick={()=>onSection(id)}><span className="sb-ic"><Icon name={icon}/></span><span>{label}</span>{id==='all'&&<small className="space-count">{items.filter(item=>!item.trashed).length}</small>}</button>)}</div>
        <section className="shell-library-source"><h3>Project folders</h3>{projects.map(project=><button type="button" className={'sb-row'+(section==='project:'+project.id?' active':'')} aria-current={section==='project:'+project.id?'page':undefined} key={project.id} onClick={()=>onSection('project:'+project.id)}><Icon name="Folder" size={16}/><span className="shell-folder-name">{project.name}</span></button>)}{!projects.length&&<p>No projects yet.</p>}</section>
        <section className="shell-library-source"><h3>Sources</h3><p><Icon name="Chat" size={15}/>Chat attachments</p><p><Icon name="FileDocument" size={15}/>This session</p></section>
      </div>
      <p className="shell-sidebar-note">Files remain on this device. Session uploads and organization reset when Vellum reloads.</p>
    </aside>;
  }
  // Read-only projection: chat attachments remain owned by conversations. Session
  // overrides stay in the incumbent collection, never mutate a conversation.
  function libraryItems(collection,chats){
    const rows=new Map();
    for(const chat of chats||[])for(const message of chat.messages||[])for(const [index,file] of (message.attachments||[]).entries()){
      if(file.reference)continue;
      const id='chat-file:'+(file.digest||`${chat.id}:${message.id}:${index}`);
      if(rows.has(id)){const prior=rows.get(id);prior.projectIds=[...new Set([...(prior.projectIds||[]),chat.projectId].filter(Boolean))];}
      if(!rows.has(id))rows.set(id,{id,projectIds:chat.projectId?[chat.projectId]:[],name:file.name||'Attachment',kind:file.kind||'file',size:file.size||'',modified:chat.updated_at||chat.created_at||chat.created||'',source:'chat',chatId:chat.id,chatTitle:chat.title,projectId:chat.projectId,attachment:file});
    }
    for(const item of collection||[]){
      const key=item.attachment?.digest?'chat-file:'+item.attachment.digest:item.id;
      const canonical=rows.get(key);
      if(item.source==='chat'&&!canonical)continue;
      rows.set(key,{...canonical,...item,...(canonical?{attachment:canonical.attachment,chatId:canonical.chatId,chatTitle:canonical.chatTitle,projectIds:canonical.projectIds}:{}),id:key,source:canonical?.source||'session'});
    }
    return [...rows.values()];
  }
  function safeFileUrl(value){
    if(!value)return '';
    try{const url=new URL(value,window.location.href);return ['http:','https:','blob:'].includes(url.protocol)||/^data:(?:image\/|text\/|application\/(?:pdf|json|octet-stream))/.test(value)?url.href:'';}catch{return '';}
  }
  function fileUrl(item){return safeFileUrl(item.attachment?.data_url||item.attachment?.url||item.url);}
  function LibraryWorkspace({items,section,onSection,onUpdate,onUpload,onOpenChat,projects=[],Icon:KindIcon}){
    const [query,setQuery]=useState(''),[mode,setMode]=useState('grid'),[source,setSource]=useState('all'),[sort,setSort]=useState('recent'),[selected,setSelected]=useState([]),[preview,setPreview]=useState(null),[renaming,setRenaming]=useState(null),[draft,setDraft]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
    const input=useRef(null),previewClose=useRef(null),previewTrigger=useRef(null),search=useRef(null);
    useShellOverlay(!!preview);
    const visible=useMemo(()=>items.filter(item=>(section==='trash'?item.trashed:!item.trashed)&&(section!=='favorites'||item.favorite)&&(section!=='images'||item.kind==='image')&&(section!=='files'||item.kind!=='image')&&(!section.startsWith('project:')||(item.folderId?item.folderId===section.slice(8):(item.projectIds||[item.projectId]).includes(section.slice(8))))&&(source==='all'||item.source===source)&&item.name.toLocaleLowerCase().includes(query.toLocaleLowerCase())).sort((a,b)=>sort==='name'?a.name.localeCompare(b.name):(Date.parse(b.modified)||0)-(Date.parse(a.modified)||0)),[items,section,query,source,sort]);
    useEffect(()=>{setSelected([]);setRenaming(null);},[section,query,source]);
    useEffect(()=>{setSelected(current=>current.filter(id=>items.some(item=>item.id===id)));},[items]);
    useEffect(()=>{if(preview)previewClose.current?.focus();else if(previewTrigger.current?.isConnected)previewTrigger.current.focus({preventScroll:true});},[preview]);
    const chosen=items.filter(item=>selected.includes(item.id));
    const label={all:'All files',favorites:'Favorites',images:'Images',files:'Documents',trash:'Trash'}[section]||(section.startsWith('project:')?projects.find(project=>project.id===section.slice(8))?.name:'')||'All files';
    const update=(rows,patch)=>onUpdate(rows.map(row=>row.id),patch);
    const toggle=id=>setSelected(current=>current.includes(id)?current.filter(value=>value!==id):[...current,id]);
    const download=item=>{const url=fileUrl(item);if(!url)return;const link=document.createElement('a');link.href=url;link.download=item.name;link.rel='noopener';if(/^https?:/.test(url))link.target='_blank';link.click();};
    const rename=()=>{if(draft.trim()&&renaming)onUpdate([renaming],{name:draft.trim()});setRenaming(null);};
    const showPreview=(item,event)=>{previewTrigger.current=event.currentTarget;setPreview(item);};
    const options=item=><div className="library-row-actions">
      <button type="button" title={item.favorite?'Remove favorite':'Add to favorites'} aria-label={(item.favorite?'Unfavorite ':'Favorite ')+item.name} aria-pressed={!!item.favorite} onClick={()=>update([item],{favorite:!item.favorite})}><Icon name="Heart" size={16}/></button>
      <button type="button" title={'Rename '+item.name} aria-label={'Rename '+item.name} onClick={()=>{setRenaming(item.id);setDraft(item.name);}}><Icon name="Edit" size={16}/></button>
      <button type="button" title={item.trashed?'Restore':'Move to trash'} aria-label={(item.trashed?'Restore ':'Move to trash ')+item.name} onClick={()=>update([item],{trashed:!item.trashed})}><Icon name={item.trashed?'ArrowRotateCw':'Trash'} size={16}/></button>
    </div>;
    return <section className="library-workspace" aria-label="Library workspace" onKeyDown={event=>{if(event.key==='Escape'){setPreview(null);setSelected([]);setRenaming(null);}}}>
      <header className="library-browsing-header"><div className="library-heading"><div><span className="library-eyebrow">Library</span><h1>{label}</h1></div><button type="button" className="btn" disabled={busy} onClick={()=>input.current?.click()}><Icon name="UploadDocuments" size={16}/>{busy?'Adding files…':'Add files'}</button></div>
        <div className="library-controls"><label className="library-query"><Icon name="Search" size={17}/><input ref={search} aria-label="Search library" placeholder="Search your files" value={query} onChange={event=>setQuery(event.target.value)}/>{query&&<button type="button" aria-label="Clear search" onClick={()=>{setQuery('');search.current?.focus();}}><Icon name="X" size={14}/></button>}</label>
          <window.VellumUI.VSelect sharedLayout className="library-filter-select" ariaLabel="Filter by source" value={source} onValueChange={setSource} options={[{value:'all',label:'All sources'},{value:'chat',label:'Chat attachments'},{value:'session',label:'This session'}]}/>
          <window.VellumUI.VSelect sharedLayout className="library-sort-select" ariaLabel="Sort library" value={sort} onValueChange={setSort} options={[{value:'recent',label:'Recently added'},{value:'name',label:'Name'}]}/>
          <div className="library-view-toggle" role="group" aria-label="Library layout"><button type="button" title="Grid view" aria-label="Grid view" aria-pressed={mode==='grid'} onClick={()=>setMode('grid')}><Icon name="Grid" size={17}/></button><button type="button" title="List view" aria-label="List view" aria-pressed={mode==='list'} onClick={()=>setMode('list')}><Icon name="Menu" size={17}/></button></div>
        </div>
        <div className="library-mobile-sections" role="group" aria-label="Library sections">{['all','favorites','images','files','trash'].map(id=><button key={id} type="button" aria-pressed={section===id} onClick={()=>onSection(id)}>{{all:'All files',favorites:'Favorites',images:'Images',files:'Documents',trash:'Trash'}[id]}</button>)}</div>
      </header>
      <input hidden ref={input} type="file" multiple onChange={async event=>{const files=[...(event.target.files||[])];event.target.value='';if(!files.length)return;setBusy(true);setError('');try{await onUpload(files);}catch(failure){setError(failure.message||'These files could not be added.');}finally{setBusy(false);}}}/>
      {error&&<p className="library-error" role="alert">{error}</p>}
      <div className="library-results-meta"><span>{visible.length} {visible.length===1?'file':'files'}{query&&` matching “${query}”`}</span>{visible.length>0&&<label><input type="checkbox" aria-label="Select all visible files" checked={visible.every(item=>selected.includes(item.id))} onChange={event=>setSelected(event.target.checked?visible.map(item=>item.id):[])}/>Select all</label>}</div>
      {chosen.length>0&&<div className="library-selection-bar" role="region" aria-label="Selected files"><strong>{chosen.length} selected</strong>{projects.length>0&&<window.VellumUI.VSelect sharedLayout className="library-organize-select" ariaLabel="Organize selected files in a project folder for this session" value="" placeholder="Organize…" options={projects.map(project=>({value:project.id,label:project.name}))} onValueChange={folderId=>update(chosen,{folderId})}/>}<button type="button" onClick={()=>update(chosen,{favorite:true})}>Favorite</button><button type="button" onClick={()=>{update(chosen,{trashed:section!=='trash'});setSelected([]);}}>{section==='trash'?'Restore':'Move to trash'}</button><button type="button" title={chosen.length!==1?'Select one file to download':!fileUrl(chosen[0])?'This attachment has no downloadable content':undefined} disabled={chosen.length!==1||!fileUrl(chosen[0])} onClick={()=>download(chosen[0])}>Download</button><button type="button" aria-label="Clear selection" onClick={()=>setSelected([])}><Icon name="X" size={15}/></button></div>}
      <div className={'library-results library-'+mode}>
        {mode==='list'&&visible.length>0&&<div className="library-list-heading"><span/><span>Name</span><span>Source</span><span>Updated</span><span/></div>}
        {visible.map(item=><article key={item.id} className={'library-file'+(selected.includes(item.id)?' selected':'')}>
          <label className="library-select"><input type="checkbox" aria-label={'Select '+item.name} checked={selected.includes(item.id)} onChange={()=>toggle(item.id)}/></label>
          <button type="button" className={'library-file-preview kind-'+item.kind} onClick={event=>showPreview(item,event)} aria-label={'Preview '+item.name}>{item.kind==='image'&&fileUrl(item)?<img loading="lazy" src={fileUrl(item)} alt=""/>:<KindIcon kind={item.kind}/>}</button>
          <div className="library-file-copy">{renaming===item.id?<input className="rename-input" autoFocus aria-label="File name" value={draft} onChange={event=>setDraft(event.target.value)} onBlur={rename} onKeyDown={event=>{if(event.key==='Enter')rename();if(event.key==='Escape'){event.stopPropagation();setRenaming(null);}}}/>:<button type="button" className="library-file-name" title={item.name} onClick={event=>showPreview(item,event)}>{item.name}</button>}<span>{item.size||item.kind}</span></div>
          <span className="library-file-source" title={item.chatTitle||'This session'}>{item.source==='chat'?'Chat attachment':'This session'}</span>
          <time className="library-file-date">{Number.isNaN(Date.parse(item.modified))?item.modified:new Date(item.modified).toLocaleDateString(undefined,{month:'short',day:'numeric'})}</time>{options(item)}
        </article>)}
        {!visible.length&&<div className="library-empty"><Icon name={section==='trash'?'Trash':'FileDocument'} size={32}/><h2>{query?'No matching files':section==='favorites'?'Keep useful files close':section==='trash'?'Trash is empty':'Your files, together'}</h2><p>{query?'Try a different name or source.':section==='favorites'?'Favorite a file to find it here.':section==='trash'?'Files moved here stay out of the main list.':'Attachments from your chats appear here. Add files to use during this session.'}</p>{(query||source!=='all')&&<button type="button" className="btn" onClick={()=>{setQuery('');setSource('all');}}>Clear filters</button>}</div>}
      </div>
      {preview&&ReactDOM.createPortal(<div className="library-preview-backdrop" data-shell-overlay="true" onClick={()=>setPreview(null)} onKeyDown={event=>{
        if(event.key==='Escape'){event.preventDefault();setPreview(null);}
        if(event.key==='Tab'){const buttons=[...event.currentTarget.querySelectorAll('button:not(:disabled),iframe')],first=buttons[0],last=buttons[buttons.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}
      }}><section className="library-preview-panel" role="dialog" aria-modal="true" aria-label={'Preview '+preview.name} onClick={event=>event.stopPropagation()}><header><h2>{preview.name}</h2><button ref={previewClose} type="button" aria-label="Close preview" onClick={()=>setPreview(null)}><Icon name="X"/></button></header><div className="library-preview-content">{preview.kind==='image'&&fileUrl(preview)?<img src={fileUrl(preview)} alt={preview.name}/>:preview.attachment?.text_content?<pre>{preview.attachment.text_content}</pre>:<div className="library-empty"><KindIcon kind={preview.kind}/><p>No inline preview is available for this file.</p></div>}</div><footer><span>{preview.size} · {preview.source==='chat'?'Chat attachment':'This session'}</span>{preview.chatId&&<button type="button" className="btn" onClick={()=>{onOpenChat(preview.chatId);setPreview(null);}}>Open chat</button>}<button type="button" className="btn" disabled={!fileUrl(preview)} onClick={()=>download(preview)}>Download</button></footer></section></div>,document.body)}
    </section>;
  }
  window.VellumUI=Object.assign(window.VellumUI||{}, {ModeSwitcher,NavigationRail,SidebarHoverProvider,useSidebarHover,SidebarSectionMenu,ProjectHoverCard,RailContextPreview,chatStatus,ChatStatus,ChatHoverCard,LibrarySidebar,LibraryWorkspace,libraryItems});
})();
