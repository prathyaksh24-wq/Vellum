(function () {
  const {useState, useEffect, useLayoutEffect, useRef} = React;
  const assets = 'assets/browser-home/';
  const Icon = ({name, size=16}) => <span className="browser-glyph" aria-hidden="true" style={{width:size, height:size, maskImage:`url("${assets}icons/${name}.svg")`, WebkitMaskImage:`url("${assets}icons/${name}.svg")`}}/>;
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

  function BrowserPanel({state, onRefresh, onHide, context, onReceipt}) {
    const api = window.VellumApi.browser;
    const [frame, setFrame] = useState(null);
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
    const [expanded, setExpanded] = useState(false);
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
    const closing = useRef(false);
    const started = useRef(false);
    const current = useRef({state, frame});
    current.current = {state, frame};
    const active = state.tabs.find(tab => tab.active);
    const home = pendingTabs > 0 || !state.running || !active || active.url === 'about:blank' && !active.loading;
    const preferences = state.preferences || api.defaultPreferences || fallbackPreferences;
    const engines = api.engines || fallbackEngines;
    const engine = engines.find(item => item.id === preferences.search_engine) || engines[0];
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
      if (empty) setAddress('');
      editingAddress.current = true;
      addressRef.current?.focus({preventScroll:true});
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
      if (current.current.state.tabs.length <= 1 && pendingTabs === 0) closeWindow();
      else command('close_tab', {tab_id:tabId});
    };
    const newTab = () => {
      setPendingTabs(count => count + 1);
      setHomeGeneration(count => count + 1);
      focusAddress(true);
      command('new_tab').finally(() => setPendingTabs(count => Math.max(0,count - 1)));
    };
    const shortcut = event => {
      if (event.getModifierState?.('AltGraph')) return;
      const key = event.key.toLowerCase();
      const modifier = event.altKey || event.ctrlKey || event.metaKey;
      let handled = true;
      if (modifier && key === 'l') focusAddress();
      else if (modifier && key === 't' && !event.shiftKey) newTab();
      else if (modifier && key === 'w' && !event.shiftKey) closeTab(current.current.state.active_tab_id);
      else if (event.altKey && key === 'arrowleft') command('back');
      else if (event.altKey && key === 'arrowright') command('forward');
      else if (key === 'f5' || (modifier && key === 'r')) command('reload');
      else if (event.altKey && /^[1-9]$/.test(key)) {
        const tabs = current.current.state.tabs;
        const tab = key === '9' ? tabs[tabs.length-1] : tabs[Number(key)-1];
        if (tab) command('select_tab', {tab_id:tab.id});
      } else handled = false;
      if (handled) { event.preventDefault(); event.stopPropagation(); }
    };
    useEffect(() => {
      if (!editingAddress.current) setAddress(active?.url === 'about:blank' ? '' : active?.url || '');
    }, [active?.url, active?.id]);
    useEffect(() => {
      if (home) { setFrame(null); setViewError(''); return; }
      let cancelled = false, timer, reconnect, stopStream, streaming = false;
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
        try { stopStream = api.stream(next => { streaming = true; display(next); }, retry); }
        catch (_) { retry(); } // HTTP frames remain available if sockets are blocked.
      };
      const refresh = async () => {
        if (!cancelled && !streaming && state.running && state.active_tab_id && !document.hidden) {
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
    }, [state.session_id, state.running, state.active_tab_id, home]);

    useEffect(() => {
      if (!state.running || !state.active_tab_id || !screenRef.current || typeof ResizeObserver === 'undefined') return;
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
    }, [state.session_id, state.running, state.active_tab_id]);
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
          if (!current.current.state.running && ['navigate','new_tab'].includes(operation)) {
            const opened = await api.control({operation:'open'}, context);
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
          const receipt = await api.control(payload, context);
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
      if (!started.current && state.available) {
        started.current = true;
        if (home) focusAddress(true);
      }
    }, [state.available]);
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
    return <aside className={'browser-panel' + (expanded ? ' browser-expanded' : '')} aria-label="Vellum browser" data-ui-reference="browser-panel"
      onKeyDownCapture={shortcut} onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); setDownloadsOpen(false); setMoreOpen(false); } }}>
      <header className="browser-heading">
        <span className="browser-brand" title="Dedicated Brave session on this device"><BrandIcon engine={engines[1]} size={20}/></span>
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
          <button className="browser-icon" title={expanded ? 'Restore split view' : 'Expand browser'} aria-pressed={expanded} onClick={() => setExpanded(!expanded)}><Icon name={expanded ? 'restore' : 'expand'}/></button>
          <button className="browser-icon" title="Browser menu" aria-expanded={moreOpen} onClick={() => { setMoreOpen(!moreOpen); setDownloadsOpen(false); }}><Icon name="more"/></button>
          <button className="browser-icon" title="Close browser" aria-label="Close browser panel" onClick={closeWindow}><Icon name="close"/></button>
        </div>
      </header>
      <>
        <form className="browser-address-row" onSubmit={navigate}>
          <button type="button" className="browser-icon" title="Back" onClick={() => command('back')} disabled={!active || busy}><Icon name="back"/></button>
          <button type="button" className="browser-icon" title="Forward" onClick={() => command('forward')} disabled={!active || busy}><Icon name="forward"/></button>
          <button type="button" className="browser-icon" title="Reload" onClick={() => command('reload')} disabled={!active || busy}><Icon name="reload"/></button>
          <button type="button" className="browser-icon" title="Home" onClick={() => command('navigate', {url:'about:blank'})}><Icon name="home"/></button>
          <div className="browser-omnibox-wrap">
            <label className="browser-omnibox"><BrandIcon engine={engine} size={16}/><input ref={addressRef} aria-label="Browser address" aria-keyshortcuts="Alt+L" role="combobox" aria-autocomplete="both" aria-expanded={addressOpen && suggestions.length > 0} aria-controls="browser-address-suggestions" aria-activedescendant={addressOpen && selectedSuggestion >= 0 ? 'browser-suggestion-' + selectedSuggestion : undefined} autoComplete="off" placeholder={'Search ' + engine.name + ' or enter address'} value={address} onFocus={() => { editingAddress.current = true; setAddressQuery(addressRef.current?.value || ''); setAddressOpen(false); setSelectedSuggestion(-1); addressRef.current?.select(); }} onBlur={() => { editingAddress.current = false; setAddressOpen(false); if (!address.trim()) setAddress(active?.url === 'about:blank' ? '' : active?.url || ''); }} onChange={changeAddress} onKeyDown={addressKeyDown} spellCheck={false}/></label>
            {addressOpen && suggestions.length > 0 && <div className="browser-suggestions" id="browser-address-suggestions" role="listbox" aria-label="Address suggestions">
              {suggestions.map((item,index) => <button type="button" className="browser-suggestion" id={'browser-suggestion-' + index} key={item.kind + ':' + item.url} role="option" aria-selected={index === selectedSuggestion} onPointerDown={event => event.preventDefault()} onClick={() => chooseSuggestion(item)}>
                {['search','query'].includes(item.kind) ? <Icon name="search" size={16}/> : <ShortcutIcon url={item.url}/>}
                <span className="browser-suggestion-copy"><span>{item.title}</span>{!['search','query'].includes(item.kind) && <small>{item.url.replace(/^https?:\/\//i,'')}</small>}</span>
                <span className="browser-suggestion-hint">{item.kind === 'tab' ? 'Switch to tab' : item.kind === 'search' ? 'Search ' + engine.name : item.kind === 'query' ? engine.name : item.kind === 'history' ? 'History' : item.kind === 'website' ? 'Website' : 'Shortcut'}</span>
              </button>)}
              {completions.query === addressQuery && completions.engine === engine.id && completions.status === 'unavailable' && <small className="browser-suggestions-status" role="status">{engine.name} suggestions unavailable</small>}
            </div>}
          </div>
          <button type="button" className="browser-icon" title="Downloads" aria-expanded={downloadsOpen} onClick={() => { setDownloadsOpen(!downloadsOpen); setMoreOpen(false); }}><Icon name="download"/></button>
        </form>
      </>
      {moreOpen && <section className="browser-session-menu" aria-label="Browser session menu"><strong>Brave session</strong><p>Separate session · On this device</p><label><input type="checkbox" checked={preferences.suggestions_enabled !== false} onChange={event => command('preferences', {suggestions_enabled:event.target.checked})}/>Search suggestions</label><p>Sends what you type to {engine.name}. History stays on this device.</p><button className="browser-button" onClick={closeWindow}><Icon name="close"/>Close session</button></section>}
      {downloadsOpen && <section className="browser-downloads" aria-label="Browser downloads">
        <div className="browser-downloads-head"><strong>Downloads</strong><button className="browser-icon" title="Close downloads" onClick={() => setDownloadsOpen(false)}><Icon name="close"/></button></div>
        {state.downloads.length ? state.downloads.map(file => <div className="browser-download" key={file.id}>
          <Icon name="download"/><div><span>{file.name}</span><small>{file.state === 'saved' ? Math.max(1, Math.round(file.size/1024)) + ' KB · Saved' : file.state === 'failed' ? 'Download failed' : 'Downloading…'}</small></div>
          {file.state === 'saved' && <button className="browser-link" onClick={() => command('show_download', {download_id:file.id})}>Show in folder</button>}
        </div>) : <p>No downloads in this session.</p>}
      </section>}
      {(error || viewError || active?.error) && <div className="browser-error" role="alert">{error || viewError || active.error}<button className="browser-link" onClick={() => onRefresh()}>Refresh</button></div>}
      <div ref={screenRef} className={'browser-screen' + (manual ? ' manual' : '') + (home ? ' browser-screen-home' : '')} tabIndex={state.running && !home ? 0 : -1} role="region" aria-label={home ? 'Browser homepage' : manual ? 'Browser page. Click to focus a field, then type. Tab leaves the preview.' : 'Live browser page. Click to take control.'}
        onPointerDown={click} onPointerMove={hover} onPointerLeave={() => {
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
        {home ? <BrowserHome key={homeGeneration} api={api} preferences={preferences} engine={engine} engines={engines} command={command}/> : frame && state.running && frame.tab_id === state.active_tab_id ? <img src={frame.data_url} alt="Live view of the dedicated browser tab" draggable={false}/> : <div className="browser-empty"><Icon name="globe" size={32}/><h2>{active?.loading ? 'Loading page…' : 'Your browser is ready'}</h2><p>{state.reason || (active?.loading ? 'You can open another tab while this site loads.' : 'Enter a website above or ask Vellum to browse.')}</p></div>}
      </div>
    </aside>;
  }
  window.VellumUI = window.VellumUI || {};
  window.VellumUI.BrowserPanel = BrowserPanel;
})();
