(function () {
  const {useEffect,useRef,useState}=React;
  function SerpApiConnection({enabled=true,onChanged}) {
    const api=window.VellumApi;
    const [status,setStatus]=useState(null),[key,setKey]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
    const [pending,setPending]=useState(null),[tools,setTools]=useState(null),[query,setQuery]=useState('');
    const mounted=useRef(false),pendingRef=useRef(null);
    const refresh=async()=>{const value=await api.plugins.serpapiStatus();if(mounted.current)setStatus(value);};
    useEffect(()=>{mounted.current=true;refresh().catch(err=>{if(mounted.current)setError(err.message);});return()=>{mounted.current=false;const value=pendingRef.current;if(value)api.appActions.cancel(value.receipt.confirmation.token,{source:'ui'}).catch(()=>{});};},[enabled]);
    const dispatch=async(action_id,args={})=>{
      const request={request_id:'serpapi_'+crypto.randomUUID(),action_id,arguments:args};
      const receipt=await api.appActions.dispatch(request,{source:'ui'});
      if(!mounted.current){if(receipt.confirmation)await api.appActions.cancel(receipt.confirmation.token,{source:'ui'}).catch(()=>{});return;}
      if(receipt.status==='confirmation_required'){const value={request,receipt};pendingRef.current=value;setPending(value);return;}
      if(receipt.status!=='applied')throw new Error(receipt.message||'SerpAPI did not complete this action.');
      return receipt.result;
    };
    const run=async(action,args={})=>{setBusy(true);setError('');try{await dispatch(action,args);await refresh();onChanged?.();}catch(err){if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}};
    const connect=async event=>{
      event.preventDefault();setBusy(true);setError('');let reference;
      try {
        const staged=await api.plugins.serpapiStage(key);reference=staged.credential_id;setKey('');
        await dispatch('serpapi.connection.connect',{credential_id:reference});await refresh();onChanged?.();
      } catch(err) {if(mounted.current)setError(err.message);} finally {
        if(reference)await api.plugins.serpapiDiscard(reference).catch(()=>{});
        if(mounted.current)setBusy(false);
      }
    };
    const decide=async confirm=>{if(!pending)return;setBusy(true);setError('');const value=pending;try{const receipt=confirm?await api.appActions.confirm(value.receipt.confirmation.token,value.request,{source:'ui'}):await api.appActions.cancel(value.receipt.confirmation.token,{source:'ui'});if(confirm&&receipt.status!=='applied')throw new Error(receipt.message||'SerpAPI did not disconnect.');await refresh();onChanged?.();}catch(err){if(mounted.current)setError(err.message);}finally{pendingRef.current=null;if(mounted.current){setPending(null);setBusy(false);}}};
    const browse=async()=>{setBusy(true);setError('');try{const value=await api.plugins.serpapiMcpTools(true);if(mounted.current)setTools(value.tools);await refresh();}catch(err){if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}};
    const connected=enabled&&status?.connected;
    const filtered=tools?.filter(tool=>(tool.name+' '+tool.description).toLowerCase().includes(query.toLowerCase()));
    return <><window.VellumUI.WebSearchSettings/><section className="product-hunt-workspace" aria-label="SerpAPI connection" aria-busy={busy}>
      <div className="product-hunt-summary"><div><h2>{connected?'Connected to SerpAPI':'Connect SerpAPI'}</h2><p>{status?.message||'Checking SerpAPI connection…'}</p></div><img src="/design-uploads/assets/plugins/serpapi.png" alt="SerpAPI" width="32" height="32"/></div>
      <p className="product-hunt-privacy">Search Google, YouTube, news, shopping and other supported engines. Vellum’s existing web search and the official MCP tools share this saved key. SerpAPI currently uses API-key authentication.</p>
      {connected&&<p className="linear-identity">{status.account_name} · API key · {status.mcp_tool_count} published tools</p>}
      <form onSubmit={connect}><label>SerpAPI key<input type="password" autoComplete="off" spellCheck={false} value={key} onChange={event=>setKey(event.target.value)} disabled={!enabled||busy||!!pending} placeholder="Enter your key from the SerpAPI dashboard"/></label><button type="submit" className="btn primary" disabled={!enabled||!status||busy||!!pending||!key.trim()}>{busy?'Connecting…':status?.configured?'Replace key':'Connect SerpAPI'}</button></form>
      <div className="product-hunt-actions">
        {status?.configured_key_available&&status.auth_type!=='configured_api_key'&&<button className="btn" disabled={!enabled||busy||!!pending} onClick={()=>run('serpapi.connection.use_configured')}>Use configured API key</button>}
        {status?.configured&&<><button className="btn" disabled={!enabled||busy||!!pending} onClick={()=>run('serpapi.connection.verify')}>Verify connection</button><button className="btn" disabled={!enabled||busy||!!pending} onClick={()=>run('serpapi.connection.disconnect')}>Disconnect</button></>}
      </div>
      {!enabled&&<p>Enable SerpAPI in the plugin controls to use this connection.</p>}
      {pending&&<div className="plugin-setup-review" role="group" aria-label="Review SerpAPI disconnection"><h3>Disconnect SerpAPI?</h3><p>Remove its saved key from this device. Vellum will stop using this connection for web search and MCP tools.</p><button className="btn" disabled={busy} onClick={()=>decide(false)}>Cancel</button><button className="btn primary" disabled={busy} onClick={()=>decide(true)}>Confirm disconnect</button></div>}
      {error&&<p className="plugins-error" role="alert">{error}</p>}
      <p className="product-hunt-privacy">The key stays in this device’s system credential store. Only an expiring reference enters Vellum’s connection action. Other users connect their own SerpAPI key.</p>
      <div className="product-hunt-links"><a href="https://github.com/serpapi/serpapi-mcp" target="_blank" rel="noopener noreferrer">Official source and tool coverage ↗</a><a href="https://serpapi.com/dashboard" target="_blank" rel="noopener noreferrer">Open SerpAPI dashboard ↗</a></div>
      <details className="linear-coverage"><summary>Tools provided by SerpAPI</summary><p>All engines and provider parameters remain available through the search tool. The current host displays tool results; SerpAPI’s embedded table/dashboard app UI is not rendered here.</p><button className="btn" disabled={!enabled||!status?.configured||busy||!!pending} onClick={browse}>{tools?'Refresh tools':'Browse tools'}</button>
        {tools&&<><label>Find a tool<input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Search operations…"/></label>{filtered.length===0?<p>No tools match this search.</p>:<ul className="linear-operations">{filtered.map(tool=><li key={tool.name}><details><summary><img src="/design-uploads/assets/plugins/serpapi.png" alt="" width="16" height="16"/>{' '}{tool.name} · {tool.read_only?'Read':'Review required'}</summary><p>{tool.description}</p><pre>{JSON.stringify(tool.input_schema,null,2)}</pre></details></li>)}</ul>}</>}
      </details>
    </section></>;
  }
  window.VellumUI=window.VellumUI||{};window.VellumUI.SerpApiConnection=SerpApiConnection;
})();
