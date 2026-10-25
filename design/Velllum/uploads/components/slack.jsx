(function () {
  const {useEffect,useRef,useState}=React;
  function SlackConnection({enabled=true,onChanged}) {
    const api=window.VellumApi;
    const [status,setStatus]=useState(null),[setup,setSetup]=useState(null);
    const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
    const [appId,setAppId]=useState(''),[clientId,setClientId]=useState('');
    const [flow,setFlow]=useState(null),[pending,setPending]=useState(null),[tools,setTools]=useState(null),[query,setQuery]=useState('');
    const mounted=useRef(false),popupRef=useRef(null),pendingRef=useRef(null);
    const refresh=async()=>{const value=await api.plugins.slackStatus();if(mounted.current)setStatus(value);return value;};
    useEffect(()=>{mounted.current=true;Promise.all([refresh(),api.plugins.slackSetup()]).then(([current,details])=>{if(mounted.current){setSetup(details);setAppId(current.app_id||'');setClientId(current.client_id||'');}}).catch(err=>{if(mounted.current)setError(err.message);});return()=>{mounted.current=false;const value=pendingRef.current;if(value)api.appActions.cancel(value.receipt.confirmation.token,{source:'ui'}).catch(()=>{});};},[enabled]);
    useEffect(()=>{
      if(flow?.status!=='pending'||!flow.flow_id)return;
      let stopped=false,checking=false;
      const poll=async()=>{if(checking)return;checking=true;try{const value=await api.plugins.slackOAuthStatus(flow.flow_id);if(!stopped){setError('');setFlow(previous=>({...previous,...value}));if(value.status!=='pending'){try{popupRef.current?.close();}catch{}popupRef.current=null;window.focus();const url=new URL(location.href);url.searchParams.delete('slack_oauth');history.replaceState(history.state,'',url);await refresh();onChanged?.();}}}catch(err){if(!stopped){if(err.status===400){setFlow(previous=>({...previous,status:'failed',message:'Slack sign-in expired. Start again.'}));setError(err.message);}else setError('Slack status is temporarily unavailable. Vellum will keep checking the local server.');}}finally{checking=false;}};
      const completed=event=>{const expected=new URL(api.plugins.slackOAuthWindowUrl(flow.flow_id));const origins=['127.0.0.1','localhost'].includes(expected.hostname)?['127.0.0.1','localhost'].map(host=>expected.protocol+'//'+host+':'+expected.port):[expected.origin];if(origins.includes(event.origin)&&event.source===popupRef.current&&event.data?.type==='vellum:slack:oauth'&&event.data.flow_id===flow.flow_id)poll();};
      window.addEventListener('message',completed);poll();const timer=setInterval(poll,1500);return()=>{stopped=true;clearInterval(timer);window.removeEventListener('message',completed);};
    },[flow?.flow_id,flow?.status]);
    const dispatch=async(action_id,args={})=>{
      const request={request_id:'slack_'+crypto.randomUUID(),action_id,arguments:args};
      const receipt=await api.appActions.dispatch(request,{source:'ui'});
      if(!mounted.current){if(receipt.confirmation)await api.appActions.cancel(receipt.confirmation.token,{source:'ui'}).catch(()=>{});return;}
      if(receipt.status==='confirmation_required'){const value={request,receipt};pendingRef.current=value;setPending(value);return;}
      if(receipt.status!=='applied')throw new Error(receipt.message||'Slack did not complete this action.');
      if(receipt.result?.connection)setStatus(receipt.result.connection);
      return receipt.result;
    };
    const run=async(action,args={})=>{setBusy(true);setError('');setNotice('');try{const result=await dispatch(action,args);await refresh();onChanged?.();return result;}catch(err){if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}};
    const connect=async()=>{
      const desktop=window.VellumDesktop?.runtime==='electron';
      const popup=desktop?null:window.open('about:blank','vellum-slack-oauth','popup,width=680,height=780');popupRef.current=popup;
      setBusy(true);setError('');
      try{const returnUrl=location.origin+location.pathname+(new URLSearchParams(location.search).get('desktop')==='1'?'?desktop=1':'');const result=await dispatch('slack.connection.oauth.start',{return_url:returnUrl,popup:true});if(result){const target=new URL(result.authorization_url);if(target.origin!=='https://slack.com'||target.pathname!=='/oauth/v2_user/authorize')throw new Error('Slack returned an invalid sign-in address.');setFlow({...result,status:'pending'});if(desktop)popupRef.current=window.open(api.plugins.slackOAuthWindowUrl(result.flow_id),'vellum-slack-oauth','popup,width=680,height=780');else if(popup)popup.location.href=target.href;}else popup?.close();}
      catch(err){popup?.close();popupRef.current=null;if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}
    };
    const decide=async confirm=>{if(!pending)return;setBusy(true);setError('');const value=pending;try{const receipt=confirm?await api.appActions.confirm(value.receipt.confirmation.token,value.request,{source:'ui'}):await api.appActions.cancel(value.receipt.confirmation.token,{source:'ui'});if(confirm&&receipt.status!=='applied')throw new Error(receipt.message||'Slack did not complete this action.');await refresh();onChanged?.();}catch(err){if(mounted.current)setError(err.message);}finally{pendingRef.current=null;if(mounted.current){setPending(null);setBusy(false);}}};
    const browse=async()=>{setBusy(true);setError('');try{const result=await api.plugins.slackMcpTools(true);if(mounted.current)setTools(result.tools);await refresh();}catch(err){if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}};
    const copy=async()=>{try{await navigator.clipboard.writeText(JSON.stringify(setup.manifest,null,2));setNotice('Manifest copied. Paste it into Slack’s app creation form.');}catch{setError('Clipboard is unavailable. Select and copy the manifest below.');}};
    const connected=enabled&&status?.connected;
    return <section className="product-hunt-workspace slack-workspace" aria-label="Slack connection" aria-busy={busy}>
      <div className="product-hunt-summary"><div><h2>{connected?'Connected to Slack':'Connect Slack'}</h2><p>{status?.message||'Checking Slack connection…'}</p></div><img src="/design-uploads/assets/plugins/slack.png" alt="Slack" width="32" height="32"/></div>
      {connected&&<p className="linear-identity">{status.account_name} <span>in {status.workspace_name}</span></p>}
      <p className="product-hunt-privacy">Search messages and threads, send messages, work with channels, reactions, canvases, files and lists through Slack’s official MCP server. Your workspace permissions apply. Changes get a readable review before they run.</p>
      <details className="linear-coverage" open={!status?.oauth_available}><summary>Set up your Slack app</summary>
        <ol><li>Open <a href="https://api.slack.com/apps" target="_blank" rel="noopener noreferrer">Slack apps ↗</a>, choose <strong>Create New App → From an app manifest</strong>, and select your workspace.</li>
          <li>Choose JSON, paste the supplied manifest, review its user permissions and create the app. It enables MCP and desktop PKCE. PKCE is a one-way Slack app setting; use a dedicated Vellum app.</li>
          <li>Under <strong>Basic Information → App Credentials</strong>, copy the public App ID and Client ID into the fields below. Then choose Sign in with Slack and review the consent screen.</li></ol>
        {setup&&<><p>Registered redirect URL: <code>{setup.callback_url}</code></p><button className="btn" onClick={copy}>Copy app manifest</button><details><summary>View app manifest</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:300,overflow:'auto'}}>{JSON.stringify(setup.manifest,null,2)}</pre></details></>}
        <form className="product-hunt-actions" onSubmit={event=>{event.preventDefault();run('slack.connection.configure',{app_id:appId.trim(),client_id:clientId.trim()});}}>
          <label>App ID<input value={appId} onChange={event=>setAppId(event.target.value)} placeholder="A0123456789" autoComplete="off" required disabled={status?.configured||busy}/></label>
          <label>Client ID<input value={clientId} onChange={event=>setClientId(event.target.value)} placeholder="123456789.123456789" autoComplete="off" required disabled={status?.configured||busy}/></label>
          <button className="btn" type="submit" disabled={!enabled||busy||!!pending||status?.configured||!appId.trim()||!clientId.trim()}>Save app registration</button>
        </form><p className="product-hunt-privacy">These two IDs are public identifiers. Vellum does not need your client secret or a pasted token. Authorization is saved only in this device’s system credential store.</p>
      </details>
      <div className="product-hunt-actions"><button className="btn primary" disabled={!enabled||busy||!!pending||flow?.status==='pending'||!status?.oauth_available} onClick={connect}>{status?.configured?'Reconnect with Slack':'Sign in with Slack'}</button>
        {status?.configured&&<><button className="btn" disabled={!enabled||busy||!!pending} onClick={()=>run('slack.connection.verify')}>Verify connection</button><button className="btn" disabled={!enabled||busy||!!pending} onClick={()=>run('slack.connection.disconnect')}>Disconnect</button></>}
      </div>
      {flow&&<div role="status"><p>{flow.message}</p>{flow.status==='pending'&&<>{flow.authorization_url&&<a className="btn primary" href={window.VellumDesktop?.runtime==='electron'?api.plugins.slackOAuthWindowUrl(flow.flow_id):flow.authorization_url} target="vellum-slack-oauth" rel="noopener noreferrer">Continue to Slack ↗</a>}<button className="btn" disabled={busy} onClick={async()=>{await run('slack.connection.oauth.cancel',{flow_id:flow.flow_id});}}>Cancel sign-in</button></>}</div>}
      {pending&&<div className="plugin-setup-review" role="group" aria-label="Review Slack disconnection"><h3>Disconnect Slack?</h3><p>Remove Vellum’s saved Slack authorization from this device. Your app registration stays available for reconnection. Revoke the app in Slack to withdraw its provider grant.</p><button className="btn" disabled={busy} onClick={()=>decide(false)}>Cancel</button><button className="btn primary" disabled={busy} onClick={()=>decide(true)}>Confirm disconnect</button></div>}
      {error&&<p className="plugins-error" role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
      <div className="product-hunt-links"><a href="https://docs.slack.dev/ai/slack-mcp-server/" target="_blank" rel="noopener noreferrer">Official source and tool coverage ↗</a></div>
      <details className="linear-coverage"><summary>Tools provided by Slack</summary><p>Discover the live catalog with its real descriptions and complete schemas. A connected status appears only after account, workspace and MCP verification.</p><button className="btn" disabled={!connected||busy||!!pending} onClick={browse}>{tools?'Refresh tools':'Browse tools'}</button>
        {tools&&<><label>Find a tool<input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Messages, channels, canvases…"/></label><ul className="linear-operations">{tools.filter(tool=>(tool.name+' '+tool.description).toLowerCase().includes(query.toLowerCase())).map(tool=><li key={tool.name}><details><summary><img src="/design-uploads/assets/plugins/slack.png" alt="" width="16" height="16"/>{' '}{tool.name} · {tool.read_only?'Read':'Review required'}</summary><p>{tool.description}</p><pre>{JSON.stringify(tool.input_schema,null,2)}</pre></details></li>)}</ul></>}
      </details>
    </section>;
  }
  window.VellumUI=window.VellumUI||{};window.VellumUI.SlackConnection=SlackConnection;
})();
