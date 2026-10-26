(function () {
  const {useEffect,useRef,useState}=React;
  function LinearActionReview({review}) {
    const Markdown=window.VellumUI?.AnswerMarkdown;
    const github=review.provider==='GitHub';
    const slack=review.provider==='Slack';
    const airtable=review.provider==='Airtable';
    const notion=review.provider==='Notion';
    const hubspot=review.provider==='HubSpot';
    const clickup=review.provider==='ClickUp';
    const vercel=review.provider==='Vercel';
    const supabase=review.provider==='Supabase';
    const searchProvider={SerpAPI:'serpapi',Exa:'exa',Tavily:'tavily'}[review.provider];
    const firecrawl=review.provider==='Firecrawl';
    const apify=review.provider==='Apify';
    return <section className="linear-action-preview" aria-label={hubspot?'Review HubSpot operation':clickup?'Review ClickUp operation':vercel?'Review Vercel operation':supabase?'Review Supabase operation':searchProvider?'Review '+review.provider+' operation':github?'Review GitHub change':slack?'Review Slack change':airtable?'Review Airtable change':notion?'Review Notion change':firecrawl?'Review Firecrawl operation':apify?'Review Apify operation':'Review Linear issue'}>
      <header><img className={vercel?"conn-logo-img brand-monochrome":undefined} src={hubspot?'/design-uploads/assets/plugins/hubspot.svg':clickup?'/design-uploads/assets/plugins/clickup.png':vercel?'/design-uploads/assets/plugins/vercel.svg':supabase?'/design-uploads/assets/plugins/supabase.svg':searchProvider?'/design-uploads/assets/plugins/'+searchProvider+'.png':firecrawl?'/design-uploads/assets/plugins/firecrawl.ico':apify?'/design-uploads/assets/plugins/apify.ico':notion?'/design-uploads/assets/plugins/notion.png':airtable?'/design-uploads/assets/plugins/airtable.svg':github?'/design-uploads/assets/plugins/github.png':slack?'/design-uploads/assets/plugins/slack.png':'/design-uploads/assets/plugins/linear.png'} width="22" height="22" alt=""/><h3>{review.heading}</h3></header>
      <div className="linear-review-content">
        {review.title&&<h4 className="linear-review-title">{review.title}</h4>}
        <dl><div><dt>{github?'Repository':airtable?'Resources':'Workspace'}</dt><dd>{review.workspace}</dd></div>{(review.fields||[]).map((field,index)=><div key={index}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl>
        <div className="linear-review-description"><h4>Description</h4>{review.description?(Markdown?<Markdown text={review.description}/>:<p>{review.description}</p>):<p className="linear-review-empty">{review.description_note||'No description supplied.'}</p>}</div>
      </div>
    </section>;
  }
  function LinearWorkspace({enabled=true,onStatus}) {
    const api=window.VellumApi;
    const [status,setStatus]=useState(null);
    const [busy,setBusy]=useState(false),[error,setError]=useState(''),[pending,setPending]=useState(null),[result,setResult]=useState(null);
    const [search,setSearch]=useState(''),[tools,setTools]=useState(null);
    const [oauth,setOAuth]=useState(()=>{const id=new URLSearchParams(window.location.search).get('linear_oauth');return id?{flow_id:id,status:'pending',message:'Checking Linear sign-in…'}:null;});
    const mounted=useRef(true),pendingRef=useRef(null);
    const accept=value=>{if(mounted.current){setStatus(value);onStatus?.(value);}};
    const refresh=async()=>{try{accept(await api.plugins.linearStatus());}catch(err){if(mounted.current)setError(err.message||'Linear status is unavailable.');}};
    useEffect(()=>{mounted.current=true;refresh();return()=>{mounted.current=false;const next=pendingRef.current;if(next)api.appActions.cancel(next.receipt.confirmation.token,{source:'ui'}).catch(()=>{});};},[]);
    const clearReturn=()=>{const url=new URL(window.location.href);if(url.searchParams.has('linear_oauth')){url.searchParams.delete('linear_oauth');window.history.replaceState(window.history.state,'',url);}};
    useEffect(()=>{
      if(!oauth?.flow_id||oauth.status!=='pending')return;
      let stopped=false,checking=false;
      const timer=setInterval(async()=>{if(checking)return;checking=true;try{const value=await api.plugins.linearOAuthStatus(oauth.flow_id);if(!stopped){setOAuth({...oauth,...value});if(value.status!=='pending'){clearReturn();await refresh();}}}catch(err){if(!stopped){clearReturn();setError('Could not finish Linear sign-in. Check the local server, then try signing in again.');setOAuth({...oauth,status:'failed',message:'Linear sign-in could not be verified.'});}}finally{checking=false;}},1500);
      return()=>{stopped=true;clearInterval(timer);};
    },[oauth?.flow_id,oauth?.status]);
    const remember=value=>{pendingRef.current=value;if(mounted.current)setPending(value);};
    const action=async(action_id,argumentsValue={})=>{
      const request={request_id:'linear_'+crypto.randomUUID(),action_id,arguments:argumentsValue};
      const receipt=await api.appActions.dispatch(request,{source:'ui'});
      if(!mounted.current){if(receipt.status==='confirmation_required')await api.appActions.cancel(receipt.confirmation.token,{source:'ui'}).catch(()=>{});return;}
      if(receipt.status==='confirmation_required'){remember({request,receipt});return;}
      if(receipt.status!=='applied')throw new Error(receipt.message||'Linear did not complete this action.');
      if(receipt.result?.connection)accept(receipt.result.connection);
      return receipt.result;
    };
    const signIn=async()=>{setBusy(true);setError('');try{const next=await action('linear.connection.oauth.start',{return_url:window.location.origin+window.location.pathname+(new URLSearchParams(window.location.search).get('desktop')==='1'?'?desktop=1':'')});if(next)setOAuth({...next,status:'pending',message:'Continue to Linear and approve access to your workspace.'});}catch(err){setError(err.message);}finally{setBusy(false);}};
    const cancelSignIn=async()=>{setBusy(true);try{await action('linear.connection.oauth.cancel',{flow_id:oauth.flow_id});setOAuth({...oauth,status:'cancelled',message:'Linear sign-in cancelled.'});}catch(err){setError(err.message);}finally{setBusy(false);}};
    const decide=async confirmed=>{if(!pending||busy)return;const next=pending;setBusy(true);setError('');
      try{const receipt=confirmed?await api.appActions.confirm(next.receipt.confirmation.token,next.request,{source:'ui'}):await api.appActions.cancel(next.receipt.confirmation.token,{source:'ui'});
        if(confirmed&&receipt.status!=='applied')throw new Error(receipt.message||'Linear did not complete this action.');
        if(confirmed&&mounted.current){if(receipt.result?.connection){accept(receipt.result.connection);}else setResult(receipt.result);}
      }catch(err){if(mounted.current)setError(err.message||'Linear did not complete this action.');}
      finally{remember(null);await refresh();if(mounted.current){setBusy(false);}}
    };
    const run=async actionId=>{setBusy(true);setError('');try{await action(actionId);}catch(err){setError(err.message);}finally{await refresh();setBusy(false);}};
    const browse=async()=>{setBusy(true);setError('');try{const catalog=await api.plugins.linearMcpTools();if(mounted.current)setTools(catalog.tools);}catch(err){if(mounted.current)setError(err.message);}finally{await refresh();if(mounted.current)setBusy(false);}};
    const readIssues=async()=>{setBusy(true);setError('');try{setResult(await api.plugins.linearMcpRead({tool_name:'list_issues',arguments:{limit:5,orderBy:'createdAt',fields:['id','title','url']}}));}catch(err){setError(err.message);}finally{await refresh();setBusy(false);}};
    const connected=!!status?.connected&&enabled;
    return <section className="product-hunt-workspace linear-workspace" aria-label="Linear connection" aria-busy={busy}>
      <div className="product-hunt-summary"><div><h2>{connected?'Connected to Linear':'Connect Linear'}</h2><p>{status?.message||'Checking connection…'}</p></div><span className="product-hunt-access">Official MCP</span></div>
      <p className="product-hunt-privacy">Your authorization is saved in this device’s system credential store and sent only to Linear. Reads use your workspace access; every write requires review and confirmation.</p>
      {connected&&<p className="linear-identity">{status.account_name} <span>in</span> {status.workspace_name}</p>}
      <dl className="product-hunt-privileges" aria-label="Linear access"><div><dt>Read</dt><dd>{connected?'Account and workspace verified':'Connection required'}</dd></div><div><dt>Write</dt><dd>{status?.write_access==='verified_for_last_operation'?'Last change verified; permissions vary by operation':'Review required · no completed changes yet'}</dd></div><div><dt>Scope</dt><dd>Authorized permissions, teams, workspace role and plan</dd></div></dl>
      {status&&<p className="product-hunt-operation-count">{tools?.length||status.mcp_tool_count||0} official MCP tools · Issues, projects, comments, teams, labels and more</p>}
      <div className="product-hunt-actions"><button className="btn primary" disabled={!enabled||busy||!!pending||oauth?.status==='pending'} onClick={signIn}>{status?.configured?'Reconnect with Linear':'Sign in with Linear'}</button><span>{status?.configured?'OAuth · authorization stays on this device':'Use your own Linear account to connect its official MCP server.'}</span></div>
      {oauth&&<div role="status"><p>{oauth.message}</p>{oauth.status==='pending'&&<>{oauth.authorization_url&&<a className="btn primary" href={oauth.authorization_url} target="_blank" rel="noopener noreferrer">Continue to Linear ↗</a>}<button className="btn" disabled={busy} onClick={cancelSignIn}>Cancel sign-in</button></>}</div>}
      {status?.verified_at&&<p className="product-hunt-verified">Last verified: {new Date(status.verified_at).toLocaleString()}</p>}
      <div className="product-hunt-links"><a href="https://linear.app/docs/mcp" target="_blank" rel="noopener noreferrer">Official MCP documentation ↗</a><a href="https://linear.app/settings/account/security" target="_blank" rel="noopener noreferrer">Manage Linear access ↗</a></div>
      {!enabled&&<p role="status">Enable Linear above to connect or use it.</p>}
      {!pending&&status?.configured&&<div className="product-hunt-actions"><button className="btn" disabled={!enabled||busy} onClick={()=>run('linear.connection.verify')}>Verify connection</button><button className="btn" disabled={!enabled||busy} onClick={()=>run('linear.connection.disconnect')}>Disconnect</button>{connected&&<button className="btn primary" disabled={busy} onClick={readIssues}>Read recent issues</button>}</div>}
      {pending&&<div className="plugin-setup-review" role="group" aria-label="Review Linear action"><h3>Disconnect Linear?</h3><p>Remove Linear authorization from this device. You can also revoke Vellum in Linear’s access settings.</p>
        <button className="btn" disabled={busy} onClick={()=>decide(false)}>Cancel</button><button className="btn primary" disabled={busy||!enabled} onClick={()=>decide(true)}>{busy?'Disconnecting…':'Confirm disconnect'}</button>
      </div>}
      {error&&<p className="plugins-error" role="alert">{error}</p>}
      {connected&&<div className="product-hunt-examples"><h3>Ask Vellum</h3><p>“Show my open Linear issues.”</p><p>“Create a Linear issue for this bug, then let me review it.”</p><span>Vellum uses the tools maintained by Linear. Every workspace change requires your confirmation.</span></div>}
      <details className="linear-coverage"><summary>Tools provided by Linear</summary><p>These tools come from Linear’s official MCP server. Available operations depend on your account, permissions and workspace plan.</p><button className="btn" disabled={!connected||busy||!!pending} onClick={browse}>{tools?'Refresh tools':'Browse tools'}</button>{tools&&<><label>Find a tool<input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Issues, projects, comments…"/></label><ul className="linear-operations">{tools.filter(tool=>(tool.name+' '+tool.description).toLowerCase().includes(search.toLowerCase())).map(tool=><li key={tool.name}><details><summary><img src="/design-uploads/assets/plugins/linear.png" alt="" width="16" height="16" style={{verticalAlign:'middle',marginRight:8}}/>{tool.name} · {tool.read_only?'Read':'Confirmation required'}</summary><p>{tool.description}</p><pre>{JSON.stringify(tool.input_schema,null,2)}</pre></details></li>)}</ul></>}</details>
      {result&&<section className="linear-result" aria-label="Linear API result"><h3>Linear result</h3><pre>{JSON.stringify(result,null,2)}</pre></section>}
    </section>;
  }
  window.VellumUI=window.VellumUI||{};window.VellumUI.LinearWorkspace=LinearWorkspace;window.VellumUI.LinearActionReview=LinearActionReview;
})();
