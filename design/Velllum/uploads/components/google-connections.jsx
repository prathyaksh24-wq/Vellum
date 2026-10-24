(function () {
  const {useEffect,useRef,useState}=React;
  const marks={drive:'googledrive.png',gmail:'gmail.svg',calendar:'googlecalendar.svg',contacts:'googlecontacts.png'};
  const names={drive:'Google Drive',gmail:'Gmail',calendar:'Google Calendar',contacts:'Google Contacts'};
  const descriptions={drive:'Find files and read metadata',gmail:'Read messages and threads',calendar:'Read calendars and manage events',contacts:'Read personal contact details'};
  const manageDescriptions={drive:'Read, create, edit, share and delete files',gmail:'Read, draft, send, update and delete mail',calendar:'Read and manage calendars and events',contacts:'Read, create, edit and delete contacts'};
  function GoogleActionReview({review}) {
    return <section className="google-action-review" aria-label="Review Google change"><header><img src={'/design-uploads/assets/plugins/'+marks[review.service]} width="24" height="24" alt=""/><h3>{review.heading}</h3></header><p>Account: {review.account}</p><p>{review.warning}</p><dl>{(review.fields||[]).map((field,index)=><div key={index}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl></section>;
  }
  function GoogleOperations() {
    const [service,setService]=useState('gmail'),[draft,setDraft]=useState(''),[query,setQuery]=useState(''),[offset,setOffset]=useState(0),[data,setData]=useState(null),[error,setError]=useState('');
    useEffect(()=>{let stopped=false;setData(null);setError('');window.VellumApi.plugins.googleCatalog({service,query,offset,limit:20}).then(value=>{if(!stopped)setData(value);}).catch(err=>{if(!stopped)setError(err.message);});return()=>{stopped=true;};},[service,query,offset]);
    return <section className="google-operations" aria-label="Google API operations"><h3>Available API operations</h3><form onSubmit={event=>{event.preventDefault();setOffset(0);setQuery(draft);}}><select aria-label="Google service" value={service} onChange={event=>{setService(event.target.value);setOffset(0);}}>{Object.keys(names).map(id=><option key={id} value={id}>{names[id]}</option>)}</select><input aria-label="Search API operations" placeholder="Search operations" value={draft} onChange={event=>setDraft(event.target.value)}/><button className="btn" type="submit">Search</button></form>{error&&<p role="alert">{error}</p>}{data?<React.Fragment><p>{data.total} matching operations · {data.operation_count} published methods</p><ul>{data.methods.map(item=><li key={item.method_id}><details><summary>{item.method_id}<small>{item.read_only?'Read':'Requires review'}</small></summary><p>{item.description}</p></details></li>)}</ul><div className="google-connection-actions"><button className="btn" disabled={!offset} onClick={()=>setOffset(value=>Math.max(0,value-20))}>Previous</button><button className="btn" disabled={data.next_offset==null} onClick={()=>setOffset(data.next_offset)}>Next</button></div><a href={data.source} target="_blank" rel="noopener noreferrer">Official Google API source · {data.revision}</a></React.Fragment>:!error&&<p role="status">Loading published operations…</p>}</section>;
  }
  function GoogleConnections({onChanged,revision}) {
    const api=window.VellumApi,dialog=useRef(null),trigger=useRef(null),mounted=useRef(true),pendingRef=useRef(null);
    const [status,setStatus]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
    const [open,setOpen]=useState(false),[selected,setSelected]=useState([]),[pending,setPending]=useState(null);
    const [forceSignIn,setForceSignIn]=useState(false),[access,setAccess]=useState('read'),[browse,setBrowse]=useState(false);
    const [flow,setFlow]=useState(()=>{const id=new URLSearchParams(window.location.search).get('google_oauth');return id?{flow_id:id,status:'pending'}:null;});
    const accept=value=>{if(mounted.current)setStatus(value);};
    const refresh=async()=>{try{accept(await api.plugins.googleStatus());}catch(err){if(mounted.current)setError(err.message||'Google connection is unavailable.');}};
    useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;const current=pendingRef.current;if(current)api.appActions.cancel(current.receipt.confirmation.token,{source:'ui'}).catch(()=>{});};},[]);
    useEffect(()=>{refresh();},[revision]);
    useEffect(()=>{
      if(!open)return;
      const element=dialog.current;
      if(element?.showModal)element.showModal();else element?.setAttribute('open','');
      return()=>{element?.close?.();trigger.current?.focus();};
    },[open]);
    useEffect(()=>{
      if(flow?.status!=='pending'||!flow.flow_id)return;
      let stopped=false,checking=false;
      const check=async()=>{if(checking)return;checking=true;try{
        const next=await api.plugins.googleOAuthStatus(flow.flow_id);
        if(stopped)return;
        setFlow(previous=>({...previous,...next}));
        if(next.status!=='pending'){
          const url=new URL(window.location.href);url.searchParams.delete('google_oauth');window.history.replaceState(window.history.state,'',url);
          await refresh();onChanged?.();
        }
      }catch(err){if(!stopped){setError(err.message||'Could not check Google sign-in.');setFlow(previous=>({...previous,status:'failed'}));}}
      finally{checking=false;}};
      check();const interval=setInterval(check,1500);
      return()=>{stopped=true;clearInterval(interval);};
    },[flow?.flow_id,flow?.status]);
    const choose=()=>{
      setForceSignIn(false);
      setAccess(status?.services?.filter(item=>item.enabled).every(item=>item.can_write)?'manage':'read');
      setSelected(status?.services?.some(item=>item.authorized&&item.id!=='calendar')?status.services.filter(item=>item.enabled).map(item=>item.id):Object.keys(names));
      setError('');setOpen(true);
    };
    const dispatch=async(action_id,argumentsValue={})=>{
      const request={request_id:'google_'+crypto.randomUUID(),action_id,arguments:argumentsValue};
      const receipt=await api.appActions.dispatch(request,{source:'ui'});
      if(receipt.status==='confirmation_required'){const current={request,receipt};pendingRef.current=current;setPending(current);return null;}
      if(receipt.status!=='applied')throw new Error(receipt.message||'Google connection could not be updated.');
      return receipt.result;
    };
    const install=async()=>{
      setBusy(true);setError('');
      try{
        const return_url=window.location.origin+window.location.pathname+(new URLSearchParams(window.location.search).get('desktop')==='1'?'?desktop=1':'');
        const result=await dispatch('google.connection.configure',{services:selected,return_url,force_signin:forceSignIn,open_browser:!!window.VellumDesktop?.invoke,access});
        if(result?.flow){setFlow(result.flow);setOpen(false);api.plugins.navigateToGoogle(result.flow);}
        else if(result?.connection){accept(result.connection);setOpen(false);onChanged?.();}
      }catch(err){setError(err.message);}finally{setBusy(false);}
    };
    const disconnect=async()=>{setBusy(true);setError('');try{await dispatch('google.connection.disconnect');}catch(err){setError(err.message);}finally{setBusy(false);}};
    const decide=async confirmed=>{if(!pending)return;setBusy(true);setError('');try{
      const receipt=confirmed?await api.appActions.confirm(pending.receipt.confirmation.token,pending.request,{source:'ui'}):await api.appActions.cancel(pending.receipt.confirmation.token,{source:'ui'});
      if(confirmed&&receipt.status!=='applied')throw new Error(receipt.message||'Google could not be disconnected.');
      pendingRef.current=null;setPending(null);if(confirmed){await refresh();onChanged?.();}
    }catch(err){setError(err.message);}finally{setBusy(false);}};
    const connected=status?.connected;
    const needsConsent=selected.some(id=>!status?.services?.find(item=>item.id===id)?.[access==='manage'?'can_write':'authorized']);
    return <section className="google-connections" aria-label="Google connection" aria-busy={busy}>
      <header className="google-connection-head"><span className="google-provider-mark"><img src="/design-uploads/assets/plugins/google.png" width="26" height="26" alt=""/></span><div><h2>{connected?'Your Google connection':'Connect your Google account'}</h2><p>{connected?(status.email||'Google account connected'):'Choose the services Vellum can use, then sign in with Google.'}</p></div></header>
      {status?<ul className="google-service-summary">{status.services.map(item=><li key={item.id}><img src={'/design-uploads/assets/plugins/'+marks[item.id]} width="22" height="22" alt=""/><span>{item.name}</span><small>{({connected:'Connected',disabled:'Off',needs_permission:'Permission needed',not_connected:'Not connected'})[item.status]}</small></li>)}</ul>:!error&&<p role="status">Checking your Google connection…</p>}
      {error&&!open&&<p className="plugins-error" role="alert">{error}</p>}
      {flow&&<div className="google-flow" role="status"><p>{flow.message||(flow.status==='pending'?'Waiting for Google sign-in…':'Google sign-in needs attention.')}</p>{flow.status==='pending'&&flow.authorization_url&&<a className="btn primary" href={flow.authorization_url} target="_blank" rel="noopener noreferrer">Continue to Google</a>}</div>}
      <div className="google-connection-actions"><button ref={trigger} className="btn primary" disabled={busy||!status||!!pending||flow?.status==='pending'} onClick={choose}>{connected?'Choose Google plugins':'Connect Google'}</button><button className="btn" disabled={busy} onClick={refresh}>Refresh status</button>{connected&&<React.Fragment>{status.services.some(item=>item.enabled&&!item.can_write)&&<button className="btn" disabled={busy||!!pending||flow?.status==='pending'} onClick={()=>{choose();setAccess('manage');}}>Enable changes</button>}<button className="btn" disabled={busy||!!pending||flow?.status==='pending'} onClick={()=>{choose();setForceSignIn(true);}}>Change account</button><button className="btn" disabled={busy||!!pending} onClick={disconnect}>Disconnect Google</button></React.Fragment>}</div>
      {status&&!status.configured&&<p className="google-connection-note">Vellum’s Google OAuth application needs to be configured before sign-in is available.</p>}
      <p className="google-connection-note">One account connection. Each service can be switched off independently in Vellum. Turning a service off keeps its existing Google permission; manage authorization in <a href="https://myaccount.google.com/connections" target="_blank" rel="noopener noreferrer">your Google account</a>.</p>
      <p className="google-connection-note">Read, create, send, edit, update and delete through the published Google APIs. Changes need the corresponding Google permission and an exact-operation review. {connected&&status.services.some(item=>item.enabled&&!item.can_write)&&'Your current grant has limited permissions; choose Enable changes to approve broader access.'}</p>
      <button className="btn" aria-expanded={browse} onClick={()=>setBrowse(value=>!value)}>{browse?'Hide API operations':'Browse API operations'}</button>{browse&&<GoogleOperations/>}
      {pending&&<div className="google-disconnect-review" role="group" aria-label="Confirm Google disconnection"><p>Disconnect this Google account from Vellum on this device? All four Google services will be switched off.</p><button className="btn" disabled={busy} onClick={()=>decide(false)}>Keep connected</button><button className="btn" disabled={busy} onClick={()=>decide(true)}>Confirm disconnect</button></div>}
      {open&&<dialog ref={dialog} className="google-plugin-dialog" aria-labelledby="google-chooser-title" onCancel={event=>{event.preventDefault();if(!busy)setOpen(false);}}>
        <button className="google-dialog-close" type="button" aria-label="Close Google plugin selection" disabled={busy} onClick={()=>setOpen(false)}>×</button>
        <div className="google-dialog-provider" aria-hidden="true"><span>v</span><span>···</span><img src="/design-uploads/assets/plugins/google.png" width="42" height="42" alt=""/></div>
        <h2 id="google-chooser-title">Choose Google plugins to install</h2><p className="google-dialog-intro">One sign-in. Your choice of services.<br/>You can change these anytime in Settings.</p>
        <fieldset disabled={busy}><legend className="google-visually-hidden">Google services</legend>{Object.keys(names).map(id=><label className="google-choice" key={id}><span className="google-choice-mark"><img src={'/design-uploads/assets/plugins/'+marks[id]} width="30" height="30" alt=""/></span><span className="google-choice-copy"><strong>{names[id]}</strong><small>{(access==='manage'?manageDescriptions:descriptions)[id]}</small></span><input type="checkbox" role="switch" checked={selected.includes(id)} onChange={event=>setSelected(current=>event.target.checked?[...current,id]:current.filter(item=>item!==id))}/></label>)}</fieldset>
        <label className="google-access-choice">Access for selected services<select aria-label="Access for selected services" disabled={busy} value={access} onChange={event=>setAccess(event.target.value)}><option value="read">Current read access</option><option value="manage">Read, create, send, edit and delete</option></select></label>
        {access==='manage'&&<p className="google-selection-note">Includes sending email, editing files and contacts, and permanent deletion. Google will show the exact permissions. Each change still requires a review in Vellum.</p>}
        {error&&<p className="plugins-error" role="alert">{error}</p>}
        <p className="google-selection-note">{forceSignIn?'Choose your preferred Google account and approve the selected services.':needsConsent?'Google will ask you to approve access to the selected services.':'Your existing Google authorization covers this selection.'}</p>
        <button className="google-install-button" disabled={busy} onClick={install}>{busy?'Preparing connection…':selected.length?'Install selected plugins':'Save with all services off'}</button>
      </dialog>}
    </section>;
  }
  window.VellumUI=window.VellumUI||{};window.VellumUI.GoogleConnections=GoogleConnections;window.VellumUI.GoogleActionReview=GoogleActionReview;
})();
