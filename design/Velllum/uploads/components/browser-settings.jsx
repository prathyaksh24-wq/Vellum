(function () {
  const {useState, useEffect, useRef} = React;
  const CONFIRMED = new Set(['delete_profile','clear_data','save_download','remove_download']);
  const POLICY = [['allow','Always allow'],['ask','Ask for approval'],['block','Block']];
  const SITE_FIELDS = [['location','Location'],['camera','Camera'],['microphone','Microphone'],['notifications','Notifications'],['javascript','JavaScript'],['images','Images'],['popups','Pop-ups'],['third_party_cookies','Third-party cookies']];
  const IMPORT_FIELDS = ['search_engine','searxng_url','suggestions_enabled','agent_enabled','agent_browsing','agent_downloads','agent_history','agent_screenshots','show_full_url','web_link_destination','local_link_destination','ask_download_location','expire_site_permissions'];
  IMPORT_FIELDS.push('agent_interactions','cursor_size');
  function Choice({label, value, options, onChange, disabled}) {
    return <select aria-label={label} value={value} disabled={disabled} onChange={e => onChange(e.target.value)}>{options.map(([id,name]) => <option key={id} value={id}>{name}</option>)}</select>;
  }
  function Toggle({label, value, onChange, disabled}) {
    return <button type="button" className={'sw' + (value ? ' on' : '')} role="switch" aria-label={label} aria-checked={value} disabled={disabled} onClick={() => onChange(!value)}/>;
  }
  function Row({title, description, children}) {
    return <div className="bs-row"><div className="bs-copy"><strong>{title}</strong>{description && <p>{description}</p>}</div><div className="bs-control">{children}</div></div>;
  }
  function BrowserSettings({onAction, onConfirm, onCancel, onRefresh}) {
    const api = window.VellumApi.browser;
    const [view,setView] = useState(null), [section,setSection] = useState('Sessions');
    const [busy,setBusy] = useState(false), [error,setError] = useState(''), [note,setNote] = useState('');
    const [pending,setPending] = useState(null), [name,setName] = useState(''), [rename,setRename] = useState(null);
    const [folder,setFolder] = useState(null), [instance,setInstance] = useState(null), [query,setQuery] = useState(''), [limit,setLimit] = useState(50);
    const [clear,setClear] = useState(null), [site,setSite] = useState(''), [siteDraft,setSiteDraft] = useState(null);
    const [permissions,setPermissions] = useState(null), [importDraft,setImportDraft] = useState(null), [saveFolders,setSaveFolders] = useState({});
    const fileRef = useRef(null), alive = useRef(true), refreshRevision = useRef(0);
    const cursorFileRef=useRef(null);
    const uploadCursor=async event=>{
      const file=event.target.files?.[0];event.target.value='';
      if (!file) return;
      try {
        if(file.type!=='image/png' || file.size>65536) throw new Error('Choose a PNG up to 128 × 128 pixels and 64 KB.');
        const image=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
        await patch({cursor_image:image,cursor_style:'custom'});
      } catch(err){setError(err.message || 'This cursor image could not be loaded.');}
    };
    useEffect(() => {setPermissions(null);setSiteDraft(null);setClear(null);setSaveFolders({});}, [view?.preferences.active_profile_id]);
    const refresh = async () => {
      const revision = ++refreshRevision.current;
      const result = await api.settings();
      if (alive.current && refreshRevision.current===revision) setView(result);
      return result;
    };
    useEffect(() => {
      alive.current = true;
      refresh().catch(() => {if (alive.current) setError('Browser settings could not load. Try again.');});
      return () => {alive.current = false;};
    }, []);
    useEffect(() => {
      if (!view || busy || pending) return;
      const timer=setInterval(() => refresh().catch(() => {}),4000);
      return () => clearInterval(timer);
    }, [!!view,busy,!!pending]);
    const run = async command => {
      if (busy || pending) return;
      setBusy(true); setError(''); setNote('');
      try {
        const receipt = await onAction(CONFIRMED.has(command.operation) ? 'browser.settings.data' : 'browser.settings.manage',
          {...command, profile_id:command.profile_id || view.preferences.active_profile_id});
        if (receipt?.status === 'confirmation_required') setPending(receipt);
        else if (receipt?.status !== 'applied') throw new Error(receipt?.message || 'The change could not be saved.');
        else {await refresh(); await onRefresh?.(); setNote('Saved.');}
        return receipt;
      } catch (err) {setError(err.message || 'The change could not be saved. Try again.');}
      finally {if (alive.current) setBusy(false);}
    };
    const confirm = async () => {
      setBusy(true); setError('');
      try {
        const receipt = await onConfirm(pending);
        if (receipt?.status !== 'applied') throw new Error(receipt?.message || 'The operation could not be completed.');
        setPending(null); setClear(null); await refresh(); await onRefresh?.(); setNote('Done.');
      } catch (err) {setPending(null); setError(err.message || 'The operation could not be completed.');}
      finally {setBusy(false);}
    };
    const cancel = async () => {await onCancel?.(pending);setPending(null);};
    const patch = values => run({operation:'preferences',patch:values});
    const disabled = busy || !!pending;
    if (!view) return <div className="browser-settings"><h2 className="set-h">Browser</h2>{error ? <div role="alert"><p>{error}</p><button className="btn" onClick={() => refresh().catch(() => setError('Browser settings could not load. Try again.'))}>Try again</button></div> : <div className="bs-loading" aria-label="Loading browser settings"><div/><div/><div/></div>}</div>;
    const prefs = view.preferences, profile = prefs.profiles.find(item => item.id === prefs.active_profile_id);
    const rules = profile.site_rules || [];
    const saveRule = rule => run({operation:'site_rule',rule});
    const filteredHistory = view.history.filter(item => (item.title + ' ' + item.url).toLowerCase().includes(query.toLowerCase()));
    const importFile = async event => {
      try {
        const file = event.target.files?.[0];
        if (!file) return;
        if (file.size > 32000) throw new Error('Choose a Vellum browser preferences file smaller than 32 KB.');
        const data = JSON.parse(await file.text());
        if (data.format !== 'vellum-browser-preferences-v1' || !data.preferences || typeof data.preferences !== 'object') throw new Error('Choose an exported Vellum browser preferences file.');
        const selected = Object.fromEntries(IMPORT_FIELDS.filter(key => Object.hasOwn(data.preferences,key)).map(key => [key,data.preferences[key]]));
        if (!Object.keys(selected).length) throw new Error('This file has no browser preferences to import.');
        setImportDraft(selected); setError('');
      } catch (err) {setError(err.message || 'This preferences file could not be read.');}
      event.target.value = '';
    };
    const exportFile = () => {
      const preferences = Object.fromEntries(IMPORT_FIELDS.map(key => [key,prefs[key]]));
      const url = URL.createObjectURL(new Blob([JSON.stringify({format:'vellum-browser-preferences-v1',preferences},null,2)],{type:'application/json'}));
      const link = document.createElement('a'); link.href=url; link.download='vellum-browser-preferences.json';link.click();setTimeout(() => URL.revokeObjectURL(url),1000);
    };
    return <div className="browser-settings" data-ui-reference="browser-settings">
      <h2 className="set-h">Browser</h2><p className="bs-intro">Manage your Brave profiles, browsing activity and site access.</p>
      <Row title="BrowserAgent" description="Let Vellum use your browser when you ask. You can still browse with this off."><Toggle label="Enable BrowserAgent" value={prefs.agent_enabled} disabled={disabled} onChange={value => patch({agent_enabled:value})}/></Row>
      <Row title="Routine browser interactions" description="When you ask Vellum to browse, let it click, type and use keys for that task. Sensitive controls keep their approval or takeover checks."><Choice label="Routine browser interactions" value={prefs.agent_interactions || 'allow'} options={[['allow','Follow my request'],['ask','Ask for each action']]} disabled={disabled} onChange={value=>patch({agent_interactions:value})}/></Row>
      <div className="bs-tabs" role="tablist" aria-label="Browser settings sections">{['Sessions','General','Cursor','History & downloads','Site access'].map(label => <button type="button" role="tab" aria-selected={section===label} key={label} className={section===label ? 'on' : ''} onClick={() => {setSection(label);setQuery('');setLimit(50);}}>{label}</button>)}</div>
      {error && <p className="bs-error" role="alert">{error}</p>}{note && <p className="bs-note" role="status">{note}</p>}
      {pending && <div className="bs-confirm" role="alertdialog" aria-label="Confirm browser change"><strong>{pending.message}</strong><div className="bs-actions"><button className="btn" disabled={busy} onClick={cancel}>Cancel</button><button className="btn primary" disabled={busy} onClick={confirm}>{busy ? 'Working…' : 'Confirm'}</button></div></div>}
      {section==='Cursor' && <section aria-label="Browser cursor settings"><h3>Cursor</h3><p className="bs-help">Choose the pointer shown while BrowserAgent works. Your choice also appears when you move over the browser page. It does not change your Windows cursor.</p>
        <div className="bs-cursor-options">{[['classic','Classic'],['light','Light'],['ember','Ember'],['mint','Mint'],['pixel','Pixel'],...(prefs.cursor_image?[['custom','Uploaded']]:[])].map(([style,label])=><button type="button" key={style} aria-label={label+' cursor'} aria-pressed={(prefs.cursor_style || 'classic')===style} disabled={disabled} onClick={()=>patch({cursor_style:style})}><window.VellumUI.BrowserCursorGraphic preferences={{...prefs,cursor_style:style}} size={32}/><span>{label}</span></button>)}</div>
        <div className="bs-group"><Row title="Size"><Choice label="Cursor size" value={prefs.cursor_size || 28} options={[[20,'Small'],[28,'Medium'],[40,'Large'],[48,'Extra large']]} disabled={disabled} onChange={value=>patch({cursor_size:Number(value)})}/></Row>
          <Row title="Your own cursor" description="Upload a transparent PNG up to 128 × 128 pixels and 64 KB. It is saved locally."><input ref={cursorFileRef} hidden type="file" accept="image/png" aria-label="Upload cursor image" onChange={uploadCursor}/><button className="btn" disabled={disabled} onClick={()=>cursorFileRef.current.click()}>Upload PNG</button>{prefs.cursor_image && <button className="btn" disabled={disabled} onClick={()=>patch({cursor_image:'',cursor_style:'classic',cursor_hotspot_x:0,cursor_hotspot_y:0})}>Remove</button>}</Row>
          {prefs.cursor_style==='custom' && <Row title="Click point" description="The pixel within the displayed pointer that lines up with the click."><label>X <input className="bs-hotspot" type="number" min="0" max={(prefs.cursor_size || 28)-1} aria-label="Cursor click point X" value={prefs.cursor_hotspot_x || 0} disabled={disabled} onChange={event=>patch({cursor_hotspot_x:Number(event.target.value)})}/></label><label>Y <input className="bs-hotspot" type="number" min="0" max={(prefs.cursor_size || 28)-1} aria-label="Cursor click point Y" value={prefs.cursor_hotspot_y || 0} disabled={disabled} onChange={event=>patch({cursor_hotspot_y:Number(event.target.value)})}/></label></Row>}
        </div><p className="bs-help"><a href="https://custom-cursor.com/" target="_blank" rel="noopener noreferrer">Browse Custom Cursor</a>. Its collection installer uses their browser extension; Vellum’s upload accepts PNG files you already have.</p>
      </section>}
      {section==='Sessions' && <section aria-label="Browser profiles"><h3>Profiles</h3><p className="bs-help">Each profile keeps its own sign-ins, cookies and history. One profile runs at a time. Vellum opens it only when you ask.</p>
        <div className="bs-group">{prefs.profiles.map(item => <div className="bs-profile" key={item.id}><div className="bs-copy">{rename?.id===item.id ? <form onSubmit={async e => {e.preventDefault();const result=await run({operation:'rename_profile',profile_id:item.id,name:rename.name});if(result?.status==='applied')setRename(null);}}><input aria-label="Profile name" maxLength="40" value={rename.name} onChange={e => setRename({...rename,name:e.target.value})}/><button className="btn" disabled={disabled || !rename.name.trim()}>Save</button><button type="button" className="btn" onClick={() => setRename(null)}>Cancel</button></form> : <React.Fragment><strong>{item.name}</strong><p>{item.id===prefs.active_profile_id ? (view.running ? 'Active · Open' : 'Selected · Closed') : 'Closed'}</p></React.Fragment>}</div><div className="bs-actions"><button className="btn" disabled={disabled} onClick={() => run({operation:item.id===prefs.active_profile_id && view.running ? 'close_profile' : 'open_profile',profile_id:item.id})}>{item.id===prefs.active_profile_id && view.running ? 'Close' : 'Open'}</button>{item.id!==prefs.active_profile_id && <button className="btn" disabled={disabled} onClick={() => run({operation:'select_profile',profile_id:item.id})}>Select</button>}<button className="btn" disabled={disabled} onClick={() => setRename({id:item.id,name:item.name})}>Rename</button>{item.id!=='default' && <button className="btn bs-danger" disabled={disabled} onClick={() => run({operation:'delete_profile',profile_id:item.id})}>Delete</button>}</div></div>)}</div>
        <form className="bs-add" onSubmit={async e => {e.preventDefault();const result=await run({operation:'create_profile',name});if(result?.status==='applied')setName('');}}><input aria-label="New profile name" placeholder="Profile name, e.g. Work" maxLength="40" value={name} onChange={e => setName(e.target.value)}/><button className="btn" disabled={disabled || !name.trim() || prefs.profiles.length>=12}>Create profile</button></form>
        <h3>Recent activity · {profile.name}</h3><div className="bs-list">{view.activity.slice(0,30).map(item => <div className="bs-activity" key={item.id}><div><strong>{item.title || item.event.replaceAll('_',' ')}</strong>{item.url && <p title={item.url}>{item.url}</p>}</div><time dateTime={item.at}>{new Date(item.at).toLocaleString()}</time></div>)}{!view.activity.length && <p className="bs-empty">Pages visited and downloads from this profile will appear here.</p>}</div>
      </section>}
      {section==='General' && <section><h3>General</h3><div className="bs-group"><Row title="Search engine"><Choice label="Default search engine" value={prefs.search_engine} options={api.engines.map(engine => [engine.id,engine.name])} disabled={disabled} onChange={value => patch({search_engine:value})}/></Row>{prefs.search_engine==='searxng' && <Row title="SearXNG instance" description="Use an instance you run or trust."><form className="bs-add" onSubmit={async event => {event.preventDefault();const result=await patch({searxng_url:instance ?? prefs.searxng_url ?? ''});if(result?.status==='applied')setInstance(null);}}><input aria-label="Settings SearXNG instance" type="url" placeholder="https://search.example.org" value={instance ?? prefs.searxng_url ?? ''} onChange={event => setInstance(event.target.value)}/><button className="btn" disabled={disabled}>Save</button></form></Row>}<Row title="Search suggestions" description="Send what you type to the selected engine. Some engines may not provide suggestions."><Toggle label="Search suggestions" value={prefs.suggestions_enabled} disabled={disabled} onChange={value => patch({suggestions_enabled:value})}/></Row><Row title="Web links open in"><Choice label="Web link destination" value={prefs.web_link_destination} options={[['vellum','Vellum'],['default','Default browser']]} disabled={disabled} onChange={value => patch({web_link_destination:value})}/></Row><Row title="Local development links open in"><Choice label="Local link destination" value={prefs.local_link_destination} options={[['vellum','Vellum'],['default','Default browser']]} disabled={disabled} onChange={value => patch({local_link_destination:value})}/></Row><Row title="Show full URL" description="Show the path and query when the address bar is not focused."><Toggle label="Show full URL" value={prefs.show_full_url} disabled={disabled} onChange={value => patch({show_full_url:value})}/></Row><Row title="BrowserAgent history access" description="Allow account history reads through Vellum's existing history integration."><Choice label="Agent history access" value={prefs.agent_history} options={[['allow','Allow'],['block','Block']]} disabled={disabled} onChange={value => patch({agent_history:value})}/></Row><Row title="Page screenshots for BrowserAgent" description="The live preview stays visible to you. This controls the agent's screenshot tool."><Toggle label="Agent page screenshots" value={prefs.agent_screenshots==='allow'} disabled={disabled} onChange={value => patch({agent_screenshots:value ? 'allow' : 'block'})}/></Row></div>
        <h3>Preferences file</h3><p className="bs-help">Import or export preferences only. Sign-ins, history and profiles stay on this device.</p><div className="bs-actions"><button className="btn" disabled={disabled} onClick={() => fileRef.current.click()}>Import…</button><button className="btn" onClick={exportFile}>Export</button><input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={importFile}/></div>{importDraft && <div className="bs-inline"><p>Import {Object.keys(importDraft).length} browser preferences?</p><div className="bs-actions"><button className="btn" onClick={() => setImportDraft(null)}>Cancel</button><button className="btn" disabled={disabled} onClick={async () => {const result=await patch(importDraft);if(result?.status==='applied')setImportDraft(null);}}>Apply preferences</button></div></div>}
      </section>}
      {section==='History & downloads' && <section><h3>Downloads</h3><div className="bs-group"><Row title="Location" description={view.download_directory}><button className="btn" disabled={disabled} onClick={() => setFolder(prefs.download_directory)}>Change</button></Row>{folder!==null && <form className="bs-add" onSubmit={async e => {e.preventDefault();const result=await patch({download_directory:folder});if(result?.status==='applied')setFolder(null);}}><input aria-label="Download folder" placeholder="Absolute local folder path" value={folder} onChange={e => setFolder(e.target.value)}/><button className="btn" disabled={disabled}>Save</button><button type="button" className="btn" onClick={() => setFolder(null)}>Cancel</button></form>}<Row title="Ask where to save downloads" description="Hold each download until you choose a folder here and approve it."><Toggle label="Ask where to save downloads" value={prefs.ask_download_location} disabled={disabled} onChange={value => patch({ask_download_location:value})}/></Row></div>
        <div className="bs-list">{view.downloads.slice().reverse().map(item => <div className="bs-download" key={item.id}><div className="bs-copy"><strong>{item.name}</strong><p>{item.state.replaceAll('_',' ')}{item.size>0 ? ' · ' + (item.size/1024).toFixed(1) + ' KB' : ''}</p></div><div className="bs-actions">{item.state==='saved' && <button className="btn" disabled={disabled} onClick={async () => {try {await api.control({operation:'show_download',download_id:item.id});}catch(err){setError(err.message);}}}>Show in folder</button>}{item.state==='awaiting_approval' && <React.Fragment><input aria-label={'Save folder for ' + item.name} placeholder={view.download_directory} value={saveFolders[item.id] || ''} onChange={e => setSaveFolders({...saveFolders,[item.id]:e.target.value})}/><button className="btn" disabled={disabled} onClick={() => run({operation:'save_download',download_id:item.id,directory:saveFolders[item.id] || ''})}>Save…</button></React.Fragment>}<button className="btn" disabled={disabled} onClick={() => run({operation:'remove_download',download_id:item.id})}>{item.state==='awaiting_approval' ? 'Cancel' : 'Remove'}</button></div></div>)}{!view.downloads.length && <p className="bs-empty">Your downloads from this profile will appear here.</p>}</div>
        <h3>Browsing history · {profile.name}</h3><div className="bs-add"><input aria-label="Filter browsing history" placeholder="Find a page" value={query} onChange={e => {setQuery(e.target.value);setLimit(50);}}/><button className="btn" disabled={disabled} onClick={() => setClear(['history'])}>Clear browsing data</button></div>{clear && <div className="bs-inline"><p>This closes the selected profile's open session. Clearing cookies signs you out. Downloaded files stay on disk.</p>{[['history','Browsing history and activity'],['cookies','Cookies and site data'],['cache','Cached files'],['downloads','Download history']].map(([id,label]) => <label className="bs-check" key={id}><input type="checkbox" checked={clear.includes(id)} onChange={e => setClear(e.target.checked ? [...clear,id] : clear.filter(value => value!==id))}/>{label}</label>)}<div className="bs-actions"><button className="btn" onClick={() => setClear(null)}>Cancel</button><button className="btn bs-danger" disabled={disabled || !clear.length} onClick={() => run({operation:'clear_data',data_types:clear})}>Clear selected data…</button></div></div>}
        <div className="bs-list">{filteredHistory.slice(0,limit).map(item => <div className="bs-history" key={item.url}><strong>{item.title || item.url}</strong><p title={item.url}>{item.url}</p></div>)}{!filteredHistory.length && <p className="bs-empty">{query ? 'No matching pages.' : 'Pages you visit in this profile will appear here.'}</p>}</div>{filteredHistory.length>limit && <button className="btn" onClick={() => setLimit(limit+50)}>Show more</button>}
      </section>}
      {section==='Site access' && <section><h3>Agent permissions</h3><p className="bs-help">Browsing approval lasts for the open session. Clicks, typing and account actions keep their existing confirmation requirements.</p><div className="bs-group"><Row title="Default browsing"><Choice label="Default agent browsing" value={prefs.agent_browsing} options={POLICY} disabled={disabled} onChange={value => patch({agent_browsing:value})}/></Row><Row title="Default downloads"><Choice label="Default agent downloads" value={prefs.agent_downloads} options={POLICY} disabled={disabled} onChange={value => patch({agent_downloads:value})}/></Row></div>
        <h3>Site exceptions · {profile.name}</h3><p className="bs-help">Rules apply to one exact site, including its protocol and port.</p><div className="bs-rules">{rules.map(rule => <div className="bs-rule" key={rule.origin}><strong title={rule.origin}>{rule.origin}</strong><label className="bs-rule-control"><span>Browsing</span><Choice label={'Browsing for ' + rule.origin} value={rule.browsing} options={POLICY} disabled={disabled} onChange={value => saveRule({...rule,browsing:value})}/></label><label className="bs-rule-control"><span>Downloads</span><Choice label={'Downloads for ' + rule.origin} value={rule.downloads} options={POLICY} disabled={disabled} onChange={value => saveRule({...rule,downloads:value})}/></label><div className="bs-actions"><button className="btn" disabled={disabled} onClick={() => setSiteDraft({...rule,permissions:rule.permissions || profile.site_defaults})}>Site permissions</button><button className="btn" disabled={disabled} onClick={() => run({operation:'remove_site_rule',origin:rule.origin})}>Remove</button></div></div>)}{!rules.length && <p className="bs-empty">Add a site to give it different browsing, download or device permissions.</p>}</div><form className="bs-add" onSubmit={async e => {e.preventDefault();const result=await saveRule({origin:site,browsing:prefs.agent_browsing,downloads:prefs.agent_downloads});if(result?.status==='applied')setSite('');}}><input aria-label="Site origin" placeholder="https://example.com" value={site} onChange={e => setSite(e.target.value)}/><button className="btn" disabled={disabled || !site.trim()}>Add site</button></form>
        <h3>Website permissions</h3><p className="bs-help">Saving these closes the current session. Open it again to apply the changes. Device permissions are also subject to Windows settings. If a device request cannot be answered in the preview, add an explicit site permission here.</p><div className="bs-group">{SITE_FIELDS.map(([key,label]) => <Row key={key} title={label}><Choice label={label + ' permission'} value={(permissions || profile.site_defaults)[key]} options={key==='location' || key==='camera' || key==='microphone' || key==='notifications' ? [['ask','Ask'],['allow','Allow'],['block','Block']] : [['allow','Allow'],['block','Block']]} disabled={disabled} onChange={value => setPermissions({...profile.site_defaults,...permissions,[key]:value})}/></Row>)}</div>{permissions && <div className="bs-actions"><button className="btn" onClick={() => setPermissions(null)}>Discard</button><button className="btn" disabled={disabled} onClick={async () => {const result=await run({operation:'site_defaults',defaults:permissions});if(result?.status==='applied')setPermissions(null);}}>Save website permissions</button></div>}
        {siteDraft && <div className="bs-inline"><h3>Permissions for {siteDraft.origin}</h3>{SITE_FIELDS.filter(([key]) => key!=='third_party_cookies').map(([key,label]) => <Row key={key} title={label}><Choice label={label + ' for ' + siteDraft.origin} value={siteDraft.permissions[key]} options={['location','camera','microphone','notifications'].includes(key) ? [['ask','Ask'],['allow','Allow'],['block','Block']] : [['allow','Allow'],['block','Block']]} onChange={value => setSiteDraft({...siteDraft,permissions:{...siteDraft.permissions,[key]:value}})}/></Row>)}<div className="bs-actions"><button className="btn" onClick={() => setSiteDraft(null)}>Cancel</button><button className="btn" disabled={disabled} onClick={async () => {const result=await saveRule(siteDraft);if(result?.status==='applied')setSiteDraft(null);}}>Save site permissions</button></div></div>}
        <Row title="Remove unused device permissions" description="Reset site exceptions for camera, microphone, location and notifications after 90 days without a visit. Checked when the profile opens."><Toggle label="Remove unused device permissions" value={prefs.expire_site_permissions} disabled={disabled} onChange={value => patch({expire_site_permissions:value})}/></Row>
        <Row title="Website tools (WebMCP)" description="Website-provided agent tools are not connected to Vellum yet."><span className="bs-unavailable">Unavailable</span></Row>
      </section>}
    </div>;
  }
  window.VellumUI = window.VellumUI || {};
  window.VellumUI.BrowserSettings = BrowserSettings;
})();
