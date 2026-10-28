(function () {
  const {useEffect,useRef,useState}=React;
  function AsanaConnection({enabled=true,onChanged,render}) {
    const api=window.VellumApi;
    const [status,setStatus]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
    const [flow,setFlow]=useState(()=>{const id=new URLSearchParams(location.search).get('asana_oauth');return id?{flow_id:id,status:'pending',message:'Checking Asana sign-in…'}:null;});
    const [pending,setPending]=useState(null),[tools,setTools]=useState(null),[query,setQuery]=useState('');
    const [clientId,setClientId]=useState(''),[clientSecret,setClientSecret]=useState('');
    const mounted=useRef(false),popupRef=useRef(null),pendingRef=useRef(null),stagedRef=useRef(null);
    const refresh=async()=>{const value=await api.plugins.asanaStatus();if(mounted.current)setStatus(value);return value;};
    useEffect(()=>{mounted.current=true;refresh().catch(err=>{if(mounted.current)setError(err.message);});return()=>{mounted.current=false;const value=pendingRef.current;if(value)api.appActions.cancel(value.receipt.confirmation.token,{source:'ui'}).catch(()=>{});if(stagedRef.current)api.plugins.asanaDiscard(stagedRef.current).catch(()=>{});};},[enabled]);
    useEffect(()=>{
      if(flow?.status!=='pending'||!flow.flow_id)return;
      let stopped=false,checking=false;
      const poll=async()=>{if(checking)return;checking=true;try{const value=await api.plugins.asanaOAuthStatus(flow.flow_id);if(!stopped){setError('');setFlow(previous=>({...previous,...value}));if(value.status!=='pending'){try{popupRef.current?.close();}catch{}popupRef.current=null;window.focus();const url=new URL(location.href);url.searchParams.delete('asana_oauth');history.replaceState(history.state,'',url);await refresh();onChanged?.();}}}catch(err){if(!stopped){if(err.status===400){setFlow(previous=>({...previous,status:'failed',message:'Asana sign-in expired. Start again.'}));setError(err.message);}else setError('Asana status is temporarily unavailable. Vellum will keep checking the local server.');}}finally{checking=false;}};
      const completed=event=>{const expected=new URL(api.plugins.asanaOAuthWindowUrl(flow.flow_id));if(event.origin===expected.origin&&event.source===popupRef.current&&event.data?.type==='vellum:asana:oauth'&&event.data.flow_id===flow.flow_id)poll();};
      window.addEventListener('message',completed);poll();const timer=setInterval(poll,1500);return()=>{stopped=true;clearInterval(timer);window.removeEventListener('message',completed);};
    },[flow?.flow_id,flow?.status]);
    const dispatch=async(action_id,args={})=>{
      const request={request_id:'asana_'+crypto.randomUUID(),action_id,arguments:args};
      const receipt=await api.appActions.dispatch(request,{source:'ui'});
      if(!mounted.current){if(receipt.confirmation)await api.appActions.cancel(receipt.confirmation.token,{source:'ui'}).catch(()=>{});return;}
      if(receipt.status==='confirmation_required'){const value={request,receipt};pendingRef.current=value;setPending(value);return;}
      if(receipt.status!=='applied')throw new Error(receipt.message||'Asana did not complete this action.');
      if(receipt.result?.connection)setStatus(receipt.result.connection);
      return receipt.result;
    };
    const run=async(action,args={})=>{setBusy(true);setError('');try{const result=await dispatch(action,args);await refresh();onChanged?.();return result;}catch(err){if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}};
    const reviewSetup=async()=>{
      setBusy(true);setError('');
      try{
        const staged=await api.plugins.asanaStage({client_id:clientId.trim(),client_secret:clientSecret.trim()});
        stagedRef.current=staged.credential_id;
        if(!mounted.current){await api.plugins.asanaDiscard(staged.credential_id);return;}
        setClientSecret('');
        await dispatch('asana.connection.configure',{credential_id:staged.credential_id});
      }catch(err){if(stagedRef.current)await api.plugins.asanaDiscard(stagedRef.current).catch(()=>{});stagedRef.current=null;if(mounted.current)setError(err.message);}
      finally{if(mounted.current)setBusy(false);}
    };
    const connect=async()=>{
      const desktop=window.VellumDesktop?.runtime==='electron';
      const popup=desktop?null:window.open('about:blank','vellum-asana-oauth','popup,width=680,height=780');popupRef.current=popup;
      setBusy(true);setError('');
      try{const returnUrl=location.origin+location.pathname+(new URLSearchParams(location.search).get('desktop')==='1'?'?desktop=1':'');const result=await dispatch('asana.connection.oauth.start',{return_url:returnUrl,popup:true});if(result){const target=new URL(result.authorization_url);if(target.origin!=='https://app.asana.com'||target.pathname!=='/-/oauth_authorize')throw new Error('Asana returned an invalid sign-in address.');setFlow({...result,status:'pending'});if(desktop)popupRef.current=window.open(api.plugins.asanaOAuthWindowUrl(result.flow_id),'vellum-asana-oauth','popup,width=680,height=780');else if(popup)popup.location.href=target.href;}else popup?.close();}
      catch(err){popup?.close();popupRef.current=null;if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}
    };
    const decide=async confirm=>{if(!pending)return;setBusy(true);setError('');const value=pending;try{const receipt=confirm?await api.appActions.confirm(value.receipt.confirmation.token,value.request,{source:'ui'}):await api.appActions.cancel(value.receipt.confirmation.token,{source:'ui'});if(confirm&&receipt.status!=='applied')throw new Error(receipt.message||'Asana did not complete this action.');await refresh();onChanged?.();}catch(err){if(mounted.current)setError(err.message);}finally{if(stagedRef.current)await api.plugins.asanaDiscard(stagedRef.current).catch(()=>{});stagedRef.current=null;pendingRef.current=null;if(mounted.current){setPending(null);setBusy(false);}}};
    const browse=async()=>{setBusy(true);setError('');try{const result=await api.plugins.asanaMcpTools(true);if(mounted.current)setTools(result.tools);await refresh();}catch(err){if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}};
    const connected=enabled&&status?.connected;
    const filtered=tools?.filter(tool=>(tool.name+' '+tool.description).toLowerCase().includes(query.toLowerCase()));
    if(render)return render({status,busy,error,pending,tools,browse,run,connect,decide,flow,clientId,setClientId,clientSecret,setClientSecret,reviewSetup});
    return <section className="product-hunt-workspace asana-workspace" aria-label="Asana connection" aria-busy={busy}>
      <div className="product-hunt-summary"><div><h2>{connected?'Connected to Asana':'Connect Asana'}</h2><p>{status?.message||'Checking Asana connection…'}</p></div><img className="conn-logo-img" src="/design-uploads/assets/plugins/asana.svg" alt="Asana" width="32" height="32"/></div>
      <p className="product-hunt-privacy">Search and manage tasks, projects and the other operations published by Asana’s official V2 MCP server. Changes get a readable review; your workspace permissions apply.</p>
      <details className="linear-coverage" open={!status?.app_registered}>
        <summary>Set up your Asana app</summary>
        <p>In the Asana developer console, create an app named Vellum and choose Asana MCP. Register this exact redirect URL:</p>
        <p><code>http://localhost:8000/api/plugins/asana/oauth/callback</code></p>
        <p><a href="https://app.asana.com/0/my-apps" target="_blank" rel="noopener noreferrer">Open Asana developer console ↗</a></p>
        <p>Under Manage distribution, allow the intended workspace and save. Enter the app’s client ID and secret here. Only an expiring reference enters the setup review; credentials stay out of chat and action history.</p>
        <label>Client ID<input value={clientId} onChange={event=>setClientId(event.target.value)} disabled={!enabled||busy||!!pending||status?.configured||flow?.status==='pending'} autoComplete="off" spellCheck={false}/></label>
        <label>Client secret<input type="password" value={clientSecret} onChange={event=>setClientSecret(event.target.value)} disabled={!enabled||busy||!!pending||status?.configured||flow?.status==='pending'} autoComplete="new-password" spellCheck={false}/></label>
        <button className="btn" disabled={!enabled||busy||!!pending||status?.configured||!clientId.trim()||!clientSecret.trim()||flow?.status==='pending'} onClick={reviewSetup}>Review app setup</button>
        {status?.configured&&<p>Disconnect Asana before replacing its app credentials.</p>}
      </details>
      {connected&&<p className="linear-identity">{status.account_name} · OAuth · {status.mcp_tool_count} published tools</p>}
      <div className="product-hunt-actions"><button className="btn primary" disabled={!enabled||!status?.oauth_available||busy||!!pending||flow?.status==='pending'} onClick={connect}>{busy&&!flow?'Connecting…':status?.auth_type==='oauth'?'Reconnect with Asana':'Sign in with Asana'}</button>
        {status?.configured&&<><button className="btn" disabled={!enabled||busy||!!pending} onClick={()=>run('asana.connection.verify')}>Verify connection</button><button className="btn" disabled={!enabled||busy||!!pending} onClick={()=>run('asana.connection.disconnect')}>Disconnect</button></>}
      </div>
      <p className="product-hunt-privacy">After saving app setup, sign in and select the Asana account you want Vellum to use. Asana determines the permissions available during installation.</p>
      {!enabled&&<p>Enable Asana in the plugin controls to connect.</p>}
      {flow&&<div role="status"><p>{flow.message}</p>{flow.status==='pending'&&<>{flow.authorization_url&&<a className="btn primary" href={api.plugins.asanaOAuthWindowUrl(flow.flow_id)} target="vellum-asana-oauth" rel="noopener noreferrer">Continue to Asana ↗</a>}<button className="btn" disabled={busy} onClick={()=>run('asana.connection.oauth.cancel',{flow_id:flow.flow_id})}>Cancel sign-in</button></>}</div>}
      {pending&&<div className="plugin-setup-review" role="group" aria-label="Review Asana connection change"><h3>{pending.request.action_id==='asana.connection.configure'?'Save Asana app setup?':'Disconnect Asana?'}</h3><p>{pending.request.action_id==='asana.connection.configure'?'Save the entered app credentials in this device’s system credential store. Account access will be reviewed separately on Asana.':'Remove Vellum’s saved Asana account authorization from this device. Its app setup stays available for reconnection. You can also revoke its grant in Asana’s connected app settings.'}</p><button className="btn" disabled={busy} onClick={()=>decide(false)}>Cancel</button><button className="btn primary" disabled={busy} onClick={()=>decide(true)}>{pending.request.action_id==='asana.connection.configure'?'Save app setup':'Confirm disconnect'}</button></div>}
      {error&&<p className="plugins-error" role="alert">{error}</p>}
      <p className="product-hunt-privacy">Authorization stays in this device’s system credential store. Each user signs in with their own Asana account.</p>
      {connected&&!status.identity_verified&&<p className="product-hunt-privacy">Access is bound to your saved Asana authorization. Choose the intended account on Asana; the connection check does not read task content or claim a verified person identity.</p>}
      <div className="product-hunt-links"><a href="https://developers.asana.com/docs/integrating-with-asanas-mcp-server" target="_blank" rel="noopener noreferrer">Official source and tool coverage ↗</a><a href="https://app.asana.com" target="_blank" rel="noopener noreferrer">Open Asana account ↗</a></div>
      <details className="linear-coverage"><summary>Tools provided by Asana</summary><p>Browse the complete catalog published for your connection, with original descriptions and schemas. Asana’s account permissions and plan limits apply to every operation.</p><button className="btn" disabled={!enabled||!status?.configured||busy||!!pending} onClick={browse}>{tools?'Refresh tools':'Browse tools'}</button>
        {tools&&<><label>Find a tool<input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Search operations…"/></label>{filtered.length===0?<p>No tools match this search.</p>:<ul className="linear-operations">{filtered.map(tool=><li key={tool.name}><details><summary><img className="conn-logo-img" src="/design-uploads/assets/plugins/asana.svg" alt="" width="16" height="16"/>{' '}{tool.name} · {tool.read_only?'Read':'Review required'}</summary><p>{tool.description}</p><pre>{JSON.stringify(tool.input_schema,null,2)}</pre></details></li>)}</ul>}</>}
      </details>
    </section>;
  }
  window.VellumUI=window.VellumUI||{};window.VellumUI.AsanaConnection=AsanaConnection;
})();
