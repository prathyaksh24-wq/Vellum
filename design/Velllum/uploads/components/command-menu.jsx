(function(){
  const {useState,useEffect,useLayoutEffect,useRef,useMemo}=React;
  const Icon=props=><window.VellumUI.AppIcon {...props}/>;
  const Shared=props=><window.VellumUI.SharedRowBackground {...props}/>;
  function CommandMenu({runtime,chats=[],projects=[],scope='all',onClose,onCommand,onChat,onProject}){
    const [query,setQuery]=useState(''),[active,setActive]=useState(''),input=useRef(null),panel=useRef(null),previous=useRef(document.activeElement);
    const entries=runtime?.entries({overlay:false,browser:true})||[];
    const rows=useMemo(()=>{
      const q=query.trim().toLocaleLowerCase();
      const matches=text=>!q||String(text).toLocaleLowerCase().includes(q);
      const commandRows=scope==='projects'?[]:entries.filter(entry=>matches(entry.label+' '+entry.id)).slice(0,q?18:10).map(entry=>({id:entry.id,label:entry.label,kind:'command',keys:entry.keys,group:entry.group}));
      const chatRows=scope==='projects'?[]:chats.filter(chat=>!chat.archived&&matches(chat.title)).slice(0,q?12:5).map(chat=>({id:'chat:'+chat.id,target:chat.id,label:chat.title,kind:'chat',group:'Conversations'}));
      const projectRows=projects.filter(project=>matches(project.name)).slice(0,10).map(project=>({id:'project:'+project.id,target:project.id,label:project.name,kind:'project',group:'Projects'}));
      return [...commandRows,...chatRows,...projectRows];
    },[query,scope,chats,projects,entries.map(entry=>entry.id).join('|')]);
    const selected=rows.find(row=>row.id===active)||rows[0];
    useEffect(()=>{input.current?.focus();return()=>{if(previous.current?.isConnected)previous.current.focus({preventScroll:true});};},[]);
    useLayoutEffect(()=>{window.dispatchEvent(new Event('vellum:shell-overlay'));return()=>requestAnimationFrame(()=>window.dispatchEvent(new Event('vellum:shell-overlay')));},[]);
    useLayoutEffect(()=>{panel.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest'});},[selected?.id]);
    const choose=row=>{if(!row)return;onClose();if(row.kind==='chat')onChat(row.target);else if(row.kind==='project')onProject(row.target);else onCommand(row.id);};
    return ReactDOM.createPortal(<div className="command-backdrop" data-shell-overlay="true" onPointerDown={event=>{if(event.target===event.currentTarget)onClose();}}>
      <section className="command-menu" role="dialog" aria-modal="true" aria-label={scope==='projects'?'Choose a project':'Search commands and chats'} onKeyDown={event=>{
        if((event.ctrlKey||event.metaKey)&&event.code==='KeyK'){event.preventDefault();event.stopPropagation();input.current?.select();}
        if(event.key==='Escape'){event.preventDefault();event.stopPropagation();onClose();}
        if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)&&!event.ctrlKey&&!event.metaKey){event.preventDefault();const index=rows.indexOf(selected);setActive(rows[event.key==='Home'?0:event.key==='End'?rows.length-1:(index+(event.key==='ArrowDown'?1:rows.length-1))%rows.length]?.id||'');}
        if(event.key==='Enter'){event.preventDefault();choose(selected);}
        if(event.key==='Tab'){event.preventDefault();input.current?.focus();}
      }}>
        <label className="command-query"><Icon name="Search"/><input ref={input} role="combobox" aria-expanded="true" aria-controls="vellum-command-results" aria-activedescendant={selected?'command-result-'+selected.id:undefined} aria-label="Search commands, chats and projects" placeholder={scope==='projects'?'Find a project':'Search commands, chats and projects'} value={query} onChange={event=>{setQuery(event.target.value);setActive('');}}/><kbd>Esc</kbd></label>
        <Shared className="command-results" role="listbox" id="vellum-command-results" activeSelector='[aria-selected="true"]' refreshKey={selected?.id}>
          <div ref={panel}>{rows.map((row,index)=><React.Fragment key={row.id}>{rows[index-1]?.group!==row.group&&<h3>{row.group}</h3>}<button type="button" role="option" id={'command-result-'+row.id} aria-selected={row===selected} data-shared-row="" tabIndex={-1} onPointerMove={()=>setActive(row.id)} onClick={()=>choose(row)}><Icon name={row.kind==='chat'?'Chat':row.kind==='project'?'Folder':'ArrowRight'} size={16}/><span>{row.label}</span>{row.keys?.[0]&&<kbd>{window.VellumCommands.displayKey(row.keys[0])}</kbd>}</button></React.Fragment>)}{!rows.length&&<p className="command-empty">No matching commands, chats or projects.</p>}</div>
        </Shared>
        <footer><span>Use arrow keys to choose</span><span>Enter to open</span></footer>
      </section>
    </div>,document.body);
  }
  function ShortcutReference({dictation={},numberPrimary='tabs',onNumberPrimary}){
    const [query,setQuery]=useState(''),[ready,setReady]=useState(!!window.VellumCommands);
    useEffect(()=>{const update=()=>setReady(true);window.addEventListener('vellum:commands-ready',update);return()=>window.removeEventListener('vellum:commands-ready',update);},[]);
    if(!ready)return <p>Loading shortcuts…</p>;
    const registry=window.VellumCommands;
    const entries=registry.commands.filter(command=>!command.hidden&&(!query||(command.label+' '+command.keys.join(' ')).toLowerCase().includes(query.toLowerCase())));
    const groups=[...new Set(entries.map(entry=>entry.group))];
    return <div className="shortcut-reference"><label className="shortcut-search"><Icon name="Search" size={16}/><input aria-label="Search keyboard shortcuts" placeholder="Search shortcuts" value={query} onChange={event=>setQuery(event.target.value)}/></label>
      <div className="shortcut-number-choice"><div><strong>Number keys</strong><p>Use 1–8 for a position and 9 for the last item.</p></div>{onNumberPrimary?<window.VellumUI.VSelect sharedLayout ariaLabel="Number shortcut preference" value={numberPrimary} options={[{value:'tabs',label:'Tabs primary'},{value:'chats',label:'Chats primary'}]} onValueChange={onNumberPrimary}/>:<span>{numberPrimary==='tabs'?'Tabs primary':'Chats primary'}</span>}</div>
      <p className="set-note">Ctrl+1–9 switches {numberPrimary==='tabs'?'browser tabs':'sidebar chats'}; Alt+1–9 switches {numberPrimary==='tabs'?'sidebar chats':'browser tabs'}. Text editors and open popups keep their own editing keys.</p>
      {groups.map(group=><section className="sc-group" key={group}><h3 className="sc-grp-h">{group}</h3>{entries.filter(entry=>entry.group===group).map(entry=><div className="sc-row" key={entry.id}><span className="sc-label">{entry.label}{entry.scope==='browser'&&<small>Browser focus</small>}</span><span className="sc-keys">{entry.keys.map(key=><kbd className="kbd" key={key}>{registry.displayKey(key)}</kbd>)}</span></div>)}</section>)}
      {!query&&<section className="sc-group"><h3 className="sc-grp-h">Dictation and editing</h3>{[['Toggle dictation',dictation.toggle_shortcut],['Hold to dictate',dictation.hold_shortcut],['Send message','Enter'],['New line','Shift+Enter']].map(([label,key])=><div className="sc-row" key={label}><span>{label}</span><kbd className="kbd">{key||'Not assigned'}</kbd></div>)}</section>}
      {!query&&<section className="sc-group"><h3 className="sc-grp-h">Not available yet</h3>{registry.unavailable.map(item=><div className="shortcut-unavailable" key={item.label}><strong>{item.label}</strong><p>{item.reason}</p></div>)}</section>}
    </div>;
  }
  function SurfaceFind({onFind,onClose,label='Find on this page'}){
    const [text,setText]=useState(''),input=useRef(null),previous=useRef(document.activeElement),last=useRef('');
    useEffect(()=>{input.current?.focus();return()=>{if(previous.current?.isConnected)previous.current.focus({preventScroll:true});};},[]);
    useEffect(()=>{const timer=setTimeout(()=>{if(last.current!==text){last.current=text;onFind(text,false,true);}},180);return()=>clearTimeout(timer);},[text]);
    useLayoutEffect(()=>{window.dispatchEvent(new Event('vellum:shell-overlay'));return()=>requestAnimationFrame(()=>window.dispatchEvent(new Event('vellum:shell-overlay')));},[]);
    return <div className="surface-find" data-shell-overlay="true" role="search" aria-label={label} onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();onClose();}if(event.key==='Enter'){event.preventDefault();onFind(text,true,!event.shiftKey);}}}><input ref={input} aria-label={label} value={text} placeholder="Find…" onChange={event=>setText(event.target.value)}/><button type="button" title="Previous result" aria-label="Previous result" disabled={!text} onClick={()=>onFind(text,true,false)}><Icon name="ChevronLeft" size={16}/></button><button type="button" title="Next result" aria-label="Next result" disabled={!text} onClick={()=>onFind(text,true,true)}><Icon name="ChevronRight" size={16}/></button><button type="button" title="Close find" aria-label="Close find" onClick={onClose}><Icon name="X" size={16}/></button></div>;
  }
  window.VellumUI=Object.assign(window.VellumUI||{},{CommandMenu,ShortcutReference,SurfaceFind});
})();
