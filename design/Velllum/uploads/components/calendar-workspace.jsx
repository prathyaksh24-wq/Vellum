/** @jsxRuntime classic */
(function () {
  const {useState, useEffect, useRef} = React;
  function CalendarWorkspace({enabled = true, onStatus, onAction}) {
    const api = window.VellumApi.plugins;
    const blank = () => ({summary:'', start:'', end:''});
    const [status,setStatus] = useState(null), [calendars,setCalendars] = useState([]);
    const [calendarId,setCalendarId] = useState('all'), [events,setEvents] = useState([]);
    const [draft,setDraft] = useState(blank), [editing,setEditing] = useState(null);
    const [pending,setPending] = useState(null), [proposal,setProposal] = useState(null);
    const [busy,setBusy] = useState(false), [error,setError] = useState('');
    const [connecting,setConnecting] = useState(false), [search,setSearch] = useState('');
    const mounted = useRef(true), loading = useRef(false), popup = useRef(null);
    const selected = useRef('all'), searchValue = useRef('');
    const inputValue = value => {
      const date = new Date(value);
      if (!value || Number.isNaN(date.getTime())) return '';
      return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16);
    };
    const display = value => new Date(value).toLocaleString(undefined, {
      timeZone:status?.time_zone || undefined, dateStyle:'medium', timeStyle:'short'
    });
    const loadEvents = async id => {
      const from = new Date(), to = new Date(from.getTime()+7*86400000);
      const result = await api.calendarEvents({time_min:from.toISOString(), time_max:to.toISOString(),
        calendar_id:id || 'primary', query:searchValue.current, max_results:'50'});
      if (mounted.current) setEvents(result.items || []);
    };
    const load = async probe => {
      if (loading.current) return;
      loading.current = true; setBusy(true); setError('');
      try {
        const next = await api.calendarStatus(probe === true);
        if (!mounted.current) return;
        setStatus(next); onStatus?.(next);
        if (next.connected) setConnecting(false);
        if (next.connected && next.enabled !== false && enabled) {
          const result = await api.calendarCalendars();
          if (!mounted.current) return;
          const visible = result.items || [];
          const id = selected.current==='all' || visible.some(item=>item.id===selected.current) ? selected.current : (visible.find(item=>item.primary)?.id || 'primary');
          selected.current = id; setCalendarId(id); setCalendars(visible);
          await loadEvents(id);
        } else {setCalendars([]); setEvents([]);}
      } catch (e) {if (mounted.current) setError(e.message || 'Google Calendar is unavailable.');}
      finally {loading.current=false; if (mounted.current) setBusy(false);}
    };
    useEffect(()=>{
      mounted.current=true; load(false);
      const backendOrigin = window.VellumApi.client.backendBase();
      const complete = event => {if(event.origin===backendOrigin && event.data?.type==='vellum:google-calendar-oauth-complete') load(true);};
      const focus = () => load(false);
      window.addEventListener('message',complete); window.addEventListener('focus',focus);
      return ()=>{mounted.current=false; window.removeEventListener('message',complete); window.removeEventListener('focus',focus);};
    },[enabled]);
    useEffect(()=>{
      if(!connecting) return;
      const timer=setInterval(()=>load(false),1500);
      const timeout=setTimeout(()=>{setConnecting(false);setError('Sign-in has not completed. Try Connect again.');},600000);
      return ()=>{clearInterval(timer);clearTimeout(timeout);};
    },[connecting]);
    const dispatch = async (id, body={}, confirmed=false) => {
      if(!onAction) throw new Error('Calendar actions are unavailable. Reload Vellum.');
      const receipt=await onAction(id,body,{confirmedFromUi:confirmed});
      if(!receipt || receipt.status!=='applied') throw new Error(receipt?.message || 'Calendar change was not completed.');
      return receipt.result || {};
    };
    const connect = async () => {
      setBusy(true);setError('');
      popup.current=window.open('about:blank','vellum-google-calendar-oauth','popup,width=620,height=760');
      try {
        const result=(await dispatch('calendar.connection.start')).connection;
        if(popup.current) popup.current.location.href=result.authorization_url;
        else window.open(result.authorization_url,'_blank','noopener,noreferrer');
        setConnecting(true);
      } catch(e) {popup.current?.close();setError(e.message || 'Calendar connection could not be started.');}
      finally {setBusy(false);}
    };
    const disconnect = async () => {
      setBusy(true);setError('');
      try {await dispatch('calendar.connection.disconnect',{},true);setPending(null);setProposal(null);setConnecting(false);await load(false);}
      catch(e){setError(e.message || 'Disconnect failed.');}finally{setBusy(false);}
    };
    const choose = async id => {
      selected.current=id;setCalendarId(id);setBusy(true);setError('');
      try {await loadEvents(id);}catch(e){setError(e.message);}finally{setBusy(false);}
    };
    const submit = async () => {
      const start=new Date(draft.start),end=new Date(draft.end);
      if(!draft.summary.trim() || !draft.start || !draft.end) return setError('Title, start, and end are required.');
      if(Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end<=start) return setError('End must be after start.');
      const destination=editing?.calendar_id || (calendarId==='all'?(calendars.find(c=>c.primary)?.id || 'primary'):calendarId);
      const action={kind:editing?'update':'create',eventId:editing?.id || '',calendarId:destination,
        body:{calendar_id:destination,summary:draft.summary.trim(),start:start.toISOString(),end:end.toISOString(),time_zone:status?.time_zone || '',confirm:true}};
      setBusy(true);setError('');setProposal(null);
      try {
        const availability=await api.calendarAvailability({...action.body,event_id:action.eventId});
        if(availability.available) setPending(action);
        else setProposal({action,availability});
      } catch(e){setError(e.message);}finally{setBusy(false);}
    };
    const useSlot = () => {
      const times=proposal.availability.proposed;
      const action={...proposal.action,body:{...proposal.action.body,...times}};
      setDraft({...draft,start:inputValue(times.start),end:inputValue(times.end)});
      setPending(action);setProposal(null);
    };
    const edit = event => {setEditing({...event,calendar_id:event.calendar_id || calendarId});setProposal(null);setError('');setDraft({summary:event.summary || '',start:inputValue(event.start),end:inputValue(event.end)});};
    const confirm = async () => {
      if(!pending || busy) return;
      setBusy(true);setError('');
      try {
        const body=Object.assign({},pending.body || {calendar_id:pending.calendarId});
        delete body.confirm;
        const result=await dispatch(`calendar.event.${pending.kind}`,{...body,...(pending.eventId?{event_id:pending.eventId}:{})},true);
        if(result.availability && !result.availability.available) {setProposal({action:pending,availability:result.availability});setPending(null);return;}
        setPending(null);setEditing(null);setDraft(blank());await loadEvents(calendarId);
      } catch(e) {
        if(e.status===409 && e.detail?.availability) {setProposal({action:pending,availability:e.detail.availability});setPending(null);}
        else setError(e.message || 'Calendar change failed.');
      } finally{setBusy(false);}
    };
    const active=enabled && status?.enabled!==false;
    return <section className="calendar-workspace" aria-label="Google Calendar workspace">
      <div className="calendar-head"><strong>Google Calendar</strong><span role="status">{!active?(status?.connected?'Disabled · connection saved':'Disabled'):status?.connected?`Connected · ${status.time_zone || 'calendar time zone'}`:connecting?'Connecting…':'Not connected'}</span>
        <div className="calendar-head-actions"><button className="btn" aria-label="Refresh Calendar" disabled={busy} onClick={()=>load(true)}>Refresh</button>
          {active && status?.connected && <button className="btn" disabled={busy} onClick={disconnect}>Disconnect</button>}</div></div>
      {!active?<div className="calendar-connect">Enable Google Calendar to use it. Disabling preserves your saved connection.</div>:!status?.connected?
        <div className="calendar-connect"><span>{status?.configured===false?'Google OAuth credentials need to be configured before connecting.':'Connect your Google account. Google will ask you to approve Calendar access, then this page updates automatically.'}</span>
          <button className="btn" disabled={busy || connecting || status?.configured===false} onClick={connect}>{connecting?'Waiting for Google…':'Connect Google Calendar'}</button></div>:
        <React.Fragment>
          <div className="calendar-toolbar"><select aria-label="Google Calendar" value={calendarId} disabled={busy || !!editing || !!pending} onChange={e=>choose(e.target.value)}><option value="all">All calendars</option>{calendars.map(item=><option key={item.id} value={item.id}>{item.summary || item.id}</option>)}</select>
            <input aria-label="Find calendar events" placeholder="Find events" value={search} onChange={e=>{setSearch(e.target.value);searchValue.current=e.target.value;}}/>
            <button className="btn" disabled={busy} onClick={()=>choose(calendarId)}>Find events</button><button className="btn" disabled={busy} onClick={()=>{setSearch('');searchValue.current='';choose(calendarId);}}>Upcoming events</button></div>
          <div className="calendar-events">{events.length?events.map(event=><article className="calendar-event" key={event.id}><span className="calendar-event-dot"/><div className="calendar-event-copy"><strong>{event.summary || 'Untitled event'}</strong><span>{display(event.start)}{event.calendar_label?` · ${event.calendar_label}`:''}{event.location?` · ${event.location}`:''}</span></div>
            <div className="calendar-event-actions"><button disabled={busy || !!pending || ['reader','freeBusyReader'].includes(event.access_role)} onClick={()=>edit(event)}>Edit</button><button disabled={busy || !!pending || !!editing || ['reader','freeBusyReader'].includes(event.access_role)} onClick={()=>setPending({kind:'delete',eventId:event.id,calendarId:event.calendar_id || calendarId,title:event.summary})}>Delete</button></div></article>):<div className="discord-empty">{search?'No matching events in the next seven days.':'No events in the next seven days.'}</div>}</div>
          <div className="calendar-editor"><input aria-label="Event title" maxLength="1024" placeholder="Event title" value={draft.summary} disabled={busy || !!pending} onChange={e=>setDraft({...draft,summary:e.target.value})}/>
            <input aria-label="Event start" type="datetime-local" value={draft.start} disabled={busy || !!pending} onChange={e=>setDraft({...draft,start:e.target.value})}/>
            <input aria-label="Event end" type="datetime-local" value={draft.end} disabled={busy || !!pending} onChange={e=>setDraft({...draft,end:e.target.value})}/>
            <div className="calendar-editor-actions">{editing && <button className="btn" onClick={()=>{setEditing(null);setProposal(null);setDraft(blank());}}>Cancel edit</button>}<button className="btn" disabled={busy || !!pending} onClick={submit}>{editing?'Update event':'Create event'}</button></div></div>
          {proposal && <div className="discord-confirm" role="alert"><span>That time overlaps another event. {proposal.availability.proposed?`Available: ${display(proposal.availability.proposed.start)} to ${display(proposal.availability.proposed.end)}. Does that time work?`:'No daytime slot was found in the next seven days. Choose another date.'}</span>
            <button className="btn" onClick={()=>setProposal(null)}>Choose another time</button>{proposal.availability.proposed && <button className="btn" onClick={useSlot}>Use suggested time</button>}</div>}
          {pending && <div className="discord-confirm"><span>Confirm Google Calendar {pending.kind}: {pending.body?.summary || pending.title || pending.eventId}{pending.body?.start?` · ${display(pending.body.start)} to ${display(pending.body.end)}`:''}</span><button className="btn" disabled={busy} onClick={()=>setPending(null)}>Cancel</button><button className="btn" disabled={busy} onClick={confirm}>Confirm</button></div>}
        </React.Fragment>}
      {error && <div className="calendar-error" role="alert">{error}</div>}
    </section>;
  }
  window.VellumUI = window.VellumUI || {};
  window.VellumUI.CalendarWorkspace = CalendarWorkspace;
})();
