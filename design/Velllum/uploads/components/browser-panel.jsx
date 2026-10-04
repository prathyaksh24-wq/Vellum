(function () {
  const {useState, useEffect, useRef} = React;
  const Icon = ({name, size=16}) => {
    const paths = {back:'m14 4-8 8 8 8', forward:'m10 4 8 8-8 8', close:'m6 6 12 12M6 18 18 6',
      plus:'M12 5v14M5 12h14', pause:'M9 5v14M15 5v14', reload:'M20 7v5h-5M20 12a8 8 0 1 0-2 6',
      download:'M12 3v12m-5-5 5 5 5-5M5 17v4h14v-4', globe:'M3 12h18M12 3a9 9 0 0 1 0 18 9 9 0 0 1 0-18M12 3c-5 5-5 13 0 18 5-5 5-13 0-18',
      expand:'M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5', more:'M5 12h.01M12 12h.01M19 12h.01'};
    return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.globe}/></svg>;
  };

  function BrowserPanel({state, onRefresh, onHide, context, onReceipt}) {
    const api = window.VellumApi.browser;
    const [frame, setFrame] = useState(null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [address, setAddress] = useState('');
    const [downloadsOpen, setDownloadsOpen] = useState(false);
    const [expanded, setExpanded] = useState(false);
    const queue = useRef(Promise.resolve());
    const editingAddress = useRef(false);
    const current = useRef({state, frame});
    current.current = {state, frame};
    const active = state.tabs.find(tab => tab.active);
    const manual = state.control === 'user';
    useEffect(() => {
      if (!editingAddress.current) setAddress(active?.url === 'about:blank' ? '' : active?.url || '');
    }, [active?.url, active?.id]);
    useEffect(() => {
      let cancelled = false, timer;
      const refresh = async () => {
        if (!cancelled && state.running && state.active_tab_id && !document.hidden) {
          try {
            const next = await api.frame();
            if (!cancelled) { setFrame(next); setError(''); }
          } catch (failure) { if (!cancelled) setError(failure.message); }
        } else if (!state.running || !state.active_tab_id) setFrame(null);
        if (!cancelled) timer = setTimeout(refresh, 1000);
      };
      refresh();
      return () => { cancelled = true; clearTimeout(timer); };
    }, [state.session_id, state.running, state.active_tab_id]);

    const command = (operation, arguments_={}) => {
      const work = async () => {
        setBusy(true);
        try {
          let payload = {operation, ...arguments_};
          if (['click', 'type', 'press', 'scroll'].includes(operation) && !payload.frame_id) {
            // Revalidate ownership and document identity on the server for each input.
            payload.frame_id = current.current.frame?.frame_id || '';
          }
          const receipt = await api.control(payload, context);
          onReceipt?.(receipt);
          setError('');
          await onRefresh();
        } catch (failure) { setError(failure.message); }
        finally { setBusy(false); }
      };
      queue.current = queue.current.then(work, work);
      return queue.current;
    };
    const navigate = event => {
      event.preventDefault();
      const input = address.trim();
      if (!input) return;
      editingAddress.current = false;
      const url = /^https?:\/\//i.test(input) || input === 'about:blank' ? input : 'https://' + input;
      command('navigate', {url});
    };
    const click = event => {
      if (!manual || !frame || frame.tab_id !== state.active_tab_id) return;
      event.preventDefault();
      const point = api.point(event.currentTarget.getBoundingClientRect(), frame, event.clientX, event.clientY);
      if (point) command('click', {...point, frame_id:frame.frame_id});
      event.currentTarget.focus({preventScroll:true});
    };
    const keyDown = event => {
      if (!manual || event.nativeEvent?.isComposing) return;
      if (['Shift','Control','Alt','Meta','Dead','Process','Unidentified'].includes(event.key)) return;
      if (event.ctrlKey && event.key.toLowerCase() === 'v') return; // Paste is explicit below.
      if (event.key === 'Tab') return; // Keep app focus navigation accessible.
      if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault(); command('type', {text:event.key});
      } else {
        event.preventDefault();
        const modifiers = [event.ctrlKey && 'Control', event.metaKey && 'Meta', event.altKey && 'Alt', event.shiftKey && 'Shift'].filter(Boolean);
        command('press', {key:[...modifiers, event.key === ' ' ? 'Space' : event.key].join('+')});
      }
    };
    return <aside className={'browser-panel' + (expanded ? ' browser-expanded' : '')} aria-label="Vellum browser" data-ui-reference="browser-panel">
      <header className="browser-heading">
        <span className="browser-brand"><Icon name="globe" size={19}/>Brave</span>
        <span className="browser-status"><i className={state.control === 'agent' ? 'live' : ''}/>{state.control === 'agent' ? 'Ready' : state.control === 'user' ? 'You have control' : state.running ? 'Paused' : 'Closed'}</span>
        <div className="browser-heading-actions">
          {state.running ? <>
            <button className="browser-button" onClick={() => command(state.control === 'agent' ? 'pause' : 'resume')} disabled={busy}>{state.control === 'agent' ? <><Icon name="pause"/>Pause</> : 'Resume agent'}</button>
            {state.control !== 'user' && <button className="browser-button secondary" onClick={() => command('take_over')} disabled={busy}>Take over</button>}
          </> : <button className="browser-button" disabled={!state.available || busy} onClick={() => command('open')}>Open browser</button>}
          <button className="browser-icon" title={expanded ? 'Restore split view' : 'Expand browser'} aria-pressed={expanded} onClick={() => setExpanded(!expanded)}><Icon name="expand"/></button>
          <button className="browser-icon" title="Hide browser panel" onClick={onHide}><Icon name="close"/></button>
        </div>
      </header>
      {state.running && <>
        <div className="browser-tabs" role="tablist" aria-label="Browser tabs">
          {state.tabs.map(tab => <div key={tab.id} className={'browser-tab' + (tab.active ? ' active' : '')}>
            <button role="tab" aria-selected={tab.active} onClick={() => command('select_tab', {tab_id:tab.id})} title={tab.url}>{tab.title}</button>
            <button className="browser-icon" aria-label={'Close ' + tab.title} onClick={() => command('close_tab', {tab_id:tab.id})}><Icon name="close" size={12}/></button>
          </div>)}
          <button className="browser-icon" title="New tab" onClick={() => command('new_tab')}><Icon name="plus"/></button>
        </div>
        <form className="browser-address-row" onSubmit={navigate}>
          <button type="button" className="browser-icon" title="Back" onClick={() => command('back')} disabled={!active || busy}><Icon name="back"/></button>
          <button type="button" className="browser-icon" title="Forward" onClick={() => command('forward')} disabled={!active || busy}><Icon name="forward"/></button>
          <button type="button" className="browser-icon" title="Reload" onClick={() => command('reload')} disabled={!active || busy}><Icon name="reload"/></button>
          <input aria-label="Browser address" placeholder="Enter a website" value={address} onFocus={() => { editingAddress.current = true; }} onBlur={() => { editingAddress.current = false; }} onChange={event => setAddress(event.target.value)} spellCheck={false}/>
          <button type="button" className="browser-icon" title="Downloads" aria-expanded={downloadsOpen} onClick={() => setDownloadsOpen(!downloadsOpen)}><Icon name="download"/></button>
        </form>
      </>}
      {downloadsOpen && <section className="browser-downloads" aria-label="Browser downloads">
        <div className="browser-downloads-head"><strong>Downloads</strong><button className="browser-icon" title="Close downloads" onClick={() => setDownloadsOpen(false)}><Icon name="close"/></button></div>
        {state.downloads.length ? state.downloads.map(file => <div className="browser-download" key={file.id}>
          <Icon name="download"/><div><span>{file.name}</span><small>{file.state === 'saved' ? Math.max(1, Math.round(file.size/1024)) + ' KB · Saved' : file.state === 'failed' ? 'Download failed' : 'Downloading…'}</small></div>
          {file.state === 'saved' && <button className="browser-link" onClick={() => command('show_download', {download_id:file.id})}>Show in folder</button>}
        </div>) : <p>No downloads in this session.</p>}
      </section>}
      {error && <div className="browser-error" role="alert">{error}<button className="browser-link" onClick={() => onRefresh()}>Refresh</button></div>}
      <div className={'browser-screen' + (manual ? ' manual' : '')} tabIndex={manual ? 0 : -1} role="region" aria-label={manual ? 'Browser page. Click to focus a field, then type. Tab leaves the preview.' : 'Live browser page'}
        onPointerDown={click} onKeyDown={keyDown} onWheel={event => { if (manual) command('scroll', {delta:Math.max(-2000, Math.min(2000, Math.round(event.deltaY)))}); }}
        onPaste={event => { if (manual) { event.preventDefault(); command('type', {text:event.clipboardData.getData('text/plain').slice(0,10000)}); } }}
        onCompositionEnd={event => { if (manual && event.data) command('type', {text:event.data}); }}>
        {frame && state.running && frame.tab_id === state.active_tab_id ? <img src={frame.data_url} alt="Live view of the dedicated browser tab" draggable={false}/> : <div className="browser-empty"><Icon name="globe" size={32}/><h2>{state.running ? 'Your browser is ready' : 'A browser for Vellum'}</h2><p>{state.reason || (state.running ? 'Enter a website above or ask Vellum to browse.' : 'A separate Brave session on this device. Sign in here when you need to.')}</p></div>}
      </div>
      <footer className="browser-footer"><span>Separate session · On this device</span>{state.running && <button className="browser-link" disabled={busy} onClick={() => command('close')}>Close session</button>}</footer>
    </aside>;
  }
  window.VellumUI = window.VellumUI || {};
  window.VellumUI.BrowserPanel = BrowserPanel;
})();
