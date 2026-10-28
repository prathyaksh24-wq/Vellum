(function () {
  const {useEffect,useRef,useState}=React;
  function SwiggyConnection({enabled=true,onChanged,render}) {
    const api=window.VellumApi;
    const [status,setStatus]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
    const [flow,setFlow]=useState(()=>{const id=new URLSearchParams(location.search).get('swiggy_oauth');return id?{flow_id:id,status:'pending',message:'Checking Swiggy sign-in…'}:null;});
    const [pending,setPending]=useState(null),[tools,setTools]=useState(null),[query,setQuery]=useState('');
    const mounted=useRef(false),popupRef=useRef(null),pendingRef=useRef(null);
    const refresh=async()=>{const value=await api.plugins.swiggyStatus();if(mounted.current)setStatus(value);return value;};
    useEffect(()=>{mounted.current=true;refresh().catch(err=>{if(mounted.current)setError(err.message);});return()=>{mounted.current=false;const value=pendingRef.current;if(value)api.appActions.cancel(value.receipt.confirmation.token,{source:'ui'}).catch(()=>{});};},[enabled]);
    useEffect(()=>{
      if(flow?.status!=='pending'||!flow.flow_id)return;
      let stopped=false,checking=false;
      const poll=async()=>{if(checking)return;checking=true;try{const value=await api.plugins.swiggyOAuthStatus(flow.flow_id);if(!stopped){setError('');setFlow(previous=>({...previous,...value}));if(value.status!=='pending'){try{popupRef.current?.close();}catch{}popupRef.current=null;window.focus();const url=new URL(location.href);url.searchParams.delete('swiggy_oauth');history.replaceState(history.state,'',url);await refresh();onChanged?.();}}}catch(err){if(!stopped){if(err.status===400){setFlow(previous=>({...previous,status:'failed',message:'Swiggy sign-in expired. Start again.'}));setError(err.message);}else setError('Swiggy status is temporarily unavailable. Vellum will keep checking the local server.');}}finally{checking=false;}};
      const completed=event=>{const expected=new URL(api.plugins.swiggyOAuthWindowUrl(flow.flow_id));if(event.origin===expected.origin&&event.source===popupRef.current&&event.data?.type==='vellum:swiggy:oauth'&&event.data.flow_id===flow.flow_id)poll();};
      window.addEventListener('message',completed);poll();const timer=setInterval(poll,1500);return()=>{stopped=true;clearInterval(timer);window.removeEventListener('message',completed);};
    },[flow?.flow_id,flow?.status]);
    const dispatch=async(action_id,args={})=>{
      const request={request_id:'swiggy_'+crypto.randomUUID(),action_id,arguments:args};
      const receipt=await api.appActions.dispatch(request,{source:'ui'});
      if(!mounted.current){if(receipt.confirmation)await api.appActions.cancel(receipt.confirmation.token,{source:'ui'}).catch(()=>{});return;}
      if(receipt.status==='confirmation_required'){const value={request,receipt};pendingRef.current=value;setPending(value);return;}
      if(receipt.status!=='applied')throw new Error(receipt.message||'Swiggy did not complete this action.');
      if(receipt.result?.connection)setStatus(receipt.result.connection);if(action_id==='swiggy.connection.configure')setTools(null);
      return receipt.result;
    };
    const run=async(action,args={})=>{setBusy(true);setError('');try{const result=await dispatch(action,args);await refresh();onChanged?.();return result;}catch(err){if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}};
    const connect=async()=>{
      const desktop=window.VellumDesktop?.runtime==='electron';
      const popup=desktop?null:window.open('about:blank','vellum-swiggy-oauth','popup,width=680,height=780');popupRef.current=popup;
      setBusy(true);setError('');
      try{const returnUrl=location.origin+location.pathname+(new URLSearchParams(location.search).get('desktop')==='1'?'?desktop=1':'');const result=await dispatch('swiggy.connection.oauth.start',{return_url:returnUrl,popup:true});if(result){const target=new URL(result.authorization_url);if(target.origin!=='https://mcp.swiggy.com'||target.pathname!=='/auth/authorize')throw new Error('Swiggy returned an invalid sign-in address.');setFlow({...result,status:'pending'});if(desktop)popupRef.current=window.open(api.plugins.swiggyOAuthWindowUrl(result.flow_id),'vellum-swiggy-oauth','popup,width=680,height=780');else if(popup)popup.location.href=target.href;}else popup?.close();}
      catch(err){popup?.close();popupRef.current=null;if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}
    };
    const decide=async confirm=>{if(!pending)return;setBusy(true);setError('');const value=pending;try{const receipt=confirm?await api.appActions.confirm(value.receipt.confirmation.token,value.request,{source:'ui'}):await api.appActions.cancel(value.receipt.confirmation.token,{source:'ui'});if(confirm&&receipt.status!=='applied')throw new Error(receipt.message||'Swiggy did not complete this action.');await refresh();onChanged?.();}catch(err){if(mounted.current)setError(err.message);}finally{pendingRef.current=null;if(mounted.current){setPending(null);setBusy(false);}}};
    const browse=async()=>{setBusy(true);setError('');try{const result=await api.plugins.swiggyMcpTools(true);if(mounted.current)setTools(result.tools);await refresh();}catch(err){if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}};
    const connected=enabled&&status?.connected;
    const filtered=tools?.filter(tool=>(tool.name+' '+tool.description).toLowerCase().includes(query.toLowerCase()));
    if(render)return render({status,busy,error,pending,tools,browse,run,connect,decide,flow});
    return <section className="product-hunt-workspace swiggy-workspace" aria-label="Swiggy connection" aria-busy={busy}>
      <div className="product-hunt-summary"><div><h2>{connected?'Swiggy & Instamart':'Connect Swiggy'}</h2><p>{status?.message||'Checking Swiggy connection…'}</p></div><img className="conn-logo-img " src="/design-uploads/assets/plugins/swiggy.png" alt="Swiggy" width="32" height="32"/></div>
      <p className="product-hunt-privacy">Discover food and groceries, manage your selected carts and follow deliveries through Swiggy’s official Food and Instamart servers. Cart changes and orders get a readable review.</p>
      <fieldset className="swiggy-services" disabled={!enabled||!status||busy||!!pending||flow?.status==='pending'}><legend>Choose Swiggy services</legend>
        {status?.services?.map(item=><label className="swiggy-service" key={item.id}><span className="swiggy-service-mark"><img src={'/design-uploads/assets/plugins/'+(item.id==='instamart'?'swiggy-instamart.png':'swiggy.png')} width="30" height="30" alt=""/></span><span className="swiggy-service-copy"><strong>{item.name}</strong><small>{item.id==='food'?'Restaurants, menus, food carts and delivery':'Groceries, essentials, carts and delivery'}</small></span><input type="checkbox" className="swiggy-service-switch" role="switch" aria-label={item.name} checked={item.enabled} onChange={event=>run('swiggy.connection.configure',{services:status.services.filter(value=>value.id===item.id?event.target.checked:value.enabled).map(value=>value.id)})}/></label>)}
      </fieldset>
      {connected&&<p className="linear-identity">{status.account_name} · OAuth · {status.mcp_tool_count} published tools</p>}
      <div className="product-hunt-actions"><button className="btn primary" disabled={!enabled||!status||!status.services?.some(item=>item.enabled)||busy||!!pending||flow?.status==='pending'} onClick={connect}>{busy&&!flow?'Connecting…':status?.auth_type==='oauth'?'Reconnect with Swiggy':'Sign in with Swiggy'}</button>
        {status?.configured&&<><button className="btn" disabled={!enabled||busy||!!pending} onClick={()=>run('swiggy.connection.verify')}>Verify connection</button><button className="btn" disabled={!enabled||busy||!!pending} onClick={()=>run('swiggy.connection.disconnect')}>Disconnect</button></>}
      </div>
      {!enabled&&<p>Enable Swiggy in the plugin controls to connect.</p>}
      {flow&&<div role="status"><p>{flow.message}</p>{flow.status==='pending'&&<>{flow.authorization_url&&<a className="btn primary" href={api.plugins.swiggyOAuthWindowUrl(flow.flow_id)} target="vellum-swiggy-oauth" rel="noopener noreferrer">Continue to Swiggy ↗</a>}<button className="btn" disabled={busy} onClick={()=>run('swiggy.connection.oauth.cancel',{flow_id:flow.flow_id})}>Cancel sign-in</button></>}</div>}
      {pending&&<div className="plugin-setup-review" role="group" aria-label="Review Swiggy disconnection"><h3>Disconnect Swiggy?</h3><p>Remove Vellum’s saved Swiggy authorization from this device. Its public app registration stays available for reconnection. You can also revoke its grant in Swiggy’s connection settings.</p><button className="btn" disabled={busy} onClick={()=>decide(false)}>Cancel</button><button className="btn primary" disabled={busy} onClick={()=>decide(true)}>Confirm disconnect</button></div>}
      {error&&<p className="plugins-error" role="alert">{error}</p>}
      <p className="product-hunt-privacy">Authorization stays in this device’s system credential store. Each user signs in with their own Swiggy account.</p>
      <div className="product-hunt-links"><a href="https://mcp.swiggy.com/builders/docs/start/authenticate/" target="_blank" rel="noopener noreferrer">Official source and tool coverage ↗</a><a href="https://www.swiggy.com" target="_blank" rel="noopener noreferrer">Open Swiggy account ↗</a></div>
      <details className="linear-coverage"><summary>Tools provided by Swiggy</summary><p>Browse the complete catalog published for your connection, with original descriptions and schemas. Food and Instamart tools are identified by service. Checkout requires a current cart, chosen destination and payment method, followed by your review.</p><button className="btn" disabled={!enabled||!status?.configured||busy||!!pending} onClick={browse}>{tools?'Refresh tools':'Browse tools'}</button>
        {tools&&<><label>Find a tool<input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Search operations…"/></label>{filtered.length===0?<p>No tools match this search.</p>:<ul className="linear-operations">{filtered.map(tool=><li key={tool.name}><details><summary><img className="conn-logo-img " src={'/design-uploads/assets/plugins/'+(tool.service==='instamart'?'swiggy-instamart.png':'swiggy.png')} alt="" width="16" height="16"/>{' '}{tool.name} · {tool.read_only?'Read':'Review required'}</summary><p>{tool.description}</p><pre>{JSON.stringify(tool.input_schema,null,2)}</pre></details></li>)}</ul>}</>}
      </details>
    </section>;
  }
  window.VellumUI=window.VellumUI||{};window.VellumUI.SwiggyConnection=SwiggyConnection;
})();
