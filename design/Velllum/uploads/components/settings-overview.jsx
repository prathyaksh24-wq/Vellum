/* Settings presentation. Persistent changes use the existing App Action callbacks. */
(() => {
  const {useEffect,useRef,useState}=React;
  const VSelect=props=><window.VellumUI.VSelect {...props}/>;
  const Arrow=()=> <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>;
  const Search=()=> <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>;
  function ProviderLogo({provider}) {
    if(!provider?.icon)return null;
    return <span className="cfg-provider-logo" aria-hidden="true">{['ollama','openrouter','openai','opencode','kimi','groq','xai'].includes(provider.id)?<span style={{maskImage:`url(${provider.icon})`,WebkitMaskImage:`url(${provider.icon})`}}/>:<img src={provider.icon} alt=""/>}</span>;
  }
  function Configuration({providers=[],models=[],model,onModel,onModelProvider,keys={},keyStatus={},savingKey,onKeyChange,onSaveKey,initialProvider,ModelIcon,modelIcon}) {
    const source=models[0]?.route_provider || 'ollama';
    const [selected,setSelected]=useState(initialProvider || null);
    const [query,setQuery]=useState('');
    const [filter,setFilter]=useState('all');
    const detailRef=useRef(null);
    const chooseProvider=id=>{
      setSelected(id);
      if(window.matchMedia('(max-width:850px)').matches) requestAnimationFrame(()=>detailRef.current?.scrollIntoView({block:'start'}));
    };
    useEffect(()=>{if(initialProvider)setSelected(initialProvider);},[initialProvider]);
    useEffect(()=>{
      const request=event=>{if(event.detail?.provider)setSelected(event.detail.provider);};
      window.addEventListener('vellum:provider-key-requested',request);
      return()=>window.removeEventListener('vellum:provider-key-requested',request);
    },[]);
    const ready=provider=>provider.id==='ollama' || !!keyStatus[provider.id];
    const current=providers.find(provider=>provider.id===source);
    const entry=providers.find(provider=>provider.id===selected) || current;
    const matches=providers.filter(provider=>(filter!=='connected' || ready(provider)) && `${provider.name} ${provider.description}`.toLowerCase().includes(query.toLowerCase()));
    const connected=providers.filter(ready).length;
    return <div className="settings-overview">
      <header className="settings-view-head"><div><h1>Configuration</h1><p>Choose a provider and default model</p></div><span className="cfg-local-note"><span/>Keys stay on this device</span></header>
      <section className="cfg-current" aria-label="Current model">
        <div className="cfg-current-identity"><ProviderLogo provider={current}/><div><span className="settings-small-label">Current provider</span><strong>{current?.name || 'Loading providers…'}</strong></div><span className="cfg-state in-use">In use</span></div>
        <div className="cfg-current-model"><span>Default model</span><VSelect className="agent-select-control" ariaLabel="Default model" value={model} onValueChange={onModel} placeholder="Choose a model" disabled={!models.length} options={models.map(item=>({value:item.id,label:item.label,icon:modelIcon?.(item)}))}/></div>
      </section>
      <div className="cfg-provider-heading"><div><h2>Model providers</h2><p>Add a key to connect another account.</p></div><span>{connected} configured</span></div>
      <div className="cfg-provider-layout">
        <section className="cfg-provider-browser" aria-label="Provider library" id="provider-library">
          <div className="cfg-provider-tools"><label className="cfg-provider-search"><Search/><input type="search" aria-label="Search providers" placeholder="Search providers" value={query} onChange={event=>setQuery(event.target.value)}/></label><div className="cfg-provider-filter" aria-label="Filter providers">{[['all','All'],['connected','Configured']].map(([id,label])=><button type="button" key={id} aria-pressed={filter===id} onClick={()=>setFilter(id)}>{label}</button>)}</div></div>
          <div className="cfg-provider-grid">{matches.map(provider=><button type="button" key={provider.id} className={'cfg-provider-card'+(entry?.id===provider.id?' selected':'')} aria-pressed={entry?.id===provider.id} aria-controls="provider-connection-detail" onClick={()=>chooseProvider(provider.id)}><ProviderLogo provider={provider}/><span className="cfg-card-name">{provider.name}</span><span className="cfg-card-description">{provider.description}</span><span className={'cfg-card-status'+(provider.id===source?' active':'')}>{provider.id===source?'In use':provider.id==='ollama'?'On this device':keyStatus[provider.id]?'Key saved':'Add API key'}</span></button>)}</div>
          {!matches.length && <div className="cfg-provider-empty">No providers match “{query}”.<button type="button" onClick={()=>{setQuery('');setFilter('all');}}>Clear filters</button></div>}
        </section>
        <section ref={detailRef} id="provider-connection-detail" className="cfg-connection-detail" aria-label={entry?entry.name+' connection':'Provider connection'}>
          {entry ? <><a className="cfg-back-to-library" href="#provider-library">Back to providers</a><div className="cfg-detail-title"><ProviderLogo provider={entry}/><div><h2>{entry.name}</h2><span>{entry.requires_key?'API connection':'Local runtime'}</span></div></div><p className="cfg-detail-description">{entry.description}</p>
            {entry.id==='ollama' ? <div className="cfg-detail-message"><strong>Your local model</strong><div className="cfg-local-model">{ModelIcon && <ModelIcon model={{id:'ollama/gemma4:12b'}}/>}<span>Gemma 4 12B</span></div><p>Runs on your device through Ollama.</p></div> : <><div className="cfg-detail-status"><span className={'cfg-state'+(keyStatus[entry.id]?' saved':'')}>{keyStatus[entry.id]?'Key saved':'Not configured'}</span><a href={entry.key_url} target="_blank" rel="noopener noreferrer">Get an API key ↗</a></div><label className="cfg-key-label" htmlFor={'provider-key-'+entry.id}>{keyStatus[entry.id]?'Replace API key':'API key'}</label><input id={'provider-key-'+entry.id} type="password" className="cfg-provider-key" autoComplete="off" spellCheck="false" placeholder={keyStatus[entry.id]?'Paste a new key to replace it':'Paste your '+entry.name+' API key'} value={keys[entry.id] || ''} disabled={savingKey===entry.id} onChange={event=>onKeyChange(entry.id,event.target.value)} onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();onSaveKey(entry.id);}}}/><button type="button" className="cfg-primary-action" disabled={!!savingKey || !(keys[entry.id] || '').trim()} onClick={()=>onSaveKey(entry.id)}>{savingKey===entry.id?'Waiting for confirmation…':'Review & save key'}</button><p className="cfg-key-help">Vellum asks you to confirm before saving. Your saved key is never shown here.</p></>}
            {entry.id===source ? <div className="cfg-detail-footer">This provider is active in your model picker.</div> : entry.model_selection_supported ? <button type="button" className="cfg-use-provider" disabled={!ready(entry)} onClick={()=>onModelProvider(entry.id)}>Use {entry.name}<Arrow/></button> : <div className="cfg-detail-footer">You can save this API key here. Direct model selection for this connection is not available in this build.{ready(providers.find(provider=>provider.id==='openrouter') || {id:'openrouter'}) && ['anthropic','kimi','xai','meta','google'].includes(entry.id) && <button type="button" className="cfg-use-provider" onClick={()=>onModelProvider('openrouter')}>Browse models on OpenRouter<Arrow/></button>}</div>}
          </> : <div className="cfg-provider-empty">Loading provider connections…</div>}
        </section>
      </div>
      <p className="cfg-connection-footnote">A saved key is a connection setting. Available models and account access are managed separately.</p>
    </div>;
  }
  function General({theme,onTheme,dockPosition,onDockPosition,dockLocked,onDockLocked,onNavigate,model,ModelIcon}) {
    return <div className="settings-overview settings-general-view">
      <header className="settings-view-head"><div><h1>General</h1><p>Appearance, workspace, and privacy</p></div></header>
      <section className="settings-preference-section"><div className="settings-section-heading"><h2>Appearance</h2><p>Choose how Vellum looks</p></div><div className="settings-preference-list">
        <div className="settings-preference-row"><div><strong>Theme</strong><p>Choose a light or dark interface.</p></div><div className="settings-theme-options">{[['light','Light'],['dark','Dark']].map(([value,label])=><button type="button" key={value} aria-pressed={theme===value} onClick={()=>{if(theme!==value)onTheme(value);}}><span className={'settings-theme-swatch '+value}/>{label}</button>)}</div></div>
        <button type="button" className="settings-preference-row settings-preference-link" onClick={()=>onNavigate('Appearance')}><span><strong>Background & accent</strong><span className="settings-row-description">Choose a background and accent</span></span><Arrow/></button>
      </div></section>
      <section className="settings-preference-section"><div className="settings-section-heading"><h2>Workspace</h2><p>Models and navigation</p></div><div className="settings-preference-list">
        <button type="button" className="settings-preference-row settings-preference-link" onClick={()=>onNavigate('Configuration')}><span><strong>Models & connections</strong><span className="settings-row-description">Manage providers and your default model.</span></span><span className="settings-current-model">{ModelIcon && <ModelIcon model={model || {}}/>}<span>{model?.label || 'Choose a model'}</span><Arrow/></span></button>
        <div className="settings-preference-row"><div><strong>Dock position</strong><p>Choose where the dock appears</p></div><VSelect className="dock-pos-select" ariaLabel="Dock position" value={dockPosition} onValueChange={onDockPosition} options={[{value:'auto',label:'Automatic'},{value:'top',label:'Top'},{value:'bottom',label:'Bottom'},{value:'left',label:'Left'},{value:'right',label:'Right'}]}/></div>
        <div className="settings-preference-row"><div><strong>Keep dock visible</strong><p>Keep quick actions in view while you work.</p></div><button type="button" role="switch" aria-label="Keep dock visible" aria-checked={dockLocked} className={'settings-preference-switch'+(dockLocked?' on':'')} onClick={()=>onDockLocked(!dockLocked)}><span/></button></div>
      </div></section>
      <section className="settings-preference-section"><div className="settings-section-heading"><h2>Personalization & privacy</h2><p>Memory, responses, and your account</p></div><div className="settings-preference-list"><button type="button" className="settings-preference-row settings-preference-link" onClick={()=>onNavigate('Personalization')}><span><strong>Personalization</strong><span className="settings-row-description">Response preferences, memory, and sharing controls.</span></span><Arrow/></button><button type="button" className="settings-preference-row settings-preference-link" onClick={()=>onNavigate('Accounts')}><span><strong>Your account</strong><span className="settings-row-description">Manage the accounts you use with Vellum.</span></span><Arrow/></button></div></section>
    </div>;
  }
  window.VellumUI=window.VellumUI || {};
  window.VellumUI.SettingsOverview={Configuration,General};
})();
