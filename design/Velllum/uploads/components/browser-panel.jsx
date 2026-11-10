(function () {
  const {useState, useEffect, useLayoutEffect, useRef} = React;
  function BrowserCursorGraphic({preferences={}, size}) {
    const style=preferences.cursor_style || 'classic';
    const width=size || preferences.cursor_size || 28;
    if (style==='custom' && preferences.cursor_image?.startsWith('data:image/png;base64,')) return <img src={preferences.cursor_image} width={width} height={width} alt=""/>;
    const colors={classic:['#20252b','#ffffff'],light:['#ffffff','#20252b'],ember:['#ff8655','#332016'],mint:['#7ce8bd','#12372c'],pixel:['#fff5cf','#252525']};
    const [fill,stroke]=colors[style] || colors.classic;
    return <svg width={width} height={width} viewBox="0 0 32 32" aria-hidden="true"><path d={style==='pixel' ? 'M3 2h4v4h4v4h4v4h4v4h-8v4H7v-8H3Z' : 'M3 2 24 18l-10 1-5 9Z'} fill={fill} stroke={stroke} strokeWidth="1.6" strokeLinejoin="round"/></svg>;
  }
  function pointerLayout(frame,width,height,preferences={}) {
    const scale=Math.min(width/frame.width,height/frame.height);
    const size=preferences.cursor_size || 28;
    return {width:frame.width*scale,height:frame.height*scale,
      x:frame.pointer.x*scale-(preferences.cursor_style==='custom'?(preferences.cursor_hotspot_x||0):size*3/32),
      y:frame.pointer.y*scale-(preferences.cursor_style==='custom'?(preferences.cursor_hotspot_y||0):size*2/32)};
  }
  // Saved preference belongs to Workspace Layout. Pixel geometry is a
  // transient projection of the actual region left after the main sidebar.
  const SplitContext = React.createContext(null);
  const SPLIT_CHAT_MIN = 320, SPLIT_BROWSER_MIN = 400, SPLIT_HANDLE = 1;
  const splitPreference = value => Number.isFinite(value) ? Math.max(20,Math.min(75,value)) : 38;
  function splitGeometry(width, preference) {
    width=Math.max(0,width);
    const available=Math.max(0,width-SPLIT_HANDLE);
    const mode=available>=SPLIT_CHAT_MIN+SPLIT_BROWSER_MIN ? 'split' : 'drawer';
    const minimum=mode==='split' ? Math.max(20,SPLIT_CHAT_MIN/available*100) : 20;
    const maximum=mode==='split' ? Math.min(75,(available-SPLIT_BROWSER_MIN)/available*100) : 75;
    const ratio=Math.max(minimum,Math.min(maximum,splitPreference(preference)));
    const left=mode==='split' ? available*ratio/100 : width;
    const right=mode==='split' ? available-left : Math.min(width,Math.max(SPLIT_BROWSER_MIN,width-48));
    return {mode,width,left,right,ratio,minimum,maximum};
  }
  function BrowserSplitView({active=false,mode='split',value=38,onChange,onDismiss,onMotionChange,children}) {
    const root=useRef(null),preference=useRef(splitPreference(value));
    const settings=useRef({value,onChange});settings.current={value,onChange};
    const revision=useRef(0),settleFrame=useRef(0);
    const [geometry,setGeometry]=useState(()=>splitGeometry(0,value));
    const [present,setPresent]=useState(active),[motion,setMotion]=useState(active?'open':'closed');
    const motionCallback=useRef(onMotionChange);motionCallback.current=onMotionChange;
    useLayoutEffect(()=>{
      const reduced=window.matchMedia?.('(prefers-reduced-motion:reduce)').matches;
      if(active){setPresent(true);setMotion(reduced?'open':'entering');}
      else if(present)setMotion(reduced?'closed':'leaving');
      if(reduced){setPresent(active);motionCallback.current?.(false);return;}
      if(!active&&!present)return;
      motionCallback.current?.(true);
      const timer=setTimeout(()=>{setPresent(active);setMotion(active?'open':'closed');motionCallback.current?.(false);},active?240:170);
      return()=>clearTimeout(timer);
    },[active]);
    const shown=active||present;
    const apply=(next=preference.current,source='input')=>{
      const node=root.current;if(!node)return;
      preference.current=splitPreference(next);
      const width=node.getBoundingClientRect().width;
      if(!width)return;
      const result=splitGeometry(width,preference.current);
      node.dataset.splitMode=shown ? (mode==='full'?'full':result.mode) : 'closed';
      node.parentElement?.parentElement?.style.setProperty('--workspace-chat-width',result.left+'px');
      node.dataset.splitSizing=source;
      node.style.setProperty('--split-left-width',result.left+'px');
      node.style.setProperty('--split-right-width',result.right+'px');
      node.style.setProperty('--split-handle-width',SPLIT_HANDLE+'px');
      cancelAnimationFrame(settleFrame.current);
      if(source==='container')settleFrame.current=requestAnimationFrame(()=>{
        settleFrame.current=requestAnimationFrame(()=>{if(root.current)root.current.dataset.splitSizing='steady';});
      });
      setGeometry(current=>Object.keys(result).every(key=>current[key]===result[key]) ? current : result);
      return result;
    };
    const controller=useRef(null);
    controller.current={
      geometry,
      apply,
      fromPointer:x=>{
        const node=root.current;if(!node)return;
        const rect=node.getBoundingClientRect(),current=splitGeometry(rect.width,preference.current);
        if(current.mode!=='split')return;
        const ratio=(x-rect.left)/(rect.width-SPLIT_HANDLE)*100;
        return apply(Math.max(current.minimum,Math.min(current.maximum,ratio)),'drag');
      },
      commit:next=>{
        const committed=Math.round(splitPreference(next)),epoch=++revision.current;
        apply(committed);
        Promise.resolve().then(()=>settings.current.onChange?.(committed)).then(receipt=>{
          if(epoch!==revision.current || !root.current)return;
          if(receipt===null || (receipt?.status && receipt.status!=='applied'))apply(settings.current.value);
        }).catch(()=>{if(epoch===revision.current && root.current)apply(settings.current.value);});
      },
      cancel:()=>apply(settings.current.value),
      root,
    };
    useLayoutEffect(()=>{
      preference.current=splitPreference(value);
      apply(preference.current,'container');
    },[active,present,mode,value]);
    useLayoutEffect(()=>{
      const node=root.current;if(!node)return;
      const measure=()=>controller.current.apply(preference.current,'container');
      const observer=typeof ResizeObserver==='function' ? new ResizeObserver(measure) : null;
      observer?.observe(node);
      if(!observer)window.addEventListener('resize',measure);
      return ()=>{observer?.disconnect();window.removeEventListener('resize',measure);cancelAnimationFrame(settleFrame.current);};
    },[]);
    const panes=React.Children.toArray(children),drawer=shown && mode!=='full' && geometry.mode==='drawer';
    useLayoutEffect(()=>{
      const main=root.current?.querySelector(':scope > .main');
      if(main)main.inert=drawer;
      return ()=>{if(main)main.inert=false;};
    },[drawer]);
    return <SplitContext.Provider value={controller}>
      <div ref={root} className={'workspace-split'+(shown?' browser-layout':'')} data-panel-motion={motion} data-split-mode={shown?(mode==='full'?'full':geometry.mode):'closed'}>
        {panes[0] && React.cloneElement(panes[0],{'aria-hidden':drawer?true:undefined})}
        {drawer && <button type="button" className="browser-drawer-backdrop" aria-label="Return to chat" onClick={onDismiss}/>}
        {shown && mode!=='full' && <BrowserSplitter value={value}/>}
        {panes[1]&&React.cloneElement(panes[1],{hidden:!shown,inert:!active?'':undefined})}
      </div>
    </SplitContext.Provider>;
  }
  function BrowserSplitter({value=38,onChange}) {
    const context=React.useContext(SplitContext);
    const ref=useRef(null),drag=useRef(null),frame=useRef(0);
    const settings=useRef({context,value,onChange});settings.current={context,value,onChange};
    const controls=()=>settings.current.context?.current;
    const setDragging=enabled=>{
      const node=controls()?.root.current || ref.current?.parentElement;
      node?.classList.toggle('browser-resizing',enabled);
    };
    const paint=()=>{frame.current=0;if(drag.current)controls()?.fromPointer(drag.current.x);};
    const finish=(commit=true)=>{
      if(!drag.current)return;
      const current=drag.current;drag.current=null;cancelAnimationFrame(frame.current);frame.current=0;
      const owner=controls(),result=commit ? owner?.fromPointer(current.x) : null;
      setDragging(false);
      if(commit && result && Math.abs(result.left-current.left)>.5)owner.commit(result.ratio);else owner?.cancel();
      if(ref.current?.hasPointerCapture?.(current.id))ref.current.releasePointerCapture(current.id);
    };
    const handlers=useRef(null);handlers.current={finish};
    useEffect(()=>{
      const end=()=>handlers.current.finish(),cancel=()=>handlers.current.finish(false);
      window.addEventListener('pointerup',end);window.addEventListener('blur',cancel);
      return ()=>{window.removeEventListener('pointerup',end);window.removeEventListener('blur',cancel);cancelAnimationFrame(frame.current);setDragging(false);};
    },[]);
    const geometry=controls()?.geometry || splitGeometry(0,value);
    const position=Math.round(geometry.ratio*10)/10;
    return <div ref={ref} className="browser-splitter" role="separator" aria-label="Resize chat and browser" aria-orientation="vertical"
      aria-valuemin={Math.round(geometry.minimum*10)/10} aria-valuemax={Math.round(geometry.maximum*10)/10} aria-valuenow={position}
      aria-valuetext={Math.round(geometry.left)+' pixels for chat, '+Math.round(geometry.right)+' pixels for browser'} tabIndex="0"
      onPointerDown={event=>{if(event.button!==0 || geometry.mode!=='split')return;event.preventDefault();drag.current={x:event.clientX,left:geometry.left,id:event.pointerId};event.currentTarget.setPointerCapture?.(event.pointerId);setDragging(true);}}
      onPointerMove={event=>{if(drag.current){drag.current.x=event.clientX;if(!frame.current)frame.current=requestAnimationFrame(paint);}}}
      onPointerUp={event=>{if(drag.current){drag.current.x=event.clientX;finish();}}}
      onPointerCancel={()=>finish(false)}
      onLostPointerCapture={()=>finish()}
      onDoubleClick={()=>controls()?.commit(38)}
      onKeyDown={event=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
        event.preventDefault();
        const next=event.key==='Home'?38:event.key==='End'?geometry.maximum:Math.max(geometry.minimum,Math.min(geometry.maximum,position+(event.key==='ArrowLeft'?-2:2)));
        controls()?.commit(next);
      }}><span/></div>;
  }
  function SidebarResizeHandle({value=260,onChange,onCollapse}) {
    const ref=useRef(null),drag=useRef(null),dragTarget=useRef(null),frame=useRef(0),epoch=useRef(0);
    const settings=useRef({value,onChange,onCollapse});settings.current={value,onChange,onCollapse};
    const [position,setPosition]=useState(value);
    const target=()=>ref.current?.closest(settings.current.onCollapse ? '.main-sidebar-slot' : '.body');
    const applyStyle=(element,width)=>{
      if(settings.current.onCollapse){
        if(width==null)element?.style.removeProperty('--scheduled-sidebar-drag-width');
        else element?.style.setProperty('--scheduled-sidebar-drag-width',width+'px');
      }else element?.style.setProperty('--workspace-sidebar-width',(width??settings.current.value)+'px');
    };
    useLayoutEffect(()=>{if(drag.current)apply(pointerWidth(drag.current.x));else setPosition(value);},[value]);
    const apply=width=>{
      const next=Math.round(Math.max(200,Math.min(400,width)));
      applyStyle(target(),next);setPosition(next);
      return next;
    };
    const pointerWidth=x=>{
      if(settings.current.onCollapse && drag.current)return drag.current.width + x - drag.current.startX;
      return x-(target()?.getBoundingClientRect().left??0);
    };
    const commit=width=>{
      if(settings.current.onCollapse){
        const next=Math.round(Math.max(200,Math.min(400,width)));
        applyStyle(target(),null);setPosition(next);settings.current.onChange(next);
        return;
      }
      const next=apply(width),current=++epoch.current;
      Promise.resolve().then(()=>settings.current.onChange(next)).then(receipt=>{
        if(current===epoch.current && ref.current && (receipt===null || (receipt?.status && receipt.status!=='applied')))apply(settings.current.value);
      }).catch(()=>{if(current===epoch.current && ref.current)apply(settings.current.value);});
    };
    const finish=(save=true)=>{
      if(!drag.current)return;
      const current=drag.current;cancelAnimationFrame(frame.current);frame.current=0;
      const rawWidth=pointerWidth(current.x);
      const collapse=save && settings.current.onCollapse && rawWidth<=64;
      const width=save && !collapse ? apply(rawWidth) : null;
      drag.current=null;
      dragTarget.current?.classList.remove('sidebar-resizing');dragTarget.current=null;
      if(collapse){
        settings.current.onCollapse();
        applyStyle(target(),null);
      }else if(save && Math.abs(width-current.width)>.5)commit(width);
      else {applyStyle(target(),null);setPosition(settings.current.value);}
      if(ref.current?.hasPointerCapture?.(current.id))ref.current.releasePointerCapture(current.id);
    };
    const handlers=useRef(null);handlers.current={finish};
    useEffect(()=>{
      const end=()=>handlers.current.finish(),cancel=()=>handlers.current.finish(false);
      window.addEventListener('pointerup',end);window.addEventListener('blur',cancel);
      return ()=>{
        window.removeEventListener('pointerup',end);window.removeEventListener('blur',cancel);cancelAnimationFrame(frame.current);
        if(dragTarget.current){dragTarget.current.classList.remove('sidebar-resizing');applyStyle(dragTarget.current,null);}
        drag.current=null;dragTarget.current=null;
      };
    },[]);
    return <div ref={ref} className="sidebar-resizer" role="separator" aria-label={onCollapse?'Resize or collapse Scheduled sidebar':'Resize sidebar'} aria-orientation="vertical" aria-valuemin={onCollapse?0:200} aria-valuemax="400" aria-valuenow={position} aria-valuetext={position?position+' pixels':'Collapsed'} tabIndex="0"
      onPointerDown={event=>{if(event.button!==0)return;event.preventDefault();drag.current={x:event.clientX,startX:event.clientX,width:position,id:event.pointerId};event.currentTarget.setPointerCapture?.(event.pointerId);dragTarget.current=target();dragTarget.current?.classList.add('sidebar-resizing');}}
      onPointerMove={event=>{if(drag.current){drag.current.x=event.clientX;if(!frame.current)frame.current=requestAnimationFrame(()=>{frame.current=0;if(drag.current)apply(pointerWidth(drag.current.x));});}}}
      onPointerUp={event=>{if(drag.current){drag.current.x=event.clientX;finish();}}}
      onPointerCancel={()=>finish(false)} onLostPointerCapture={()=>finish()} onDoubleClick={()=>commit(260)}
      onKeyDown={event=>{
        if(!['ArrowLeft','ArrowRight','Home','End','Enter'].includes(event.key) || event.key==='Enter' && !onCollapse)return;
        event.preventDefault();
        if(onCollapse && (event.key==='Home' || event.key==='Enter' || event.key==='ArrowLeft' && position<=200))onCollapse();
        else commit(event.key==='Home'?260:event.key==='End'?400:position+(event.key==='ArrowLeft'?-16:16));
      }}><span/></div>;
  }
  const assets = 'assets/browser-home/';
  const browserIcons={"close": "X", "plus": "Plus", "pause": "Pause", "restore": "SidebarRight", "expand": "Expand", "more": "DotsHorizontal", "back": "ArrowLeft", "forward": "ArrowRight", "reload": "ArrowRotateCw", "home": "Home", "download": "Download", "search": "Search", "chevron": "ChevronDown", "check": "Check", "settings": "SettingsCog", "globe": "Globe"};
  const Icon = ({name,size=16}) => browserIcons[name]?React.createElement(window.VellumUI.WorkspaceIcon||window.VellumUI.AppIcon,{name:window.VellumUI.WorkspaceIcon?(name==='expand'?'Full':name==='restore'?'Split':browserIcons[name]):browserIcons[name],size}):<span className="browser-glyph" aria-hidden="true" style={{width:size,height:size,maskImage:`url("${assets}icons/${name}.svg")`,WebkitMaskImage:`url("${assets}icons/${name}.svg")`}}/>;
  const BrandIcon = ({engine, size=20}) => engine.mask ? <span className={'browser-brand-icon brand-' + engine.id} aria-hidden="true" style={{width:size, height:size, maskImage:`url("${assets}${engine.icon}")`, WebkitMaskImage:`url("${assets}${engine.icon}")`}}/> : <img className="browser-brand-icon" src={assets + engine.icon} width={size} height={size} alt=""/>;
  const fallbackEngines = [
    {id:'google', name:'Google', wallpaper:'google.png', icon:'google.ico'},
    {id:'brave', name:'Brave', wallpaper:'brave.png', icon:'brave.svg', mask:true},
    {id:'duckduckgo', name:'DuckDuckGo', wallpaper:'duckduckgo.png', icon:'duckduckgo-logo.png'},
    {id:'startpage', name:'Startpage', wallpaper:'startpage.png', icon:'startpage.svg', mask:true},
    {id:'searxng', name:'SearXNG', wallpaper:'searxng.png', icon:'searxng.svg', mask:true},
  ];
  const fallbackPreferences = {search_engine:'google', searxng_url:'', shortcuts:[
    {id:'github', name:'GitHub', url:'https://github.com/'},
    {id:'wikipedia', name:'Wikipedia', url:'https://www.wikipedia.org/'},
    {id:'youtube', name:'YouTube', url:'https://www.youtube.com/'},
  ]};
  function ShortcutIcon({url}) {
    let name = '';
    try {
      const host = new URL(url).hostname.replace(/^www\./, '');
      name = {'github.com':'github', 'wikipedia.org':'wikipedia', 'youtube.com':'youtube'}[host] || '';
    } catch (_) { /* Custom links use the standard link icon. */ }
    return name ? <span className={'browser-shortcut-icon shortcut-' + name} aria-hidden="true" style={{maskImage:`url("${assets}${name}.svg")`, WebkitMaskImage:`url("${assets}${name}.svg")`}}/> : <Icon name="link" size={21}/>;
  }
  function BrowserHome({api, preferences, engine, engines, command}) {
    const [query, setQuery] = useState('');
    const [menu, setMenu] = useState(false);
    const [adding, setAdding] = useState(false);
    const [setup, setSetup] = useState(false);
    const [instance, setInstance] = useState(preferences.searxng_url || '');
    const [name, setName] = useState('');
    const [url, setUrl] = useState('');
    const [error, setError] = useState('');
    const [saving, setSaving] = useState(false);
    const picker = useRef(null);
    const pickerButton = useRef(null);
    const searchInput = useRef(null);
    const menuRef = useRef(null);
    const shortcuts = preferences.shortcuts || [];
    useEffect(() => { setInstance(preferences.searxng_url || ''); }, [preferences.searxng_url]);
    useLayoutEffect(() => {
      if (!menu) return;
      const element = menuRef.current;
      const home = element?.closest('.browser-home');
      if (!home) return;
      const fit = () => {
        const bounds = home.getBoundingClientRect();
        element.style.maxHeight = Math.max(40, bounds.height - 16) + 'px';
        element.style.maxWidth = Math.max(40, bounds.width - 16) + 'px';
        element.style.transform = 'none';
        const rect = element.getBoundingClientRect();
        const x = Math.max(bounds.left + 8 - rect.left, Math.min(0, bounds.right - 8 - rect.right));
        const y = Math.max(bounds.top + 8 - rect.top, Math.min(0, bounds.bottom - 8 - rect.bottom));
        element.style.transform = `translate(${x}px, ${y}px)`;
      };
      fit();
      const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(fit) : null;
      observer?.observe(home);
      observer?.observe(home.querySelector('.browser-home-content'));
      window.addEventListener('resize', fit);
      home.addEventListener('scroll', fit);
      return () => {
        observer?.disconnect();
        window.removeEventListener('resize', fit);
        home.removeEventListener('scroll', fit);
      };
    }, [menu, engine.id, setup, adding, preferences.searxng_url]);
    useEffect(() => {
      if (!menu) return;
      const dismiss = event => { if (!picker.current?.contains(event.target)) setMenu(false); };
      document.addEventListener('pointerdown', dismiss);
      menuRef.current?.querySelector('[aria-checked="true"]')?.focus({preventScroll:true});
      return () => document.removeEventListener('pointerdown', dismiss);
    }, [menu]);
    const savePreferences = async patch => {
      setSaving(true); setError('');
      try { return await command('preferences', patch); }
      finally { setSaving(false); }
    };
    const selectEngine = async selected => {
      setMenu(false); setSetup(false); setError(''); pickerButton.current?.focus({preventScroll:true});
      if (await savePreferences({search_engine:selected.id})) {
        searchInput.current?.focus({preventScroll:true});
        const end = searchInput.current?.value.length || 0;
        searchInput.current?.setSelectionRange(end,end);
      }
    };
    const search = event => {
      event.preventDefault();
      if (!query.trim()) return;
      try { setError(''); command('navigate', {url:api.searchUrl(query, preferences)}); }
      catch (failure) { setError(failure.message); setSetup(engine.id === 'searxng'); }
    };
    const saveInstance = async event => {
      event.preventDefault();
      try {
        api.searchUrl('test', {...preferences, search_engine:'searxng', searxng_url:instance});
        if (await savePreferences({searxng_url:instance.trim()})) setSetup(false);
      } catch (failure) { setError(failure.message); }
    };
    const addShortcut = async event => {
      event.preventDefault();
      try {
        const destination = api.addressUrl(url, preferences);
        const parsed = new URL(destination);
        if (!/^https?:$/.test(parsed.protocol) || parsed.username || parsed.password) throw new Error('Enter a website address without credentials.');
        const id = 'shortcut_' + (window.crypto?.randomUUID?.() || Date.now().toString(36));
        if (await savePreferences({shortcuts:[...shortcuts, {id, name:name.trim(), url:parsed.href}]})) {
          setAdding(false); setName(''); setUrl('');
        }
      } catch (failure) { setError(failure.message); }
    };
    const escape = event => {
      if (event.key !== 'Escape') return;
      event.stopPropagation(); setMenu(false); setAdding(false); setSetup(false);
      pickerButton.current?.focus({preventScroll:true});
    };
    return <section className="browser-home" data-engine={engine.id} aria-label={engine.name + ' homepage'} style={{backgroundImage:`url("${assets}${engine.wallpaper}")`}} onKeyDown={escape}>
      <div className="browser-home-content">
        <div className="browser-home-title">
          {engine.id === 'google' ? <img className="browser-google-wordmark" src={assets + 'google-logo.png'} alt="Google"/> : <h1><BrandIcon engine={engine} size={engine.id === 'duckduckgo' ? 76 : 60}/>{engine.name}</h1>}
          <div ref={picker} className="browser-engine-picker">
            <button ref={pickerButton} className="browser-engine-trigger" aria-label="Choose search engine" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu(!menu)}><Icon name="chevron" size={18}/></button>
            {menu && <div ref={menuRef} className="browser-engine-menu" role="menu" aria-label="Search engine" onKeyDown={event => {
              if (!['ArrowDown','ArrowUp','Home','End'].includes(event.key)) return;
              event.preventDefault();
              const items = Array.from(menuRef.current.querySelectorAll('[role="menuitemradio"]'));
              const index = items.indexOf(document.activeElement);
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length-1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
              items[next]?.focus({preventScroll:true});
            }}>
              {engines.map(item => <button key={item.id} role="menuitemradio" aria-checked={item.id === engine.id} disabled={saving} onClick={() => selectEngine(item)}><BrandIcon engine={item}/><span>{item.name}</span>{item.id === engine.id && <Icon name="check"/>}</button>)}
              <button className="browser-instance-link" role="menuitem" onClick={() => { setMenu(false); setSetup(true); }}><Icon name="settings"/>SearXNG instance</button>
            </div>}
          </div>
        </div>
        <form className="browser-home-search" onSubmit={search}>
          <Icon name="search" size={21}/>
          <input ref={searchInput} aria-label={'Search with ' + engine.name} placeholder={'Search with ' + engine.name} value={query} onChange={event => setQuery(event.target.value)} autoComplete="off" spellCheck={false}/>
          <button type="submit" aria-label={'Submit ' + engine.name + ' search'} disabled={!query.trim()}><Icon name="arrow" size={21}/></button>
        </form>
        <div className="browser-home-shortcuts" aria-label="Homepage shortcuts">
          {shortcuts.map(item => <div className="browser-shortcut-wrap" key={item.id}>
            <button className="browser-shortcut" onClick={() => command('navigate', {url:item.url})}><ShortcutIcon url={item.url}/><span>{item.name}</span></button>
            <button className="browser-shortcut-remove" title={'Remove ' + item.name + ' shortcut'} aria-label={'Remove ' + item.name + ' shortcut'} disabled={saving} onClick={() => savePreferences({shortcuts:shortcuts.filter(shortcut => shortcut.id !== item.id)})}><Icon name="close" size={12}/></button>
          </div>)}
          {shortcuts.length < 12 && <button className="browser-shortcut browser-shortcut-add" aria-expanded={adding} onClick={() => { setAdding(!adding); setSetup(false); setError(''); }}><Icon name="plus" size={22}/><span>Add shortcut</span></button>}
        </div>
        {setup && <form className="browser-home-edit" onSubmit={saveInstance}>
          <label htmlFor="browser-searxng">SearXNG instance</label><p>Use an instance you run or trust.</p>
          <input id="browser-searxng" type="url" required value={instance} placeholder="https://search.example.org" onChange={event => setInstance(event.target.value)}/>
          <div><button type="button" onClick={() => setSetup(false)}>Cancel</button><button type="submit" disabled={saving || !instance.trim()}>Use instance</button></div>
        </form>}
        {adding && <form className="browser-home-edit" onSubmit={addShortcut}>
          <label htmlFor="browser-shortcut-name">Shortcut name</label><input id="browser-shortcut-name" required maxLength={40} value={name} onChange={event => setName(event.target.value)} autoFocus/>
          <label htmlFor="browser-shortcut-url">Website</label><input id="browser-shortcut-url" required maxLength={4096} value={url} placeholder="https://example.com" onChange={event => setUrl(event.target.value)}/>
          <div><button type="button" onClick={() => setAdding(false)}>Cancel</button><button type="submit" disabled={saving || !name.trim() || !url.trim()}>Save shortcut</button></div>
        </form>}
        {error && <p className="browser-home-error" role="alert">{error}</p>}
      </div>
    </section>;
  }

  function BrowserPanel({state, onRefresh, onHide, onCloseTab, context, onReceipt, onSettings, suspended=false, overlayVisible=false, hidden=false, layoutMode='split', onLayoutModeChange, controllerRef, autoFocus=true,sharedTabs=false}) {
    const api = window.VellumApi.browser;
    const native = state.render_transport === 'native';
    const nativeBridge = window.VellumDesktop?.browser;
    const [frame, setFrame] = useState(null);
    const [nativeStill,setNativeStill] = useState('');
    const [localPointer,setLocalPointer]=useState(null);
    const [error, setError] = useState('');
    const [viewError, setViewError] = useState('');
    const [busy, setBusy] = useState(false);
    const [address, setAddress] = useState('');
    const [addressQuery, setAddressQuery] = useState('');
    const [addressOpen, setAddressOpen] = useState(false);
    const [history, setHistory] = useState([]);
    const [completions, setCompletions] = useState({query:'',engine:'',items:[],status:'idle'});
    const [pendingTabs, setPendingTabs] = useState(0);
    const [homeGeneration, setHomeGeneration] = useState(0);
    const [selectedSuggestion, setSelectedSuggestion] = useState(-1);
    const selectedAddressItem = useRef(null);
    const [downloadsOpen, setDownloadsOpen] = useState(false);
    const expanded=layoutMode==='full';
    const [moreOpen, setMoreOpen] = useState(false);
    const screenRef = useRef(null);
    const addressRef = useRef(null);
    const queue = useRef(Promise.resolve());
    const textBuffer = useRef({text:'', tab_id:''});
    const textTimer = useRef(null);
    const wheelBuffer = useRef(0);
    const wheelPoint = useRef(null);
    const wheelTimer = useRef(null);
    const hoverTimer = useRef(null);
    const hoverPending = useRef(null);
    const hoverInFlight = useRef(false);
    const takingOver = useRef(false);
    const editingAddress = useRef(false);
    const focusingBlankAddress = useRef(false);
    const closing = useRef(false);
    const started = useRef(false);
    const [findOpen,setFindOpen]=useState(false);
    const findQuery=useRef('');
    const current = useRef({state, frame});
    current.current = {state, frame, context, suspended};
    const active = state.tabs.find(tab => tab.active);
    const home = pendingTabs > 0 || !state.running || !active || active.url === 'about:blank' && !active.loading;
    const preferences = state.preferences || api.defaultPreferences || fallbackPreferences;
    const engines = api.engines || fallbackEngines;
    const engine = engines.find(item => item.id === preferences.search_engine) || engines[0];
    const displayAddress = url => {
      if (!url || url === 'about:blank') return '';
      if (preferences.show_full_url !== false) return url;
      try { return new URL(url).host; } catch (_) { return url; }
    };
    const queries = completions.query === addressQuery && completions.engine === engine.id && preferences.suggestions_enabled !== false ? completions.items : [];
    const suggestions = addressQuery.trim() ? api.addressSuggestions?.(addressQuery, state.tabs, preferences.shortcuts, history, preferences, queries) || [] : [];
    selectedAddressItem.current = suggestions[selectedSuggestion] || null;
    useEffect(() => {
      if (!addressOpen || !addressQuery.trim() || !api.suggestions) return;
      let alive = true;
      const timer = setTimeout(() => {
        api.suggestions(addressQuery).then(result => {
          if (!alive) return;
          const items = result.items || [];
          const selected = selectedAddressItem.current;
          const remote = result.search_engine === engine.id ? result.queries || [] : [];
          const next = api.addressSuggestions?.(addressQuery, state.tabs, preferences.shortcuts, items, preferences, remote) || [];
          setHistory(items);
          setCompletions({query:addressQuery,engine:result.search_engine,items:remote,status:result.suggestion_status});
          setSelectedSuggestion(selected ? next.findIndex(item => item.url === selected.url && item.kind === selected.kind) : -1);
        }).catch(() => { if (alive) { setHistory([]); setSelectedSuggestion(-1); } });
      }, addressQuery ? 80 : 0);
      return () => { alive = false; clearTimeout(timer); };
    }, [addressOpen, addressQuery, engine.id, preferences.suggestions_enabled]);
    const manual = state.control === 'user';
    const focusAddress = (empty=false) => {
      if (native) nativeBridge?.mount({focus_chrome:true}).catch(()=>{});
      if (empty) setAddress('');
      editingAddress.current = true;
      focusingBlankAddress.current = empty;
      addressRef.current?.focus({preventScroll:true});
      focusingBlankAddress.current = false;
      if (!empty) addressRef.current?.select();
      setAddressQuery(empty ? '' : addressRef.current?.value || '');
      setAddressOpen(false); setSelectedSuggestion(-1);
    };
    const closeWindow = () => {
      if (closing.current) return;
      closing.current = true;
      onHide();
      command('close');
    };
    const closeTab = tabId => {
      if(sharedTabs&&onCloseTab)return onCloseTab(tabId);
      if (current.current.state.tabs.length <= 1 && pendingTabs === 0) closeWindow();
      else command('close_tab', {tab_id:tabId});
    };
    const newTab = () => {
      setPendingTabs(count => count + 1);
      setHomeGeneration(count => count + 1);
      focusAddress(true);
      command('new_tab').finally(() => setPendingTabs(count => Math.max(0,count - 1)));
    };
    useEffect(()=>{setFindOpen(false);findQuery.current='';},[state.active_tab_id]);
    const shortcut = event => window.VellumCommands?.runtime?.dispatch(event,{browser:true,native:!home&&!!event.target?.closest?.('.browser-screen')});
    useEffect(() => {
      if (!editingAddress.current) setAddress(displayAddress(active?.url));
    }, [active?.url, active?.id, preferences.show_full_url]);
    useEffect(() => {
      if (home || native) { setFrame(null); setViewError(''); return; }
      if(suspended)return;
      let cancelled = false, timer, reconnect, stopStream, streaming = false, lastStreamFrame = 0;
      const display = next => {
        if (cancelled || next.tab_id !== current.current.state.active_tab_id) return;
        current.current.frame = next;
        setFrame(next);
        setViewError('');
      };
      const connect = () => {
        if (cancelled || document.hidden || !state.running || !state.active_tab_id || !api.stream) return;
        stopStream?.();
        const retry = () => {
          streaming = false;
          clearTimeout(reconnect);
          if (!cancelled) reconnect = setTimeout(connect, 1500);
        };
        try { stopStream = api.stream(next => { streaming = true; lastStreamFrame = Date.now(); display(next); }, retry); }
        catch (_) { retry(); } // HTTP frames remain available if sockets are blocked.
      };
      const refresh = async () => {
        // An idle socket and a stalled socket both stop sending pixels. Sample
        // HTTP frames after a quiet interval so pointer-only changes still arrive.
        if (!cancelled && (!streaming || Date.now() - lastStreamFrame > 1200) && state.running && state.active_tab_id && !document.hidden) {
          try {
            const next = await api.frame();
            display(next);
          } catch (failure) {
            if (!cancelled) setViewError(current.current.state.tabs.find(tab => tab.active)?.loading ? '' : failure.message);
          }
        } else if (!state.running || !state.active_tab_id) setFrame(null);
        if (!cancelled) timer = setTimeout(refresh, streaming ? 1000 : 200);
      };
      const visibility = () => {
        stopStream?.(); streaming = false; clearTimeout(reconnect);
        if (!document.hidden) connect();
      };
      connect();
      refresh();
      document.addEventListener('visibilitychange', visibility);
      return () => { cancelled = true; clearTimeout(timer); clearTimeout(reconnect); stopStream?.(); document.removeEventListener('visibilitychange', visibility); };
    }, [state.session_id, state.running, state.active_tab_id, home, native, suspended]);

    const nativeMountQueue=useRef(Promise.resolve());
    useEffect(() => {
      if (!native || !nativeBridge || !screenRef.current) return;
      let cancelled=false,frame=0,inFlight=false,dirty=false,lastMounted='';
      const body=screenRef.current.closest('.body'),region=screenRef.current.closest('.workspace-split'),panel=screenRef.current.closest('.browser-panel');
      const sidebar=body?.querySelector(':scope > .main-sidebar-slot');
      const mountNative=request=>{
        const result=nativeMountQueue.current.catch(()=>{}).then(()=>cancelled || !screenRef.current?.isConnected ? undefined : nativeBridge.mount(request));
        nativeMountQueue.current=result;
        return result;
      };
      const update=()=>{
        dirty=true;
        if(!cancelled && !inFlight && !frame)frame=requestAnimationFrame(flush);
      };
      const flush=async()=>{
        frame=0;if(cancelled || !dirty)return;
        if(!screenRef.current?.isConnected)return;
        dirty=false;inFlight=true;
        const rect=screenRef.current.getBoundingClientRect();
        const navigation=sidebar?.querySelector('.sidebar'),slot=sidebar?.getBoundingClientRect();
        const navigationOverlay=sidebar?.dataset.state==='open' && slot?.width<1 && navigation && rect.x<slot.x+navigation.offsetWidth;
        // Resizing is a bounds change, not a visibility change. Keep the native
        // WebContentsView mounted; transient menus still use the existing still.
        const composerOverlay=[...document.querySelectorAll('[data-composer-popup], [data-shell-overlay], .workspace-details')].some(node=>{
          if(node.getAttribute('aria-hidden')==='true')return false;
          const popup=node.getBoundingClientRect();
          return popup.width>0 && popup.height>0 && popup.left<rect.right && popup.right>rect.left && popup.top<rect.bottom && popup.bottom>rect.top;
        });
        const visible=Boolean(state.running && !home && !document.hidden && !suspended && !overlayVisible && !navigationOverlay && !composerOverlay && !moreOpen && !downloadsOpen && !(addressOpen && suggestions.length) && rect.width>0 && rect.height>0);
        const bounds={x:rect.x,y:rect.y,width:rect.width,height:rect.height};
        const identity=JSON.stringify({visible,target_id:state.native_target_id,...(visible?bounds:{})});
        try {
          if(identity===lastMounted)return;
          if (!visible && !home && !suspended && !document.hidden) {
            const result=await mountNative({prepare_only:true,target_id:state.native_target_id});
            if(cancelled)return;
            if(result?.still) {
              const image=new Image();image.src=result.still;
              await image.decode?.().catch(()=>{});
              if(cancelled)return;
              setNativeStill(result.still);
              await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
            }
          }
          if(cancelled)return;
          await mountNative({visible,target_id:state.native_target_id,bounds});
          lastMounted=identity;
          if (!cancelled && visible) setNativeStill('');
        } catch(failure) {if(!cancelled)setViewError(failure.message);}
        finally {inFlight=false;if(dirty && !cancelled)update();}
      };
      const observer=typeof ResizeObserver==='undefined' ? null : new ResizeObserver(update);
      observer?.observe(screenRef.current);
      if(sidebar)observer?.observe(sidebar);
      const layoutObserver=typeof MutationObserver==='undefined' ? null : new MutationObserver(update);
      if(body)layoutObserver?.observe(body,{attributes:true,attributeFilter:['class']});
      if(region?.parentElement)layoutObserver?.observe(region.parentElement,{childList:true});
      if(region)layoutObserver?.observe(region,{attributes:true,attributeFilter:['class','style','data-split-mode']});
      if(panel)layoutObserver?.observe(panel,{attributes:true,attributeFilter:['class']});
      if(sidebar)layoutObserver?.observe(sidebar,{attributes:true,attributeFilter:['data-state','data-pinned','data-peeking']});
      window.addEventListener('resize',update);
      window.addEventListener('vellum:composer-popup',update);
      window.addEventListener('vellum:shell-overlay',update);
      document.addEventListener('visibilitychange',update);
      update();
      return ()=>{cancelled=true;cancelAnimationFrame(frame);observer?.disconnect();layoutObserver?.disconnect();window.removeEventListener('resize',update);window.removeEventListener('vellum:composer-popup',update);window.removeEventListener('vellum:shell-overlay',update);document.removeEventListener('visibilitychange',update);};
    }, [native,state.running,state.native_target_id,home,expanded,suspended,overlayVisible,moreOpen,downloadsOpen,addressOpen,suggestions.length]);
    useEffect(()=>()=>{if(native)nativeBridge?.mount({visible:false}).catch(()=>{});},[native,nativeBridge]);

    useEffect(()=>{
      if (!native || !nativeBridge) return;
      return nativeBridge.subscribe(event=>{
        if(current.current.suspended)return;
        if (event.type==='take_over') { if (current.current.state.control==='agent') command('take_over'); return; }
        if(event.type==='command'){window.VellumCommands?.runtime?.dispatch({...event.input,preventDefault(){},stopPropagation(){}},{native:true,browser:true});return;}
        if (event.type!=='shortcut') return;
        if (event.command==='address') focusAddress();
        else if (event.command==='new_tab') newTab();
        else if (event.command==='close_tab') closeTab(current.current.state.active_tab_id);
        else command(event.command);
      });
    },[native]);

    useEffect(() => {
      if (native || !state.running || !state.active_tab_id || !screenRef.current || typeof ResizeObserver === 'undefined') return;
      let timer, last = '';
      const resize = () => {
        const rect = screenRef.current.getBoundingClientRect();
        if (rect.width < 240 || rect.height < 160) return;
        const size = api.viewport(rect);
        const identity = size.width + ':' + size.height;
        if (last === identity) return;
        last = identity;
        command('resize', {...size, tab_id:state.active_tab_id});
      };
      const observer = new ResizeObserver(() => { clearTimeout(timer); timer = setTimeout(resize, 120); });
      observer.observe(screenRef.current);
      resize();
      return () => { clearTimeout(timer); observer.disconnect(); };
    }, [state.session_id, state.running, state.active_tab_id, native]);
    useEffect(() => () => { clearTimeout(textTimer.current); clearTimeout(wheelTimer.current); clearTimeout(hoverTimer.current); hoverPending.current = null; }, []);
    useEffect(() => { clearTimeout(hoverTimer.current); hoverTimer.current = null; hoverPending.current = null; }, [state.active_tab_id, state.running]);
    useEffect(() => {
      const screen = screenRef.current;
      const wheel = event => { if (current.current.state.control === 'user' && current.current.state.tabs.find(tab => tab.active)?.url !== 'about:blank') event.preventDefault(); };
      screen?.addEventListener('wheel', wheel, {passive:false});
      return () => screen?.removeEventListener('wheel', wheel);
    }, []);

    const flushText = () => {
      clearTimeout(textTimer.current);
      textTimer.current = null;
      const pending = textBuffer.current;
      textBuffer.current = {text:'', tab_id:''};
      if (pending.text) command('type', {text:pending.text}, pending.tab_id);
    };

    const command = (operation, arguments_={}, targetTab=current.current.state.active_tab_id) => {
      if (closing.current && operation !== 'close') return Promise.resolve(false);
      if (operation !== 'hover') {
        clearTimeout(hoverTimer.current); hoverTimer.current = null; hoverPending.current = null;
      }
      if (!['type','hover'].includes(operation)) flushText();
      if (!['scroll','type','press','hover'].includes(operation)) {
        clearTimeout(wheelTimer.current); wheelTimer.current = null; wheelBuffer.current = 0;
      }
      const input = ['click','type','press','scroll','hover'].includes(operation);
      const work = async () => {
        if (closing.current && operation !== 'close') return false;
        if (!input && operation !== 'resize') setBusy(true);
        try {
          if (operation === 'hover' && (targetTab !== current.current.state.active_tab_id || arguments_.frame_id !== current.current.frame?.frame_id)) return false;
          if (input && targetTab !== current.current.state.active_tab_id) throw new Error('The active tab changed. Click the current page before typing.');
          let payload = {operation, ...arguments_};
          if (!current.current.state.running && ['navigate','new_tab','reopen_tab'].includes(operation)) {
            const opened = await api.control({operation:'open'}, current.current.context);
            onReceipt?.(opened);
            const status = await onRefresh();
            if (status) current.current.state = status;
          }
          if (closing.current && operation !== 'close') return false;
          const takeControl = operation === 'click' && current.current.state.control !== 'user';
          if (takeControl) payload.take_control = true;
          if (input && !payload.frame_id) {
            // Revalidate ownership and document identity on the server for each input.
            payload.frame_id = current.current.frame?.frame_id || '';
          }
          const receipt = await api.control(payload, current.current.context);
          if (operation !== 'hover') onReceipt?.(receipt);
          setError('');
          if (!input || takeControl) {
            const status = await onRefresh();
            if (status) current.current.state = status;
          }
          return true;
        } catch (failure) { if (operation !== 'hover') setError(failure.message); }
        finally { if (!input && operation !== 'resize') setBusy(false); if (operation === 'click') takingOver.current = false; }
      };
      queue.current = queue.current.then(work, work);
      return queue.current;
    };
    useEffect(() => {
      if (autoFocus && !suspended && !started.current && state.available) {
        started.current = true;
        if (home) focusAddress(true);
      }
    }, [state.available,autoFocus,suspended]);
    useLayoutEffect(()=>{
      if(!controllerRef)return;
      controllerRef.current={command,focusAddress,newTab,closeTab,openFind:()=>setFindOpen(true),isFinding:()=>findOpen,findNext:forward=>command('find',{text:findQuery.current,find_next:true,forward}),prepareHide:()=>{
        flushText();clearTimeout(hoverTimer.current);hoverPending.current=null;
      }};
      return()=>{controllerRef.current=null;};
    });
    const sendHover = () => {
      hoverTimer.current = null;
      const pending = hoverPending.current;
      if (!pending || hoverInFlight.current) return;
      hoverPending.current = null;
      hoverInFlight.current = true;
      command('hover', pending.arguments, pending.tab_id).finally(() => {
        hoverInFlight.current = false;
        if (hoverPending.current && !hoverTimer.current) hoverTimer.current = setTimeout(sendHover, 50);
      });
    };
    const hover = event => {
      const bounds=event.currentTarget.getBoundingClientRect();
      setLocalPointer({x:event.clientX-bounds.left,y:event.clientY-bounds.top});
      if (home || !state.running || !frame || frame.tab_id !== state.active_tab_id || event.buttons) return;
      const point = api.point(event.currentTarget.getBoundingClientRect(), frame, event.clientX, event.clientY);
      if (!point) return;
      hoverPending.current = {arguments:{...point, frame_id:frame.frame_id}, tab_id:state.active_tab_id};
      if (!hoverTimer.current && !hoverInFlight.current) hoverTimer.current = setTimeout(sendHover, 50);
    };
    const navigate = event => {
      event.preventDefault();
      const selected = addressOpen && suggestions[selectedSuggestion];
      if (selected) { chooseSuggestion(selected); return; }
      const input = address.trim();
      if (!input) return;
      editingAddress.current = false;
      setAddressOpen(false);
      try { const url = api.addressUrl(input, preferences); command('navigate', {url}); }
      catch (failure) { setError(failure.message); }
    };
    const chooseSuggestion = item => {
      editingAddress.current = false;
      setAddress(item.url); setAddressQuery(item.url); setAddressOpen(false); setSelectedSuggestion(-1);
      addressRef.current?.blur();
      if (item.kind === 'tab') command('select_tab', {tab_id:item.tab_id});
      else command('navigate', {url:item.url});
    };
    const changeAddress = event => {
      const value = event.target.value;
      setAddressQuery(value); setAddressOpen(Boolean(value.trim())); setSelectedSuggestion(-1);
      const matches = api.addressSuggestions?.(value, state.tabs, preferences.shortcuts, history, preferences) || [];
      const deletion = event.nativeEvent.inputType?.startsWith('delete');
      const match = !deletion && !event.nativeEvent.isComposing && value && !/\s/.test(value) && event.target.selectionStart === value.length
        ? matches.find(item => !['search','query'].includes(item.kind) && (item.url.toLowerCase().startsWith(value.toLowerCase()) || item.url.replace(/^https?:\/\/(?:www\.)?/i,'').toLowerCase().startsWith(value.toLowerCase()))) : null;
      const completed = match ? (match.url.toLowerCase().startsWith(value.toLowerCase()) ? match.url : match.url.replace(/^https?:\/\/(?:www\.)?/i,'')) : value;
      setAddress(completed);
      if (match && completed.length > value.length) {
        setSelectedSuggestion(matches.indexOf(match));
        requestAnimationFrame(() => {
          if (addressRef.current?.value === completed && document.activeElement === addressRef.current) addressRef.current.setSelectionRange(value.length,completed.length);
        });
      }
    };
    const addressKeyDown = event => {
      if (event.nativeEvent.isComposing) return;
      if (['ArrowDown','ArrowUp'].includes(event.key) && suggestions.length) {
        event.preventDefault(); event.stopPropagation(); setAddressOpen(true);
        const next = event.key === 'ArrowDown' ? (selectedSuggestion + 1) % suggestions.length : (selectedSuggestion < 0 ? suggestions.length - 1 : (selectedSuggestion - 1 + suggestions.length) % suggestions.length);
        setSelectedSuggestion(next);
        requestAnimationFrame(() => document.getElementById('browser-suggestion-' + next)?.scrollIntoView?.({block:'nearest'}));
      } else if (event.key === 'Enter' && addressOpen && suggestions[selectedSuggestion]) {
        event.preventDefault(); event.stopPropagation(); chooseSuggestion(suggestions[selectedSuggestion]);
      } else if (event.key === 'Escape' && addressOpen) {
        event.preventDefault(); event.stopPropagation(); setAddress(addressQuery); setAddressOpen(false); setSelectedSuggestion(-1);
      }
    };
    const click = event => {
      if (home || !state.running || !frame || frame.tab_id !== state.active_tab_id || event.button !== 0) return;
      event.preventDefault();
      const point = api.point(event.currentTarget.getBoundingClientRect(), frame, event.clientX, event.clientY);
      if (point) { takingOver.current = true; command('click', {...point, frame_id:frame.frame_id}); }
      event.currentTarget.focus({preventScroll:true});
    };
    const keyDown = event => {
      if (home || !(current.current.state.control === 'user' || takingOver.current) || event.nativeEvent?.isComposing) return;
      if (['Shift','Control','Alt','Meta','Dead','Process','Unidentified'].includes(event.key)) return;
      if (event.ctrlKey && event.key.toLowerCase() === 'v') return; // Paste is explicit below.
      if (event.key === 'Tab') return; // Keep app focus navigation accessible.
      event.stopPropagation();
      if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        if (textBuffer.current.tab_id && textBuffer.current.tab_id !== current.current.state.active_tab_id) flushText();
        textBuffer.current.tab_id = current.current.state.active_tab_id;
        textBuffer.current.text += event.key;
        if (textBuffer.current.text.length >= 10000) flushText();
        else if (!textTimer.current) textTimer.current = setTimeout(flushText, 35);
      } else {
        event.preventDefault();
        const modifiers = [event.ctrlKey && 'Control', event.metaKey && 'Meta', event.altKey && 'Alt', event.shiftKey && 'Shift'].filter(Boolean);
        command('press', {key:[...modifiers, event.key === ' ' ? 'Space' : event.key].join('+')});
      }
    };
    const transfers=state.downloads||[],activeTransfers=transfers.filter(file=>file.state==='downloading'),known=activeTransfers.length>0&&activeTransfers.every(file=>file.total_bytes>0),totalBytes=activeTransfers.reduce((sum,file)=>sum+(file.total_bytes||0),0),received=activeTransfers.reduce((sum,file)=>sum+(file.received_bytes||0),0),percent=known?Math.min(100,Math.round(received/totalBytes*100)):null;
    const allPaused=activeTransfers.length>0&&activeTransfers.every(file=>file.paused),attention=transfers.filter(file=>!file.acknowledged&&['failed','saved'].includes(file.state)).sort((a,b)=>Number(b.state==='failed')-Number(a.state==='failed'))[0];
    const toggleDownloads=()=>{setDownloadsOpen(!downloadsOpen);setMoreOpen(false);if(!downloadsOpen)command('ack_downloads');};
    const downloadLabel=activeTransfers.length?(allPaused?'Downloads paused':known?'Downloading · '+percent+'%':'Downloads in progress'):attention?.state==='failed'?'Download failed':attention?'Download complete':'Downloads';
    return <aside hidden={hidden} inert={hidden?'':undefined} className={'browser-panel' + (expanded ? ' browser-expanded' : '')} aria-label="Vellum browser" data-ui-reference="browser-panel" data-shared-tabs={sharedTabs}
      onKeyDownCapture={shortcut} onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); setDownloadsOpen(false); setMoreOpen(false); } }}>
      <header className="browser-heading">
        <span className="browser-brand" title={native ? 'Vellum embedded Chromium browser' : 'Dedicated Brave session on this device'}>{native ? <Icon name="globe" size={20}/> : <BrandIcon engine={engines[1]} size={20}/>}</span>
        <div className="browser-tabs" role="tablist" aria-label="Browser tabs">
          {state.tabs.map(tab => <div key={tab.id} className={'browser-tab' + (tab.active ? ' active' : '')}>
            <button role="tab" aria-selected={tab.active && !pendingTabs} aria-busy={tab.loading || undefined} onClick={() => command('select_tab', {tab_id:tab.id})} title={tab.url}>{tab.url === 'about:blank' ? <BrandIcon engine={engine} size={15}/> : <Icon name="globe" size={15}/>}<span>{tab.title}</span></button>
            <button className="browser-icon" aria-label={'Close ' + tab.title} aria-keyshortcuts={tab.active ? 'Alt+W' : undefined} onClick={() => closeTab(tab.id)}><Icon name="close" size={12}/></button>
          </div>)}
          {(!state.tabs.length || pendingTabs > 0) && <div className="browser-tab active"><button role="tab" aria-selected="true" aria-busy={pendingTabs > 0 || undefined}><BrandIcon engine={engine} size={15}/><span>New tab{pendingTabs > 1 ? ' · ' + pendingTabs : ''}</span></button>{!pendingTabs && <button className="browser-icon" aria-label="Close New tab" onClick={closeWindow}><Icon name="close" size={12}/></button>}</div>}
          <button className="browser-icon" title="New tab" aria-keyshortcuts="Alt+T" onClick={newTab}><Icon name="plus"/></button>
        </div>
        <div className="browser-heading-actions">
          <span className="browser-status" title={state.control === 'user' ? 'You have control' : state.control === 'agent' ? 'Agent can browse' : state.running ? 'Paused' : 'Starting Brave'}><i className={state.control === 'agent' ? 'live' : ''}/>{state.control === 'user' ? 'Your turn' : state.control === 'agent' ? 'Ready' : state.running ? 'Paused' : 'Starting…'}</span>
          {state.running ? <>
            <button className="browser-button" title={state.control === 'agent' ? 'Pause agent' : 'Resume agent'} onClick={() => command(state.control === 'agent' ? 'pause' : 'resume')} disabled={busy}>{state.control === 'agent' ? <Icon name="pause"/> : 'Resume'}</button>
            {state.control !== 'user' && <button className="browser-button secondary" onClick={() => command('take_over')} disabled={busy}>Take over</button>}
          </> : null}
          <button className="browser-icon" title={expanded ? 'Restore split view' : 'Expand browser'} aria-pressed={expanded} onClick={() => onLayoutModeChange?.(expanded?'split':'full')}><Icon name={expanded ? 'restore' : 'expand'}/></button>
          <button className="browser-icon" title="Browser menu" aria-expanded={moreOpen} onClick={() => { setMoreOpen(!moreOpen); setDownloadsOpen(false); }}><Icon name="more"/></button>
          <button className="browser-icon" title="Hide tabs" aria-label="Hide browser tabs" onClick={onHide}><Icon name="close"/></button>
        </div>
      </header>
      <>
        <form className="browser-address-row" onSubmit={navigate}>
          <button type="button" className="browser-icon" title="Back" onClick={() => command('back')} disabled={!active || busy}><Icon name="back"/></button>
          <button type="button" className="browser-icon" title="Forward" onClick={() => command('forward')} disabled={!active || busy}><Icon name="forward"/></button>
          <button type="button" className="browser-icon" title="Reload" onClick={() => command('reload')} disabled={!active || busy}><Icon name="reload"/></button>
          <button type="button" className="browser-icon" title="Home" onClick={() => command('navigate', {url:'about:blank'})}><Icon name="home"/></button>
          <div className="browser-omnibox-wrap">
            <label className="browser-omnibox"><BrandIcon engine={engine} size={16}/><input ref={addressRef} aria-label="Browser address" aria-keyshortcuts="Alt+L" role="combobox" aria-autocomplete="both" aria-expanded={addressOpen && suggestions.length > 0} aria-controls="browser-address-suggestions" aria-activedescendant={addressOpen && selectedSuggestion >= 0 ? 'browser-suggestion-' + selectedSuggestion : undefined} autoComplete="off" placeholder={'Search ' + engine.name + ' or enter address'} value={address} onFocus={() => { editingAddress.current = true; if (!focusingBlankAddress.current && address === displayAddress(active?.url)) setAddress(active?.url === 'about:blank' ? '' : active?.url || ''); setAddressQuery(addressRef.current?.value || ''); setAddressOpen(false); setSelectedSuggestion(-1); addressRef.current?.select(); }} onBlur={() => { editingAddress.current = false; setAddressOpen(false); if (!address.trim() || address === active?.url) setAddress(displayAddress(active?.url)); }} onChange={changeAddress} onKeyDown={addressKeyDown} spellCheck={false}/></label>
            {addressOpen && suggestions.length > 0 && <div className="browser-suggestions" id="browser-address-suggestions" role="listbox" aria-label="Address suggestions">
              {suggestions.map((item,index) => <button type="button" className="browser-suggestion" id={'browser-suggestion-' + index} key={item.kind + ':' + item.url} role="option" aria-selected={index === selectedSuggestion} onPointerDown={event => event.preventDefault()} onClick={() => chooseSuggestion(item)}>
                {['search','query'].includes(item.kind) ? <Icon name="search" size={16}/> : <ShortcutIcon url={item.url}/>}
                <span className="browser-suggestion-copy"><span>{item.title}</span>{!['search','query'].includes(item.kind) && <small>{item.url.replace(/^https?:\/\//i,'')}</small>}</span>
                <span className="browser-suggestion-hint">{item.kind === 'tab' ? 'Switch to tab' : item.kind === 'search' ? 'Search ' + engine.name : item.kind === 'query' ? engine.name : item.kind === 'history' ? 'History' : item.kind === 'website' ? 'Website' : 'Shortcut'}</span>
              </button>)}
              {completions.query === addressQuery && completions.engine === engine.id && completions.status === 'unavailable' && <small className="browser-suggestions-status" role="status">{engine.name} suggestions unavailable</small>}
            </div>}
          </div>
          <button type="button" title={downloadLabel} aria-label={downloadLabel} className="browser-icon browser-download-indicator" aria-expanded={downloadsOpen} data-attention={attention?.state} data-paused={allPaused} onClick={toggleDownloads}><Icon name={allPaused?'pause':'download'}/>{!!activeTransfers.length&&<progress aria-hidden="true" max="100" value={percent===null?undefined:percent}/>}</button>
        </form>
      </>
      {moreOpen && <section className="browser-session-menu" aria-label="Browser options"><strong>{preferences.profiles?.find(profile => profile.id===preferences.active_profile_id)?.name || 'Browser'}</strong>
        {state.features?.find&&<button type="button" className="browser-menu-row" onClick={()=>{setFindOpen(true);setMoreOpen(false);}}><Icon name="search"/>Find in page</button>}
        {state.features?.zoom&&<div className="browser-zoom-controls"><span>Zoom</span><button type="button" aria-label="Zoom out" disabled={state.zoom_factor<=0.25} onClick={()=>command('zoom',{zoom_factor:Math.max(0.25,(state.zoom_factor||1)-0.1)})}><window.VellumUI.WorkspaceIcon name="Minus" size={14}/></button><button type="button" aria-label="Reset zoom" onClick={()=>command('zoom',{zoom_factor:1})}>{Math.round((state.zoom_factor||1)*100)}%</button><button type="button" aria-label="Zoom in" disabled={state.zoom_factor>=3} onClick={()=>command('zoom',{zoom_factor:Math.min(3,(state.zoom_factor||1)+0.1)})}><window.VellumUI.AppIcon name="Plus" size={14}/></button></div>}
        {state.features?.print&&<button type="button" className="browser-menu-row" onClick={()=>{setMoreOpen(false);command('print');}}>Print…</button>}
        <button type="button" className="browser-menu-row" onClick={()=>{setMoreOpen(false);setDownloadsOpen(true);command('ack_downloads');}}><Icon name="download"/>Downloads</button>
        <button type="button" className="browser-menu-row" onClick={()=>{setMoreOpen(false);onSettings?.();}}><Icon name="settings"/>History and browser settings</button>
        <label className="browser-menu-row"><input type="checkbox" checked={preferences.suggestions_enabled !== false} onChange={event => command('preferences', {suggestions_enabled:event.target.checked})}/>Search suggestions</label><p>Suggestions use {engine.name}.</p>
        <button type="button" className="browser-menu-row" onClick={closeWindow}><Icon name="close"/>Close session</button>
      </section>}
      {attention&&!downloadsOpen&&<button type="button" className="browser-download-peek" role="status" onClick={toggleDownloads}><Icon name="download"/><span>{attention.state==='failed'?'Download failed':'Downloaded'}<strong>{attention.name}</strong></span></button>}
      {downloadsOpen && <section className="browser-downloads" aria-label="Browser downloads">
        <div className="browser-downloads-head"><strong>Downloads</strong><button className="browser-icon" title="Close downloads" onClick={() => setDownloadsOpen(false)}><Icon name="close"/></button></div>
        {state.downloads.length ? state.downloads.map(file => <div className="browser-download" key={file.id}>
          <Icon name="download"/><div><span>{file.name}</span><small>{file.state==='saved'?Math.max(1,Math.round(file.size/1024))+' KB · Saved':file.state==='awaiting_approval'?'Needs approval in Browser settings':file.state==='blocked'?'Blocked by download permissions':file.state==='failed'?'Download failed':file.state==='cancelled'?'Cancelled':file.paused?'Paused':file.total_bytes?Math.round(file.received_bytes/file.total_bytes*100)+'% · Downloading':'Downloading…'}</small>{file.state==='downloading'&&<progress aria-label={'Download progress: '+file.name} max={file.total_bytes||undefined} value={file.total_bytes?file.received_bytes:undefined}/>}</div>
          {state.features?.download_controls&&file.state==='downloading'&&<button type="button" className="browser-link" onClick={()=>command(file.paused?'resume_download':'pause_download',{download_id:file.id})}>{file.paused?'Resume':'Pause'}</button>}
          {state.features?.download_controls&&['downloading','awaiting_approval'].includes(file.state)&&<button type="button" className="browser-link" onClick={()=>command('cancel_download',{download_id:file.id})}>Cancel</button>}
          {file.state === 'saved' && <button className="browser-link" onClick={() => command('show_download', {download_id:file.id})}>Show in folder</button>}
        </div>) : <p>No downloads in this session.</p>}
      </section>}
      {(error || viewError || active?.error) && <div className="browser-error" role="alert">{error || viewError || active.error}<button className="browser-link" onClick={() => onRefresh()}>Refresh</button></div>}
      {findOpen&&<div className="browser-find-row"><window.VellumUI.SurfaceFind label="Find in browser page" onFind={(text,find_next,forward)=>{findQuery.current=text;command('find',{text,find_next,forward});}} onClose={()=>{setFindOpen(false);command('find',{text:''});}}/></div>}
      <div ref={screenRef} className={'browser-screen' + (manual ? ' manual' : '') + (home ? ' browser-screen-home' : '')} tabIndex={state.running && !home && !native ? 0 : -1} role="region" aria-label={home ? 'Browser homepage' : native ? 'Embedded browser page' : manual ? 'Browser page. Click to focus a field, then type. Tab leaves the preview.' : 'Live browser page. Click to take control.'}
        onPointerDown={click} onPointerMove={hover} onPointerLeave={() => {
          setLocalPointer(null);
          clearTimeout(hoverTimer.current); hoverTimer.current = null; hoverPending.current = null;
          if (!home && frame && frame.tab_id === state.active_tab_id) command('hover', {x:0,y:0,frame_id:frame.frame_id});
        }} onKeyDown={keyDown} onWheel={event => {
          if (home || !manual || !frame || frame.tab_id !== state.active_tab_id) return;
          wheelPoint.current = api.point(event.currentTarget.getBoundingClientRect(), frame, event.clientX, event.clientY);
          if (!wheelPoint.current) return;
          wheelBuffer.current += event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? screenRef.current.clientHeight : 1);
          if (!wheelTimer.current) wheelTimer.current = setTimeout(() => {
            const delta = Math.max(-2000, Math.min(2000, Math.round(wheelBuffer.current)));
            wheelBuffer.current = 0; wheelTimer.current = null;
            command('scroll', {delta, ...wheelPoint.current});
          }, 32);
        }}
        onPaste={event => { if (!home && manual) { event.preventDefault(); flushText(); command('type', {text:event.clipboardData.getData('text/plain').slice(0,10000)}); } }}
        onCompositionEnd={event => { if (!home && manual && event.data) { flushText(); command('type', {text:event.data}); } }}>
        {home ? <BrowserHome key={homeGeneration} api={api} preferences={preferences} engine={engine} engines={engines} command={command}/> : native ? <div className="browser-native-surface" aria-label="Embedded browser page">{nativeStill && <img src={nativeStill} alt="Page beneath browser menu" draggable={false}/>} {!nativeBridge && <p>Open Vellum desktop to use this browser session.</p>}</div> : frame && state.running && frame.tab_id === state.active_tab_id ? <img src={frame.data_url} alt="Live view of the dedicated browser tab" draggable={false}/> : <div className="browser-empty"><Icon name="globe" size={32}/><h2>{active?.loading ? 'Loading page…' : 'Your browser is ready'}</h2><p>{state.reason || (active?.loading ? 'You can open another tab while this site loads.' : 'Enter a website above or ask Vellum to browse.')}</p></div>}
        {localPointer && (manual || home) && preferences.cursor_style && preferences.cursor_style!=='classic' && <div className="browser-local-pointer" aria-hidden="true" style={{left:localPointer.x-(preferences.cursor_hotspot_x||0),top:localPointer.y-(preferences.cursor_hotspot_y||0)}}><BrowserCursorGraphic preferences={preferences}/></div>}
        {!home && state.control==='agent' && frame?.pointer?.tab_id===state.active_tab_id && (()=>{const layout=pointerLayout(frame,screenRef.current?.clientWidth || frame.width,screenRef.current?.clientHeight || frame.height,preferences);return <div className="browser-agent-pointer-layer" role="img" aria-label={'Agent cursor: '+frame.pointer.action} style={{width:layout.width,height:layout.height}}><div className="browser-agent-pointer" style={{left:layout.x,top:layout.y}}><BrowserCursorGraphic preferences={preferences}/><span>{frame.pointer.action==='click'?'Click':frame.pointer.action==='type'?'Type':frame.pointer.action==='scroll'?'Scroll':'Agent'}</span></div></div>;})()}
      </div>
    </aside>;
  }
  window.VellumUI = window.VellumUI || {};
  window.VellumUI.BrowserSplitter = BrowserSplitter;
  window.VellumUI.BrowserSplitView = BrowserSplitView;
  window.VellumUI.SidebarResizeHandle = SidebarResizeHandle;
  window.VellumUI.BrowserCursorGraphic = BrowserCursorGraphic;
  window.VellumUI.browserPointerLayout = pointerLayout;
  window.VellumUI.BrowserPanel = BrowserPanel;
})();
