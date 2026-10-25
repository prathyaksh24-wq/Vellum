(function () {
  const {useEffect,useRef,useState}=React;
  function GitHubConnection({enabled=true,onChanged}) {
    const api=window.VellumApi;
    const [status,setStatus]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
    const [flow,setFlow]=useState(()=>{const id=new URLSearchParams(location.search).get('github_oauth');return id?{flow_id:id,status:'pending',message:'Checking GitHub authorization…'}:null;});
    const [tools,setTools]=useState(null),[query,setQuery]=useState(''),[pending,setPending]=useState(null);
    const mounted=useRef(false),pendingRef=useRef(null),popupRef=useRef(null);
    const refresh=async()=>{const value=await api.plugins.githubStatus();if(mounted.current)setStatus(value);};
    const cleanReturn=()=>{const url=new URL(location.href);url.searchParams.delete('github_oauth');history.replaceState(history.state,'',url);};
    useEffect(()=>{mounted.current=true;refresh().catch(err=>setError(err.message));return()=>{mounted.current=false;const value=pendingRef.current;if(value)api.appActions.cancel(value.receipt.confirmation.token,{source:'ui'}).catch(()=>{});};},[enabled]);
    useEffect(()=>{
      if(flow?.status!=='pending'||!flow.flow_id)return;
      let stopped=false,checking=false;
      const poll=async()=>{if(checking)return;checking=true;try{const value=await api.plugins.githubOAuthStatus(flow.flow_id);if(!stopped){setError('');setFlow(previous=>({...previous,...value}));if(value.status!=='pending'){try{popupRef.current?.close();}catch{}popupRef.current=null;window.focus();cleanReturn();await refresh();onChanged?.();}}}catch(err){if(!stopped){if(err.status===400){setError(err.message||'GitHub sign-in expired. Start again.');setFlow(previous=>({...previous,status:'failed',message:'GitHub sign-in expired. Your saved connection is unchanged.'}));}else setError('GitHub status is temporarily unavailable. Vellum will keep checking the local server.');}}finally{checking=false;}};
      const completed=event=>{if(!['http://127.0.0.1:8000','http://localhost:8000'].includes(event.origin)||event.source!==popupRef.current||event.data?.type!=='vellum:github:oauth'||event.data.flow_id!==flow.flow_id)return;poll();};
      window.addEventListener('message',completed);poll();const timer=setInterval(poll,1500);return()=>{stopped=true;clearInterval(timer);window.removeEventListener('message',completed);};
    },[flow?.flow_id,flow?.status]);
    const dispatch=async(action_id,args={})=>{
      const request={request_id:'github_'+crypto.randomUUID(),action_id,arguments:args};
      const receipt=await api.appActions.dispatch(request,{source:'ui'});
      if(!mounted.current){if(receipt.confirmation)await api.appActions.cancel(receipt.confirmation.token,{source:'ui'}).catch(()=>{});return;}
      if(receipt.status==='confirmation_required'){const value={request,receipt};pendingRef.current=value;setPending(value);return;}
      if(receipt.status!=='applied')throw new Error(receipt.message||'GitHub did not complete this action.');
      if(receipt.result?.connection)setStatus(receipt.result.connection);
      return receipt.result;
    };
    const connect=async()=>{
      const desktop=window.VellumDesktop?.runtime==='electron';
      const popup=desktop?null:window.open('about:blank','vellum-github-oauth','popup,width=680,height=780');
      popupRef.current=popup;
      setBusy(true);setError('');
      try{const returnUrl=location.origin+location.pathname+(new URLSearchParams(location.search).get('desktop')==='1'?'?desktop=1':'');const result=await dispatch('github.connection.oauth.start',{return_url:returnUrl,access:'manage',popup:true});if(result){const target=new URL(result.authorization_url);if(target.origin!=='https://github.com'||target.pathname!=='/login/oauth/authorize')throw new Error('GitHub returned an invalid sign-in address.');setFlow(result);if(desktop)popupRef.current=window.open(api.plugins.githubOAuthWindowUrl(result.flow_id),'vellum-github-oauth','popup,width=680,height=780');else if(popup)popup.location.href=target.href;}else popup?.close();}
      catch(err){popup?.close();popupRef.current=null;setError(err.message);}finally{if(mounted.current)setBusy(false);}
    };
    const run=async action=>{setBusy(true);setError('');try{await dispatch(action);await refresh();onChanged?.();}catch(err){setError(err.message);}finally{if(mounted.current)setBusy(false);}};
    const decide=async confirm=>{if(!pending)return;setBusy(true);setError('');const value=pending;
      try{const receipt=confirm?await api.appActions.confirm(value.receipt.confirmation.token,value.request,{source:'ui'}):await api.appActions.cancel(value.receipt.confirmation.token,{source:'ui'});if(confirm&&receipt.status!=='applied')throw new Error(receipt.message||'GitHub did not complete this action.');await refresh();onChanged?.();}
      catch(err){if(mounted.current)setError(err.message);}finally{pendingRef.current=null;if(mounted.current){setPending(null);setBusy(false);}}
    };
    const browse=async()=>{setBusy(true);setError('');try{const result=await api.plugins.githubMcpTools(true);if(mounted.current)setTools(result.tools);await refresh();}catch(err){if(mounted.current)setError(err.message);}finally{if(mounted.current)setBusy(false);}};
    const cancel=async()=>{setBusy(true);try{await dispatch('github.connection.oauth.cancel',{flow_id:flow.flow_id});setFlow({...flow,status:'cancelled',message:'GitHub sign-in cancelled.'});}catch(err){setError(err.message);}finally{setBusy(false);}};
    const connected=status?.connected&&enabled;
    return <section className="product-hunt-workspace github-workspace" aria-label="GitHub connection" aria-busy={busy}>
      <div className="product-hunt-summary"><div><h2>{connected?'Connected to GitHub':'Connect GitHub'}</h2><p>{status?.message||'Checking GitHub connection…'}</p></div><img src="/design-uploads/assets/plugins/github.png" alt="GitHub" width="32" height="32"/></div>
      {connected&&<p className="linear-identity">{status.account_name} <span>@{status.login}</span></p>}
      <p className="product-hunt-privacy">One GitHub sign-in authorizes both connection paths. Authorization stays in this device’s system credential store. Each change has a readable review before it runs.</p>
      <dl className="product-hunt-privileges" aria-label="GitHub connection paths"><div><dt>Preferred</dt><dd>{status?.cli_available?'GitHub CLI available':'CLI unavailable · uses MCP'}</dd></div><div><dt>Fallback</dt><dd>Official GitHub MCP server</dd></div><div><dt>Tools</dt><dd>{status?.mcp_tool_count||0} published tools · discovered on demand</dd></div></dl>
      <p className="product-hunt-privacy">Repository, organization and GitHub permissions determine access. If a change times out, Vellum stops and asks you to check GitHub before retrying.</p>
      <div className="product-hunt-actions"><button className="btn primary" disabled={!enabled||busy||!!pending||flow?.status==='pending'||!status?.oauth_available} onClick={connect}>{status?.configured?'Reconnect with GitHub':'Sign in with GitHub'}</button>
        {status&&!status.oauth_available&&<span>Configure Vellum’s GitHub OAuth app to enable sign-in.</span>}
        {status?.configured&&<><button className="btn" disabled={!enabled||busy||!!pending} onClick={()=>run('github.connection.verify')}>Verify connection</button><button className="btn" disabled={!enabled||busy||!!pending} onClick={()=>run('github.connection.disconnect')}>Disconnect</button></>}
      </div>
      {flow&&<div role="status"><p>{flow.message}</p>{flow.status==='pending'&&<>{flow.authorization_url&&<a className="btn primary" href={window.VellumDesktop?.runtime==='electron'?api.plugins.githubOAuthWindowUrl(flow.flow_id):flow.authorization_url} target="vellum-github-oauth" rel="noopener noreferrer">Continue to GitHub ↗</a>}<button className="btn" disabled={busy} onClick={cancel}>Cancel sign-in</button></>}</div>}
      {pending&&<div className="plugin-setup-review" role="group" aria-label="Review GitHub disconnection"><h3>Disconnect GitHub?</h3><p>Remove Vellum’s saved GitHub authorization from this device. Your global GitHub CLI login stays as it is. You can revoke Vellum in GitHub’s authorized applications.</p><button className="btn" disabled={busy} onClick={()=>decide(false)}>Cancel</button><button className="btn primary" disabled={busy} onClick={()=>decide(true)}>Confirm disconnect</button></div>}
      {error&&<p className="plugins-error" role="alert">{error}</p>}
      <div className="product-hunt-links"><a href="https://github.com/github/github-mcp-server" target="_blank" rel="noopener noreferrer">Official source and documentation ↗</a><a href="https://github.com/settings/applications" target="_blank" rel="noopener noreferrer">Manage GitHub access ↗</a></div>
      <div className="product-hunt-examples"><h3>Ask Vellum</h3><p>“Show the open issues in my repository.”</p><p>“Draft a pull request for these changes.”</p><p>“Check why the latest workflow failed.”</p></div>
      <details className="linear-coverage"><summary>Tools provided by GitHub</summary><p>Browse the connected account’s official catalog. Tool schemas are loaded when needed.</p><button className="btn" disabled={!connected||busy||!!pending} onClick={browse}>{tools?'Refresh tools':'Browse tools'}</button>
        {tools&&<><label>Find a tool<input value={query} onChange={event=>setQuery(event.target.value)} placeholder="Issues, pull requests, workflows…"/></label><ul className="linear-operations">{tools.filter(tool=>(tool.name+' '+tool.description).toLowerCase().includes(query.toLowerCase())).map(tool=><li key={tool.name}><details><summary><img src="/design-uploads/assets/plugins/github.png" alt="" width="16" height="16"/>{' '}{tool.name} · {tool.read_only?'Read':'Review required'}</summary><p>{tool.description}</p><pre>{JSON.stringify(tool.input_schema,null,2)}</pre></details></li>)}</ul></>}
      </details>
    </section>;
  }
  window.VellumUI=window.VellumUI||{};window.VellumUI.GitHubConnection=GitHubConnection;
})();
