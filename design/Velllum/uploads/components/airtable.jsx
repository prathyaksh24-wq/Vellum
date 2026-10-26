(function () {
  const {useEffect,useRef,useState}=React;
  function AirtableConnection({enabled=true,onChanged}) {
    const api=window.VellumApi;
    const [status,setStatus]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
    const [flow,setFlow]=useState(()=>{const id=new URLSearchParams(location.search).get('airtable_oauth');return id?{flow_id:id,status:'pending',message:'Checking Airtable sign-in…'}:null;});
    const [pending,setPending]=useState(null),[tools,setTools]=useState(null),[query,setQuery]=useState('');
    const mounted=useRef(false),popupRef=useRef(null),pendingRef=useRef(null);
    const refresh=async()=>{const value=await api.plugins.airtableStatus();if(mounted.current)setStatus(value);return value;};
    useEffect(()=>{mounted.current=true;refresh().catch(err=>{if(mounted.current)setError(err.message);});return()=>{mounted.current=false;const value=pendingRef.current;if(value)api.appActions.cancel(value.receipt.confirmation.token,{source:'ui'}).catch(()=>{});};},[enabled]);
    useEffect(()=>{
      if(flow?.status!=='pending'||!flow.flow_id)return;
      let stopped=false,checking=false;
      const poll=async()=>{if(checking)return;checking=true;try{const value=await api.plugins.airtableOAuthStatus(flow.flow_id);if(!stopped){setError('');setFlow(previous=>({...previous,...value}));if(value.status!=='pending'){try{popupRef.current?.close();}catch{}popupRef.current=null;window.focus();const url=new URL(location.href);url.searchParams.delete('airtable_oauth');history.replaceState(history.state,'',url);await refresh();onChanged?.();}}}catch(err){if(!stopped){if(err.status===400){setFlow(previous=>({...previous,status:'failed',message:'Airtable sign-in expired. Start again.'}));setError(err.message);}else setError('Airtable status is temporarily unavailable. Vellum will keep checking the local server.');}}finally{checking=false;}};
      const completed=event=>{const expected=new URL(api.plugins.airtableOAuthWindowUrl(flow.flow_id));if(event.origin===expected.origin&&event.source===popupRef.current&&event.data?.type==='vellum:airtable:oauth'&&event.data.flow_id===flow.flow_id)poll();};
      window.addEventListener('message',completed);poll();const timer=setInterval(poll,1500);return()=>{stopped=true;clearInterval(timer);window.removeEventListener('message',completed);};
    },[flow?.flow_id,flow?.status]);
    const dispatch=async(action_id,args={})=>{
      const request={request_id:'airtable_'+crypto.randomUUID(),action_id,arguments:args};
      const receipt=await api.appActions.dispatch(request,{source:'ui'});
      if(!mounted.current){if(receipt.confirmation)await api.appActions.cancel(receipt.confirmation.token,{source:'ui'}).catch(()=>{});return;}
      if(receipt.status==='confirmation_required'){const value={request,receipt};pendingRef.current=value;setPending(value);return;}
      if(receipt.status!=='applied')throw new Error(receipt.message||'Airtable did not complete this action.');
      if(receipt.result?.connection)setStatus(receipt.result.connection);
      return receipt.result;
    };
    const run=async(action,args={})=>{setBusy(true);setError('');try{const result=await dispatch(action,args);await refresh();onChanged?.();return result;}catch(err){if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}};
    const connect=async()=>{
      const desktop=window.VellumDesktop?.runtime==='electron';
      const popup=desktop?null:window.open('about:blank','vellum-airtable-oauth','popup,width=680,height=780');popupRef.current=popup;
      setBusy(true);setError('');
      try{const returnUrl=location.origin+location.pathname+(new URLSearchParams(location.search).get('desktop')==='1'?'?desktop=1':'');const result=await dispatch('airtable.connection.oauth.start',{return_url:returnUrl,popup:true});if(result){const target=new URL(result.authorization_url);if(target.origin!=='https://airtable.com'||target.pathname!=='/oauth2/v1/authorize')throw new Error('Airtable returned an invalid sign-in address.');setFlow({...result,status:'pending'});if(desktop)popupRef.current=window.open(api.plugins.airtableOAuthWindowUrl(result.flow_id),'vellum-airtable-oauth','popup,width=680,height=780');else if(popup)popup.location.href=target.href;}else popup?.close();}
      catch(err){popup?.close();popupRef.current=null;if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}
    };
    const decide=async confirm=>{if(!pending)return;setBusy(true);setError('');const value=pending;try{const receipt=confirm?await api.appActions.confirm(value.receipt.confirmation.token,value.request,{source:'ui'}):await api.appActions.cancel(value.receipt.confirmation.token,{source:'ui'});if(confirm&&receipt.status!=='applied')throw new Error(receipt.message||'Airtable did not complete this action.');await refresh();onChanged?.();}catch(err){if(mounted.current)setError(err.message);}finally{pendingRef.current=null;if(mounted.current){setPending(null);setBusy(false);}}};
    const browse=async()=>{setBusy(true);setError('');try{const result=await api.plugins.airtableMcpTools(true);if(mounted.current)setTools(result.tools);await refresh();}catch(err){if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}};
    const connected=enabled&&status?.connected;
    const filtered=tools?.filter(tool=>(tool.name+' '+tool.description).toLowerCase().includes(query.toLowerCase()));
    return <section className="product-hunt-workspace airtable-workspace" aria-label="Airtable connection" aria-busy={busy}>
      <div className="product-hunt-summary"><div><h2>{connected?'Connected to Airtable':'Connect Airtable'}</h2><p>{status?.message||'Checking Airtable connection…'}</p></div><img src="/design-uploads/assets/plugins/airtable.svg" alt="Airtable" width="32" height="32"/></div>
      <p className="product-hunt-privacy">Work with bases, tables, records, comments, interfaces and automations through Airtable’s official MCP server. Choose the resources Vellum can access during sign-in. Changes get a readable review before they run.</p>
      {connected&&<p className="linear-identity">Account: {status.account_name} · {status.mcp_tool_count} published tools</p>}
      <div className="product-hunt-actions"><button className="btn primary" disabled={!enabled||!status||busy||!!pending||flow?.status==='pending'} onClick={connect}>{busy&&!flow?'Connecting…':status?.configured?'Reconnect with Airtable':'Sign in with Airtable'}</button>
        {status?.configured&&<><button className="btn" disabled={!enabled||busy||!!pending} onClick={()=>run('airtable.connection.verify')}>Verify connection</button><button className="btn" disabled={!enabled||busy||!!pending} onClick={()=>run('airtable.connection.disconnect')}>Disconnect</button></>}
      </div>
      {!enabled&&<p>Enable Airtable in the plugin controls to connect.</p>}
      {flow&&<div role="status"><p>{flow.message}</p>{flow.status==='pending'&&<>{flow.authorization_url&&<a className="btn primary" href={api.plugins.airtableOAuthWindowUrl(flow.flow_id)} target="vellum-airtable-oauth" rel="noopener noreferrer">Continue to Airtable ↗</a>}<button className="btn" disabled={busy} onClick={()=>run('airtable.connection.oauth.cancel',{flow_id:flow.flow_id})}>Cancel sign-in</button></>}</div>}
      {pending&&<div className="plugin-setup-review" role="group" aria-label="Review Airtable disconnection"><h3>Disconnect Airtable?</h3><p>Remove Vellum’s saved Airtable authorization from this device. Its public app registration stays available for reconnection. You can also revoke its grant in Airtable’s third-party integrations.</p><button className="btn" disabled={busy} onClick={()=>decide(false)}>Cancel</button><button className="btn primary" disabled={busy} onClick={()=>decide(true)}>Confirm disconnect</button></div>}
      {error&&<p className="plugins-error" role="alert">{error}</p>}
      <p className="product-hunt-privacy">Authorization stays in this device’s system credential store. No API key or developer app setup is needed.</p>
      <div className="product-hunt-links"><a href="https://airtable.com/developers/agents/mcp/getting-started" target="_blank" rel="noopener noreferrer">Official source and tool coverage ↗</a><a href="https://airtable.com/?integrations=thirdParty" target="_blank" rel="noopener noreferrer">Manage Airtable access ↗</a></div>
      <details className="linear-coverage"><summary>Tools provided by Airtable</summary><p>Browse the complete catalog published for your connection, with original descriptions and schemas. Airtable’s resource permissions apply to every operation.</p><button className="btn" disabled={!enabled||!status?.configured||busy||!!pending} onClick={browse}>{tools?'Refresh tools':'Browse tools'}</button>
        {tools&&<><label>Find a tool<input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Records, tables, automations…"/></label>{filtered.length===0?<p>No tools match this search.</p>:<ul className="linear-operations">{filtered.map(tool=><li key={tool.name}><details><summary><img src="/design-uploads/assets/plugins/airtable.svg" alt="" width="16" height="16"/>{' '}{tool.name} · {tool.read_only?'Read':'Review required'}</summary><p>{tool.description}</p><pre>{JSON.stringify(tool.input_schema,null,2)}</pre></details></li>)}</ul>}</>}
      </details>
    </section>;
  }
  window.VellumUI=window.VellumUI||{};window.VellumUI.AirtableConnection=AirtableConnection;
})();
