(function () {
  const {useState, useEffect, useRef} = React;
  function timestamp(value) {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Unavailable' : date.toLocaleString(undefined, {
      year:'numeric', month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit', timeZoneName:'short'
    });
  }
  function duration(run) {
    if (!run.finished_at) return run.status === 'running' ? 'In progress' : '—';
    const milliseconds = new Date(run.finished_at) - new Date(run.started_at);
    return Number.isFinite(milliseconds) && milliseconds >= 0 ? (milliseconds / 1000).toFixed(1) + ' seconds' : '—';
  }
  function AutomationRunHistory({runs = []}) {
    const ordered = [...runs].sort((a,b) => String(b.started_at).localeCompare(String(a.started_at)));
    return <section className="au-run-history" aria-label="Run history">
      <h3>Run history <span>{runs.length} recorded</span></h3>
      <p>Newest first · times in {Intl.DateTimeFormat().resolvedOptions().timeZone} · latest 100 runs retained</p>
      {!ordered.length && <p>No recorded runs yet.</p>}
      {ordered.map(run => <article className="au-run-entry" key={run.id}>
        <div className="au-run-heading"><strong>{run.status === 'failed' ? 'Failed' : run.status === 'running' ? 'Running' : 'Completed'}</strong><time dateTime={run.started_at}>{timestamp(run.started_at)}</time></div>
        <dl><div><dt>Started</dt><dd>{timestamp(run.started_at)}</dd></div><div><dt>Finished</dt><dd>{timestamp(run.finished_at)}</dd></div><div><dt>Duration</dt><dd>{duration(run)}</dd></div></dl>
        {run.output && <div className="au-run-output">{run.output}</div>}
        {run.error && <div className="au-run-error">{run.error}</div>}
        <details><summary>Run ID</summary><code>{run.id}</code></details>
      </article>)}
    </section>;
  }
  function isRecentUnread(item) {
    const age = Date.now() - new Date(item.created_at).getTime();
    return !item.read_at && Number.isFinite(age) && age >= 0 && age <= 24*60*60*1000;
  }
  function dayLabel(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Date unavailable';
    const today = new Date(), yesterday = new Date(); yesterday.setDate(today.getDate()-1);
    if (date.toDateString() === today.toDateString()) return 'Today';
    if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
    return date.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'});
  }
  function AutomationNotificationCenter({onAction, onPing, browserVisible=false, sidebarPinned=false}) {
    const [snapshot,setSnapshot] = useState({items:[],recent_unread_count:0,total_count:0});
    const [history,setHistory] = useState({items:[],matched_count:0,has_more:false});
    const [open,setOpen] = useState(false);
    const [view,setView] = useState('recent');
    const [query,setQuery] = useState('');
    const [offset,setOffset] = useState(0);
    const [revision,setRevision] = useState(0);
    const [loading,setLoading] = useState(false);
    const [available,setAvailable] = useState(false);
    const [error,setError] = useState('');
    const [busy,setBusy] = useState(false);
    const callbacks = useRef({onAction,onPing,browserVisible}); callbacks.current = {onAction,onPing,browserVisible};
    const refreshRef = useRef(null);
    const container = useRef(null), trigger = useRef(null), closeButton = useRef(null);
    useEffect(() => {
      let alive = true, reading = false, supported = false;
      const seen = new Set(); let initialized = false, lastPollAt=Date.now();
      async function refresh() {
        if (reading || !alive) return;
        reading = true;
        const startedAt=Date.now();
        try {
          if (!supported) {
            const contract = await window.VellumApi.plugins.capabilities();
            supported = !!contract.features?.automation_notifications?.enabled;
            if (!supported) {setError('Notifications are not available on this backend.'); return;}
          }
          const next = await window.VellumApi.automations.notifications({view:'recent',limit:50});
          if (!alive) return;
          setAvailable(true); setError(''); setSnapshot(next);
          const fresh = next.items.filter(item => isRecentUnread(item) && !seen.has(item.id) && new Date(item.created_at).getTime() >= lastPollAt);
          next.items.forEach(item => seen.add(item.id));
          // Reopening Vellum exposes retained unread items without replaying old pings.
          if (initialized && fresh.length && !callbacks.current.browserVisible) callbacks.current.onPing({message:fresh.length === 1 ? fresh[0].message.split('\n')[0] : fresh.length + ' new upload notifications', duration:4500, notificationPing:true});
          initialized = true;
          lastPollAt=startedAt;
          // Keep this projection bounded; durable deduplication belongs to the backend.
          if (seen.size > 600) {seen.clear(); next.items.forEach(item => seen.add(item.id));}
        } catch (_) {if (alive) setError('Notifications are temporarily unavailable.');}
        finally {reading = false;}
      }
      refreshRef.current = refresh;
      refresh();
      const timer = setInterval(() => {if (document.visibilityState !== 'hidden') refresh();},15000);
      const focus = () => refresh();
      window.addEventListener('focus',focus);
      return () => {alive=false; clearInterval(timer); window.removeEventListener('focus',focus);};
    },[]);
    useEffect(() => {setOpen(false);},[browserVisible]);
    useEffect(() => {
      const show = () => {trigger.current=document.activeElement;setView('recent');setOpen(true);refreshRef.current?.();};
      window.addEventListener('vellum:notifications-open',show);
      return () => window.removeEventListener('vellum:notifications-open',show);
    },[]);
    useEffect(() => {
      if (!open || view !== 'history') return;
      let alive=true;
      setLoading(true);
      setHistory({items:[],matched_count:0,has_more:false});
      const timer=setTimeout(async () => {
        try {
          const next=await window.VellumApi.automations.notifications({view:'history',limit:50,offset,query});
          if (alive) {setHistory(next);setError('');}
        } catch (_) {if (alive) setError('History is temporarily unavailable. Try reopening notifications.');}
        finally {if (alive) setLoading(false);}
      },query ? 250 : 0);
      return () => {alive=false;clearTimeout(timer);};
    },[open,view,offset,query,revision]);
    function close() {setOpen(false); trigger.current?.focus();}
    useEffect(() => {
      if (!open) return;
      closeButton.current?.focus();
      const key = event => {if (event.key === 'Escape') close();};
      const outside = event => {if (!container.current?.contains(event.target)) setOpen(false);};
      window.addEventListener('keydown',key); document.addEventListener('pointerdown',outside);
      return () => {window.removeEventListener('keydown',key);document.removeEventListener('pointerdown',outside);};
    },[open]);
    async function markRead(ids, recent=false) {
      if (busy) return;
      setBusy(true);
      try {
        const receipt = await callbacks.current.onAction('automation.notifications.read', recent ? {recent:true} : {ids}, {notify:false});
        if (receipt?.status !== 'applied') throw new Error('Unavailable');
        await refreshRef.current();
        setRevision(value=>value+1);
      } catch (_) {setError('Could not mark notifications read.');}
      finally {setBusy(false);}
    }
    const recentItems = snapshot.items.filter(isRecentUnread);
    const unread = snapshot.recent_unread_count ?? recentItems.length;
    const items = view === 'history' ? history.items : recentItems;
    const groups = new Map(); items.forEach(item=>{const day=dayLabel(item.created_at);if (!groups.has(day)) groups.set(day,[]);groups.get(day).push(item);});
    if (!available && !open) return null;
    return <div ref={container} className={'automation-notifications'+(browserVisible ? ' browser-quiet' : '')} style={browserVisible ? {left:sidebarPinned ? 270 : 64,right:'auto'} : undefined}>
      {!browserVisible && available && <button type="button" className="notification-bell" aria-label={'Notifications' + (unread ? ', ' + unread + ' recent unread' : '')} aria-expanded={open} aria-controls="notification-panel" onClick={event => {trigger.current=event.currentTarget;setOpen(!open); refreshRef.current();}}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg>
        {unread > 0 && <span className="notification-count">{unread > 99 ? '99+' : unread}</span>}
      </button>}
      {open && <section id="notification-panel" className="notification-panel" aria-label="Notifications">
        <header><h2>Notifications</h2><button ref={closeButton} type="button" aria-label="Close notifications" onClick={close}>×</button></header>
        <div className="notification-views" role="group" aria-label="Notification views">
          <button type="button" aria-pressed={view==='recent'} onClick={()=>setView('recent')}>Recent {unread > 0 && <span>{unread}</span>}</button>
          <button type="button" aria-pressed={view==='history'} onClick={()=>{setView('history');setOffset(0);}}>History</button>
        </div>
        {view==='recent' ? <div className="notification-toolbar"><span>Unread · last 24 hours</span><button type="button" disabled={busy || !unread} onClick={() => markRead([],true)}>Mark recent read</button></div> :
          <label className="notification-search">Search history<input type="search" maxLength={200} placeholder="Creator or title" value={query} onChange={event=>{setQuery(event.target.value);setOffset(0);}}/></label>}
        {error && <p role="alert">{error}</p>}
        <div className="notification-items" key={view} aria-busy={loading}>{loading || !available && !error ? <p>{view==='history' ? 'Reading history…' : 'Checking notifications…'}</p> : !items.length && !error && <div className="notification-empty"><strong>{view==='recent' ? 'You’re caught up.' : query ? 'No matching notifications.' : 'No saved notifications yet.'}</strong><p>{view==='recent' ? 'Older and read notifications stay in History.' : 'Try another creator or video title.'}</p></div>}
          {!loading && [...groups].map(([day,entries])=><section className="notification-day" key={day} aria-label={day}><h3>{day}</h3>{entries.map(item => <article key={item.id} className={'notification-item' + (!item.read_at ? ' unread' : '')}>
            <p title={item.message.split('\n')[0]}>{item.message.split('\n')[0]}</p><time dateTime={item.created_at} title={timestamp(item.created_at)}>Received {new Date(item.created_at).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'})}</time>
            <div>{/^https:\/\/www\.youtube\.com\/watch\?v=[\w-]{11}$/.test(item.url) && <a href={item.url} target="_blank" rel="noopener noreferrer" onClick={() => markRead([item.id])}>Watch video ↗</a>}{!item.read_at && <button type="button" disabled={busy} onClick={() => markRead([item.id])}>Mark read</button>}</div>
          </article>)}</section>)}
        </div>
        <footer className="notification-footer">{view==='history' && <div className="notification-pagination"><button type="button" disabled={loading || offset===0} onClick={()=>setOffset(Math.max(0,offset-50))}>Newer</button><span>{history.matched_count ? `${offset+1}–${Math.min(offset+50,history.matched_count)} of ${history.matched_count}` : '0 results'}</span><button type="button" disabled={loading || !history.has_more} onClick={()=>setOffset(offset+50)}>Older</button></div>}
          {view==='recent' ? 'Older items stay saved in History. ' : 'History includes recent and read items. '}Latest {snapshot.retention_per_automation || 200} notifications per task retained.
          {view==='recent' && snapshot.recent_unread_count > recentItems.length && <button type="button" onClick={()=>{setView('history');setOffset(0);}}>View all {snapshot.recent_unread_count} recent items in History</button>}
        </footer>
      </section>}
    </div>;
  }
  window.VellumAutomationNotifications = {AutomationRunHistory, AutomationNotificationCenter};
})();
