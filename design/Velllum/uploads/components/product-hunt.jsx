(function () {
  const {useEffect,useRef,useState} = React;
  function ProductHuntWorkspace({enabled=true,onStatus}) {
    const api=window.VellumApi;
    const [status,setStatus]=useState(null),[token,setToken]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
    const [pending,setPending]=useState(null),[editing,setEditing]=useState(false),[posts,setPosts]=useState(null);
    const [accountChoice,setAccountChoice]=useState('viewer'),[accountData,setAccountData]=useState(null),[username,setUsername]=useState('');
    const mounted=useRef(true),pendingRef=useRef(null),input=useRef(null);
    const accept=next=>{if(!mounted.current)return;setStatus(next);onStatus?.(next);};
    const refresh=async()=>{try{accept(await api.plugins.productHuntStatus());}catch(err){if(mounted.current)setError(err.message||'Product Hunt status is unavailable.');}};
    useEffect(()=>{mounted.current=true;refresh();return()=>{mounted.current=false;const next=pendingRef.current;if(next){api.appActions.cancel(next.receipt.confirmation.token,{source:'ui'}).catch(()=>{});if(next.request.arguments.credential_id)api.plugins.productHuntDiscard(next.request.arguments.credential_id).catch(()=>{});}};},[]);
    const remember=value=>{pendingRef.current=value;setPending(value);};
    const action=async(action_id,args={})=>{
      const request={request_id:'producthunt_'+crypto.randomUUID(),action_id,arguments:args};
      const receipt=await api.appActions.dispatch(request,{source:'ui'});
      if(!mounted.current){if(receipt.status==='confirmation_required')await api.appActions.cancel(receipt.confirmation.token,{source:'ui'}).catch(()=>{});if(args.credential_id)await api.plugins.productHuntDiscard(args.credential_id).catch(()=>{});return;}
      if(receipt.status==='confirmation_required'){remember({request,receipt});return;}
      if(receipt.status!=='applied')throw new Error(receipt.message||'Product Hunt could not complete this action.');
      if(receipt.result?.connection)accept(receipt.result.connection);else await refresh();
    };
    const stage=async event=>{event.preventDefault();if(busy||!token.trim())return;setBusy(true);setError('');let reference;
      try{const staged=await api.plugins.productHuntStage(token);reference=staged.credential_id;if(!mounted.current){await api.plugins.productHuntDiscard(reference).catch(()=>{});return;}setToken('');await action('producthunt.connection.connect',{credential_id:reference});}
      catch(err){setToken('');if(reference)await api.plugins.productHuntDiscard(reference).catch(()=>{});setError(err.message||'Product Hunt could not be connected.');}
      finally{setBusy(false);}
    };
    const decide=async confirmed=>{if(!pending||busy)return;setBusy(true);setError('');const next=pending;
      try{const receipt=confirmed?await api.appActions.confirm(next.receipt.confirmation.token,next.request,{source:'ui'}):await api.appActions.cancel(next.receipt.confirmation.token,{source:'ui'});
        if(confirmed&&receipt.status!=='applied')throw new Error(receipt.message||'Product Hunt could not be connected.');
        if(confirmed){if(receipt.result?.connection)accept(receipt.result.connection);setEditing(false);setPosts(null);}
      }catch(err){setError(err.message||'Product Hunt could not complete this action.');}
      finally{if(next.request.arguments.credential_id)await api.plugins.productHuntDiscard(next.request.arguments.credential_id).catch(()=>{});remember(null);await refresh();setBusy(false);input.current?.focus();}
    };
    const run=async actionId=>{setBusy(true);setError('');try{await action(actionId);}catch(err){setError(err.message);}finally{await refresh();setBusy(false);}};
    const preview=async()=>{setBusy(true);setError('');try{const result=await api.plugins.productHuntRead({operation:'posts',limit:5,order:'NEWEST'});setPosts(result.posts);await refresh();}catch(err){setError(err.message);await refresh();}finally{setBusy(false);}};
    const readAccount=async()=>{setBusy(true);setError('');setAccountData(null);try{const request=accountChoice.startsWith('posts:')?{operation:'account_posts',account_feed:accountChoice.split(':')[1],limit:5}:{operation:accountChoice,limit:5};setAccountData(await api.plugins.productHuntRead(request));await refresh();}catch(err){setError(err.message);await refresh();}finally{setBusy(false);}};
    const reviewFollow=async following=>{if(!username.trim()||busy)return;setBusy(true);setError('');try{await action(following?'producthunt.user.follow':'producthunt.user.unfollow',{username:username.trim().replace(/^@/,'')});}catch(err){setError(err.message);}finally{setBusy(false);}};
    const connected=!!status?.connected&&enabled;
    const showForm=!!status&&(!status.configured||editing);
    const safeLink=url=>{try{const value=new URL(url);return value.protocol==='https:'&&(value.hostname==='www.producthunt.com'||value.hostname==='producthunt.com')?value.href:null;}catch{return null;}};
    return <section className="product-hunt-workspace" aria-label="Product Hunt connection" aria-busy={busy}>
      <div className="product-hunt-summary"><div><h2>{connected?'Connected to Product Hunt':'Connect Product Hunt'}</h2><p>{status?.message||'Checking connection…'}</p></div><span className="product-hunt-access">Official API</span></div>
      <p className="product-hunt-privacy">Your token stays in this device’s system credential store and is sent only to Product Hunt. Account reads are requested explicitly; follow changes require confirmation and provider Write permission.</p>
      <dl className="product-hunt-privileges" aria-label="Product Hunt privileges"><div><dt>Public</dt><dd>{connected?'Verified API reads':'Connection required'}</dd></div><div><dt>Private</dt><dd>{status?.account_access==='available'?'Account reads verified':status?.account_access==='needs_permission'?'Additional permission required':'Account access not checked'}</dd></div><div><dt>Write</dt><dd>{status?.write_access==='verified'?'Follow changes verified; confirmation required':status?.write_access==='approval_required'?'Product Hunt approval required':'Follow changes implemented; provider permission not verified'}</dd></div></dl>
      <p className="product-hunt-operation-count">1 read tool · 7 read operations · 2 confirmed actions</p>
      <p className="product-hunt-privacy">Product submission, voting, and comment posting are not exposed by the documented API. Write access must be approved by Product Hunt for your application.</p>
      {status?.verified_at&&<p className="product-hunt-verified">Last verified: {new Date(status.verified_at).toLocaleString()}</p>}
      <div className="product-hunt-links"><a href="https://www.producthunt.com" target="_blank" rel="noopener noreferrer">Product Hunt ↗</a><a href="https://api.producthunt.com/v2/docs" target="_blank" rel="noopener noreferrer">API documentation ↗</a></div>
      {!enabled&&<p role="status">Enable Product Hunt above to connect or use it.</p>}
      {showForm&&<form onSubmit={stage}>
        <details className="product-hunt-guide"><summary>Get your Product Hunt developer token</summary><ol><li>Open the <a href="https://www.producthunt.com/v2/oauth/applications" target="_blank" rel="noopener noreferrer">Product Hunt API dashboard ↗</a> and sign in.</li><li>Create a personal application named Vellum, then open that application’s details.</li><li>Copy the developer token into the field below. Use the developer token, rather than the API key or client secret.</li></ol><p>This connection uses a developer token and does not use an OAuth callback. Product Hunt’s API terms limit commercial use; review their documentation if you plan to distribute this integration.</p></details>
        <label htmlFor="producthunt-token">Developer token</label><input ref={input} id="producthunt-token" type="password" autoComplete="off" spellCheck={false} maxLength={4096} value={token} disabled={!enabled||busy||!!pending} onChange={event=>setToken(event.target.value)} placeholder="Enter your Product Hunt developer token" aria-describedby="producthunt-token-help"/>
        <p id="producthunt-token-help">The value is cleared after you continue. Only an opaque reference appears in the confirmation.</p>
        <button className="btn primary" disabled={!enabled||busy||!!pending||!token.trim()}>{busy?'Checking…':'Review connection'}</button>{editing&&<button type="button" className="btn" disabled={busy||!!pending} onClick={()=>{setEditing(false);setToken('');}}>Cancel replacement</button>}
      </form>}
      {!pending&&status?.configured&&<div className="product-hunt-actions"><button className="btn" disabled={!enabled||busy} onClick={()=>run('producthunt.connection.verify')}>{busy?'Checking…':'Verify connection'}</button><button className="btn" disabled={!enabled||busy} onClick={()=>{setEditing(true);setError('');}}>Replace token</button><button className="btn" disabled={!enabled||busy} onClick={()=>run('producthunt.connection.disconnect')}>Disconnect</button>{connected&&<button className="btn primary" disabled={busy} onClick={preview}>Read recent launches</button>}</div>}
      {pending&&<div className="plugin-setup-review" role="group" aria-label="Review Product Hunt action"><h3>{pending.request.action_id.startsWith('producthunt.user.')?'Review following change':pending.request.action_id.endsWith('.disconnect')?'Disconnect Product Hunt?':'Connect Product Hunt?'}</h3><p>{pending.request.action_id.startsWith('producthunt.user.')?pending.receipt.message:pending.request.action_id.endsWith('.disconnect')?'Remove the locally saved credential. You can revoke the token separately in Product Hunt’s API dashboard.':'Send the entered credential to api.producthunt.com to verify public read access, then save it in this device’s system credential store.'}</p><button className="btn" disabled={busy} onClick={()=>decide(false)}>Cancel</button><button className="btn primary" disabled={busy||!enabled} onClick={()=>decide(true)}>{busy?'Checking…':pending.request.action_id.startsWith('producthunt.user.')?'Confirm change':pending.request.action_id.endsWith('.disconnect')?'Confirm disconnect':'Verify and connect'}</button></div>}
      {error&&<p className="plugins-error" role="alert">{error}</p>}
      {connected&&<div className="product-hunt-examples"><h3>Ask Vellum</h3><p>“Use Product Hunt to find recent developer-tool launches.”</p><p>“Get the Product Hunt details for this launch slug.”</p><span>Vellum can browse launches by topic and date, read a launch, and list topics.</span></div>}
      {connected&&<section className="product-hunt-account" aria-label="Product Hunt account"><h3>Your account</h3><p>Read your profile, voted launches, products you made or submitted, or followed collections. Product Hunt may redact fields; an empty list does not prove there is no activity.</p><div className="product-hunt-actions"><select aria-label="Product Hunt account data" disabled={busy||!!pending} value={accountChoice} onChange={event=>setAccountChoice(event.target.value)}><option value="viewer">My profile</option><option value="posts:voted">My voted launches</option><option value="posts:made">Products I made</option><option value="posts:submitted">Products I submitted</option><option value="account_collections">Collections I follow</option></select><button className="btn" disabled={busy||!!pending} onClick={readAccount}>Read account data</button></div>
        {accountData&&<div className="product-hunt-account-result" role="status"><p>From your authenticated Product Hunt account</p>{accountData.user&&<p>{accountData.user.name} · @{accountData.user.username}</p>}{(accountData.posts||[]).map(post=><p key={post.id}>{post.name} — {post.tagline}</p>)}{(accountData.collections||[]).map(item=><p key={item.id}>{item.name}</p>)}{!accountData.user&&!(accountData.posts||[]).length&&!(accountData.collections||[]).length&&<p>No items were returned. This may reflect an empty list or provider privacy restrictions.</p>}</div>}
        <h3>Follow a user</h3><p>Review an exact username before changing your account’s following list. This requires Product Hunt’s Write permission.</p><label htmlFor="producthunt-username">Product Hunt username</label><input id="producthunt-username" value={username} maxLength={80} disabled={busy||!!pending} placeholder="@username" onChange={event=>setUsername(event.target.value)}/><div className="product-hunt-actions"><button className="btn" disabled={busy||!!pending||!username.trim()} onClick={()=>reviewFollow(true)}>Review follow</button><button className="btn" disabled={busy||!!pending||!username.trim()} onClick={()=>reviewFollow(false)}>Review unfollow</button></div></section>}
      {posts&&<section className="product-hunt-launches" aria-label="Recent Product Hunt launches"><h3>Recent launches · Product Hunt API</h3>{posts.length?posts.map(post=><article key={post.id}><h4>{safeLink(post.url)?<a href={safeLink(post.url)} target="_blank" rel="noopener noreferrer">{post.name} ↗</a>:post.name}</h4><p>{post.tagline}</p><span>{post.votesCount} votes · {post.commentsCount} comments</span></article>):<p>The API returned no launches for this request.</p>}</section>}
    </section>;
  }
  window.VellumUI=window.VellumUI||{};
  window.VellumUI.ProductHuntWorkspace=ProductHuntWorkspace;
})();
