/* Faithful handoff presentation over Vellum's canonical plugin/skill owners. */
(function () {
  const {
    useState,
    useEffect,
    useRef,
    createContext,
    useContext
  } = React;
  const A = window.VellumPluginDesignAssets,
    X = createContext(null),
    useX = () => useContext(X);
  const name = x => x.display_name || x.normalized_name || x.name || x.id;
  const normalize = x => String(x || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  const brand = p => ({
    'googledrive': 'gdrive',
    'googlecalendar': 'gcal'
  })[normalize(p.name)] || normalize(p.name);
  const Ic = ({
    n,
    s = 18
  }) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" dangerouslySetInnerHTML={{
    __html: A.I[n] || A.I.plug
  }} />;
  const link = value => {
    try {
      const u = new URL(value);
      return ['https:', 'http:'].includes(u.protocol) ? u.href : null;
    } catch {
      return null;
    }
  };
  function Tile({
    p,
    sz = 46,
    i = 26,
    r = 12
  }) {
    const {
        Logo
      } = useX(),
      b = A.logos[brand(p)];
    return <span className="t" style={{
      width: sz,
      height: sz,
      borderRadius: r,
      background: b?.gradient ? 'linear-gradient(135deg,#00C4CC,#7D2AE8)' : b ? '#fff' : 'var(--panel,#202020)'
    }}>{b ? <span style={{
        width: i,
        height: i,
        display: 'flex'
      }} dangerouslySetInnerHTML={{
        __html: b.svg
      }} /> : Logo ? <Logo c={p} size={i} /> : <Ic n="plug" s={i} />}</span>;
  }
  function ActionLink(props) {
    return <a className={props.className} style={props.style} aria-label={props['aria-label']} href="#" onClick={event => {
      event.preventDefault();
      props.onClick?.(event);
    }}>{props.children}</a>;
  }
  const Sw = ({
    value,
    onChange,
    label,
    disabled
  }) => <button className={'sw' + (value ? ' on' : '')} role="switch" aria-checked={!!value} aria-label={label} disabled={disabled} onClick={e => {
    e.stopPropagation();
    onChange(!value);
  }}><i /></button>;
  const Search = ({
    q,
    setQ,
    ph
  }) => <label className="sb"><span className="vh">{ph}</span><Ic n="search" s={16} /><input type="search" placeholder={ph} value={q} onChange={e => setQ(e.target.value)} /></label>;
  function Pop({
    items,
    close,
    style,
    cls = ''
  }) {
    const ref = useRef();
    useEffect(() => {
      const f = e => {
        if (e.key === 'Escape' || !ref.current?.contains(e.target)) close();
      };
      document.addEventListener('pointerdown', f);
      document.addEventListener('keydown', f);
      return () => {
        document.removeEventListener('pointerdown', f);
        document.removeEventListener('keydown', f);
      };
    }, [close]);
    return <div ref={ref} className={'mu ' + cls} role="menu" style={style}>{items.map((x, i) => x.label === '-' ? <hr key={i} /> : <button role="menuitem" key={i} disabled={x.disabled} title={x.reason} className={x.danger ? 'rd' : ''} onClick={e => {
        e.stopPropagation();
        close();
        x.action?.();
      }}>{x.icon && <Ic n={x.icon} s={16} />}{x.label}</button>)}</div>;
  }
  function Dlg({
    w = 560,
    close,
    label,
    children
  }) {
    const ref = useRef(),
      previous = useRef(document.activeElement);
    useEffect(() => {
      ref.current?.focus();
      const f = e => {
        if (e.key === 'Escape') {
          e.stopImmediatePropagation();
          close();
        }
        if (e.key === 'Tab') {
          const nodes = [...ref.current.querySelectorAll('button,input,select,textarea,a[href],[tabindex="0"]')].filter(n => !n.disabled);
          if (!nodes.length) {
            e.preventDefault();
            return;
          }
          if (e.shiftKey && (document.activeElement === nodes[0] || document.activeElement === ref.current)) {
            e.preventDefault();
            nodes.at(-1).focus();
          } else if (!e.shiftKey && (document.activeElement === nodes.at(-1) || document.activeElement === ref.current)) {
            e.preventDefault();
            nodes[0].focus();
          }
        }
      };
      document.addEventListener('keydown', f, true);
      return () => {
        document.removeEventListener('keydown', f, true);
        previous.current?.focus?.();
      };
    }, []);
    return <div className="ov" onMouseDown={e => e.target === e.currentTarget && close()}><div ref={ref} className="dl" style={{
        width: w
      }} tabIndex={-1} role="dialog" aria-modal="true" aria-label={label}>{children}</div></div>;
  }
  const DH = ({
    p,
    t,
    sub,
    close
  }) => <div className="dh">{p && <Tile p={p} sz={44} i={26} r={10} />}<div><h2>{t}</h2>{sub}</div><button className="ib" aria-label="Close" onClick={close}><Ic n="x" /></button></div>;
  function Add({
    settings
  }) {
    const {
        setDlg
      } = useX(),
      [open, setOpen] = useState(false);
    return <><button className={settings ? 'addb wt' : 'add'} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>Add <Ic n="chevD" s={14} /></button>{open && <Pop cls="am" close={() => setOpen(false)} items={[{
        icon: 'plug',
        label: 'Create plugin',
        action: () => setDlg({
          t: 'create'
        })
      }, {
        icon: 'plus',
        label: 'Add a marketplace',
        action: () => setDlg({
          t: 'marketplace'
        })
      }, ...(!settings ? [{
        icon: 'file',
        label: 'Upload plugin archive',
        action: () => setDlg({
          t: 'archive'
        })
      }] : []), {
        icon: 'mcp',
        label: settings ? 'Add MCP server' : 'Add custom MCP server',
        action: () => setDlg({
          t: 'mcp'
        })
      }]} />}</>;
  }
  function usePluginMenus(p) {
    const {
      go,
      setDlg,
      tryNow
    } = useX();
    return [{
      icon: 'chat',
      label: 'Try now',
      action: () => tryNow(p)
    }, {
      icon: 'gear',
      label: 'Manage',
      action: () => setDlg({
        t: 'manage',
        p
      })
    }, {
      icon: 'gear',
      label: 'Plugin settings',
      action: () => go({
        v: 'settings',
        p: p.id
      })
    }, {
      label: '-'
    }, {
      icon: 'trash',
      label: 'Uninstall',
      danger: true,
      disabled: p.protected || p.required || p.manageable === false,
      reason: p.protected ? 'Required by Vellum' : undefined,
      action: () => setDlg({
        t: 'uninstall',
        p
      })
    }];
  }
  function Row({
    p
  }) {
    const {
        go,
        setDlg
      } = useX(),
      [open, setOpen] = useState(false),
      items = usePluginMenus(p);
    return <div className={'r' + (open ? ' hi' : '')} role="button" tabIndex={0} onKeyDown={e => e.target === e.currentTarget && e.key === 'Enter' && go({
      v: 'detail',
      p: p.id
    })} onClick={() => go({
      v: 'detail',
      p: p.id
    })}><Tile p={p} /><div className="m"><b>{p.name}</b><span>{p.description || p.notes}</span></div><button className="a" aria-label={(p.installed === false ? 'Install ' : 'Manage ') + p.name} onClick={e => {
        e.stopPropagation();
        p.installed === false ? setDlg({
          t: 'install',
          p
        }) : setOpen(!open);
      }}><Ic n={p.installed === false ? 'plus' : 'dots'} s={22} /></button>{open && <Pop close={() => setOpen(false)} items={items} />}</div>;
  }
  function Directory({
    category
  }) {
    const {
        plugins,
        go,
        refresh,
        loading
      } = useX(),
      [q, setQ] = useState(''),
      [seg, setSeg] = useState('Public');
    const sections = A.SECS.filter(([title]) => ['Popular', 'New & Noteworthy'].includes(title)).map(([title, keys]) => [title, keys.map(k => plugins.find(p => brand(p) === k)).filter(Boolean)]);
    const groups = new Map();
    for (const plugin of plugins) {
      const category = plugin.category || 'Other';
      if (!groups.has(category)) groups.set(category, new Map());
      groups.get(category).set(plugin.id, plugin);
    }
    const order = ['CRM & Communication', 'Productivity', 'Creativity', 'Developer Tools', 'Web & Research', 'Data & Analytics', 'Memory & Knowledge', 'Food & Experiences', 'Media & Entertainment', 'Automation', 'Writing & Documents', 'Personalization', 'Security'];
    for (const category of [...groups.keys()].sort((a, b) => (order.indexOf(a) < 0 ? 99 : order.indexOf(a)) - (order.indexOf(b) < 0 ? 99 : order.indexOf(b)) || a.localeCompare(b))) {
      sections.push([category, [...groups.get(category).values()].sort((a, b) => a.name.localeCompare(b.name))]);
    }
    const match = p => (p.name + ' ' + p.description).toLowerCase().includes(q.toLowerCase()) && (seg !== 'Personal' || p.id.startsWith('custom-'));
    return <div className="cc">{category ? <><nav className="bc"><ActionLink onClick={() => go({
            v: 'directory'
          })}>Plugins</ActionLink><Ic n="chevR" s={14} /><b>{category}</b></nav><h1>{category}</h1><p className="sub">A curated selection of useful and noteworthy plugins.</p></> : <><div className="hd"><div><h1>Plugins</h1><p className="sub">Connect plugins to let Vellum work across your tools</p></div><div className="tl"><Search q={q} setQ={setQ} ph="Search plugins" /><button className="ib" aria-label="Refresh" disabled={loading} onClick={refresh}><Ic n="refresh" /></button><button className="ib f" aria-label="Manage plugins" onClick={() => go({
              v: 'settings'
            })}><Ic n="gear" /></button><Add /></div></div><div className="seg">{['Public', 'Personal'].map(s => <button key={s} className={seg === s ? 'on' : ''} onClick={() => setSeg(s)}>{s}</button>)}</div></>}{loading && <p className="notice" role="status">Loading your plugins…</p>}{sections.filter(([t]) => !category || t === category).map(([t, list]) => {
        const rows = list.filter(match);
        return rows.length > 0 && <section key={t}>{!category && <ActionLink className="sh" onClick={() => go({
            v: 'category',
            category: t
          })}>{t}<Ic n="chevR" s={16} /></ActionLink>}<div className="g">{rows.map(p => <Row key={p.id} p={p} />)}</div></section>;
      })}{!loading && !plugins.some(match) && <p className="notice">{seg === 'Personal' ? 'No personal plugins yet. Use Add → Create plugin to make one.' : 'No plugins match this search.'}</p>}</div>;
  }
  const OWNERS = {
    linear: 'LinearWorkspace',
    github: 'GitHubConnection',
    slack: 'SlackConnection',
    airtable: 'AirtableConnection',
    notion: 'NotionConnection',
    apify: 'ApifyConnection',
    firecrawl: 'FirecrawlConnection',
    exa: 'ExaConnection',
    tavily: 'TavilyConnection',
    supabase: 'SupabaseConnection',
    vercel: 'VercelConnection',
    clickup: 'ClickUpConnection',
    hubspot: 'HubSpotConnection',
    asana: 'AsanaConnection',
    swiggy: 'SwiggyConnection',
    district: 'DistrictConnection',
    serpapi: 'SerpApiConnection',
    'app-69b7bed23a9481919d2378ab225cddeb': 'ProductHuntWorkspace'
  };
  function DiscordConnection({p,children}) {
    const [status,setStatus]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
    const readStatus=async()=>{
      setBusy(true);setError('');
      try{const next=await window.VellumApi.plugins.discordStatus();setStatus({...next,message:next.connected?'Discord bot connection verified.':next.configured?'Verify the bot connection and install it in the intended server.':'Discord bot setup is managed by the backend.'});}
      catch(e){setError(e.message||'Discord status could not be read.');}
      finally{setBusy(false);}
    };
    useEffect(()=>{if(p.enabled!==false)readStatus();},[p.enabled]);
    const connect=async()=>{
      if(busy||p.enabled===false)return;
      const popup=window.open('','vellum-discord-install','width=720,height=760');
      setBusy(true);setError('');
      try{
        const result=await window.VellumApi.plugins.discordInstall();
        const target=new URL(result.authorization_url);
        if(target.origin!=='https://discord.com'||target.pathname!=='/oauth2/authorize'||target.username||target.password)throw Error('Discord returned an invalid bot authorization URL.');
        if(popup)popup.location.href=target.href;else window.open(target.href,'_blank','noopener,noreferrer');
      }catch(e){popup?.close();setError(e.message||'Discord installation could not be started.');}
      finally{setBusy(false);}
    };
    return children({bot:true,status,busy,error,connect,readStatus});
  }
  function PublicMcpConnection({p, children}) {
    const [tools,setTools]=useState(null), [busy,setBusy]=useState(false), [error,setError]=useState('');
    const enabled=p.enabled!==false && p.installed!==false;
    useEffect(()=>{if(!enabled)setTools(null);},[enabled]);
    const browse=async()=>{
      if(!enabled||busy)return;
      setBusy(true);setError('');
      try{const result=await window.VellumApi.plugins.connectorTools(p.id,p.mcp_connectors[0].name);setTools(result.tools);}
      catch(e){setTools(null);setError(e.message||'The public MCP server could not be reached.');}
      finally{setBusy(false);}
    };
    return children({anonymous:true,tools:enabled?tools:null,busy,error,browse,status:{configured:enabled,connected:enabled&&tools!==null,
      message:enabled?'Public MCP server. No sign-in or API key required.':'Enable this plugin to use its public MCP server.'}});
  }
  function Connection({
    p,
    children
  }) {
    const {
        refresh
      } = useX(),
      google = ['google-workspace', 'gmail', 'google-drive', 'google-calendar', 'google-contacts'].includes(p.id),
      C = window.VellumUI[google ? 'GoogleConnections' : OWNERS[p.id]];
    const previousStatus = useRef(null);
    const syncStatus = next => {
      const key = JSON.stringify([next.status, next.configured, next.connected]);
      const old = previousStatus.current;
      previousStatus.current = key;
      if (old !== null && key !== old) refresh();
    };
    if(p.id==='discord')return <DiscordConnection p={p}>{children}</DiscordConnection>;
    if(p.metadata?.connection?.anonymous)return <PublicMcpConnection p={p}>{children}</PublicMcpConnection>;
    return C ? <C enabled={p.enabled !== false} onStatus={syncStatus} onChanged={refresh} revision={p.enabled} render={children} /> : children({
      status: p.metadata?.connection || {
        connected: p.configured && p.status === 'ready'
      },
      unsupported: true
    });
  }
  function Feedback({
    c,
    p
  }) {
    return <>{c.status?.configured && !c.status.connected && !c.error && <p className="notice" role="status">{c.status.message}</p>}{c.error && <p className="error" role="alert">{c.error}</p>}{c.flow && <p className="notice" role="status">{c.flow.message || 'Waiting for authorization…'}{c.flow.status === 'pending' && c.run && <button className="bs" disabled={c.busy} onClick={() => c.run(p.id + '.connection.oauth.cancel', {
          flow_id: c.flow.flow_id
        })}>Cancel sign-in</button>}</p>}{c.pending && <div className="ds" role="group" aria-label="Review connection change"><h3>Review connection change</h3><p>{c.pending.receipt?.message || 'Review this change before applying it.'}</p><div className="df"><button className="bs" disabled={c.busy} onClick={() => c.decide(false)}>Cancel</button><button className="bt" disabled={c.busy} onClick={() => c.decide(true)}>Confirm</button></div></div>}</>;
  }
  function Setup({
    c,
    p
  }) {
    if (c.reviewSetup) return <details className="ds" open={!c.status?.app_registered}><summary>Set up your {p.name} app</summary><label className="fd">Client ID<input className="fi" value={c.clientId} onChange={e => c.setClientId(e.target.value)} autoComplete="off" /></label><label className="fd">Client secret<input className="fi" type="password" value={c.clientSecret} onChange={e => c.setClientSecret(e.target.value)} autoComplete="off" /></label><button className="bs" disabled={c.busy || !c.clientId || !c.clientSecret} onClick={c.reviewSetup}>Review app setup</button></details>;
    if (p.id === 'slack' && !c.status?.oauth_available) return <div className="ds"><h3>Set up your Slack app</h3>{c.setup && <details><summary>App manifest</summary><pre className="tool-schema">{JSON.stringify(c.setup.manifest, null, 2)}</pre></details>}<label className="fd">App ID<input className="fi" value={c.appId} onChange={e => c.setAppId(e.target.value)} /></label><label className="fd">Client ID<input className="fi" value={c.clientId} onChange={e => c.setClientId(e.target.value)} /></label><button className="bs" disabled={c.busy || !c.appId || !c.clientId} onClick={() => c.run('slack.connection.configure', {
        app_id: c.appId.trim(),
        client_id: c.clientId.trim()
      })}>Save app registration</button></div>;
    if (c.stage || p.id === 'serpapi') return <form className="ds" onSubmit={c.stage || c.connect}><label className="fd">{p.id === 'serpapi' ? 'API key' : 'Developer token'}<input type="password" className="fi" autoComplete="off" value={c.token ?? c.key ?? ''} onChange={e => (c.setToken || c.setKey)(e.target.value)} /></label><button className="bt" disabled={c.busy || !(c.token || c.key)}>Review connection</button></form>;
    return null;
  }
  function GoogleChooser({
    p,
    c
  }) {
    return <Dlg w={560} close={() => c.setOpen(false)} label="Choose Google plugins to install"><DH p={p} t="Choose Google plugins to install" close={() => c.setOpen(false)} /><p className="sub">You can revisit this anytime in settings</p><div className="ds">{c.status?.services?.map(s => <div className="ln" key={s.id}><span className="gr">{s.name}</span><Sw value={c.selected.includes(s.id)} label={s.name} onChange={v => c.setSelected(old => v ? [...old, s.id] : old.filter(x => x !== s.id))} /></div>)}</div><label className="fd">Access<select className="fi" value={c.access} onChange={e => c.setAccess(e.target.value)}><option value="read">Read</option><option value="manage">Read, create, edit and delete</option></select></label><Feedback p={p} c={c} /><div className="df"><button className="bs" onClick={() => c.setOpen(false)}>Cancel</button><button className="bt" disabled={c.busy} onClick={c.install}>Install selected plugins</button></div></Dlg>;
  }
  function Accounts({
    p,
    c
  }) {
    const [menu, setMenu] = useState(false),
      {
        setError
      } = useX(),
      connected = c.status?.connected,
      account = c.status?.email || c.status?.account_name || c.status?.workspace_name || 'Authorized account',
      connect = () => c.status?.configured && !c.status?.connected && c.run ? c.run((p.id.startsWith('app-') ? 'producthunt' : p.id) + '.connection.verify') : c.choose ? c.choose() : c.connect?.();
    if(c.bot)return <div className="ds"><h2 className="h2s">Discord bot connection</h2><p className="notice">{c.status?.message||'Checking Discord connection…'}</p><div className="df"><button className="bt" disabled={c.busy||p.enabled===false} onClick={c.connect}>Install bot</button><button className="bs" disabled={c.busy||p.enabled===false} onClick={c.readStatus}>Verify connection</button></div><Feedback p={p} c={c}/></div>;
    if(c.anonymous)return <div className="ds"><h2 className="h2s">Public MCP connection</h2><p className="notice">{c.status.message}</p><button className="bs" disabled={c.busy||p.enabled===false} onClick={c.browse}>{c.busy?'Verifying…':'Verify connection'}</button>{c.tools&&<p className="notice" role="status">Connected · {c.tools.length} published tools available</p>}<Feedback p={p} c={c}/></div>;
    return <><Setup p={p} c={c} />{connected ? <><h2 className="h2s">Connected accounts</h2><div className="lc" style={{
          marginTop: 0
        }}><div className="li"><span className="av2">{account[0]?.toUpperCase()}</span><span className="gr">{account}</span><button className="ib" aria-label="Account actions" aria-haspopup="menu" onClick={() => setMenu(!menu)}><Ic n="dots" /></button>{menu && <Pop close={() => setMenu(false)} style={{
              top: 54,
              width: 200
            }} items={[{
              icon: 'pencil',
              label: 'Rename account',
              disabled: true,
              reason: 'The provider supplies this account name.'
            }, {
              icon: 'refresh',
              label: 'Reconnect',
              action: connect
            }, {
              icon: 'x',
              label: 'Disconnect',
              danger: true,
              action: () => c.disconnect ? c.disconnect() : c.run?.((p.id.startsWith('app-') ? 'producthunt' : p.id) + '.connection.disconnect')
            }]} />}</div><div className="li" role="button" tabIndex={0} onClick={() => setError('This connector supports one account on this device. Reconnect to change accounts.')} onKeyDown={e => e.target === e.currentTarget && e.key === 'Enter' && setError('Reconnect to change accounts.')}><span className="pls"><Ic n="plus" /></span><span>Connect another account</span></div></div></> : <div className="lc" style={{
        marginTop: 28
      }}><div className="li" style={{
          minHeight: 64
        }}><span className="gr">{p.name}</span><button className="cb" disabled={p.enabled === false || c.busy || !!c.pending || c.flow?.status === 'pending' || c.unsupported || !c.connect && !c.choose} onClick={connect}>{c.busy ? 'Connecting…' : c.status?.configured && c.run ? 'Verify connection' : 'Connect'}</button></div></div>}{p.id === 'swiggy' && c.status?.services && <div className="ds">{c.status.services.map(s => <div className="ln" key={s.id}><span className="gr">{s.name}</span><Sw label={s.name} value={s.enabled} disabled={c.busy} onChange={v => c.run('swiggy.connection.configure', {
            services: c.status.services.filter(x => x.id === s.id ? v : x.enabled).map(x => x.id)
          })} /></div>)}</div>}{c.unsupported && <p className="notice">{p.notes || 'Managed by its source installation.'}</p>}<Feedback p={p} c={c} />{c.open && <GoogleChooser p={p} c={c} />}</>;
  }
  function Detail({
    p,
    settings = false
  }) {
    const {
        go,
        setDlg,
        tryNow,
        skills,
        renderDiscord
      } = useX(),
      [workspaceOpen,setWorkspaceOpen]=useState(false),
      [open, setOpen] = useState(false),
      items = usePluginMenus(p),
      ss = skills.filter(s => s.owner_plugin === p.id),
      included = ss.length ? ss : p.skills || [],
      meta = p.metadata || {},
      info = [['Developer', p.developer || meta.provider || 'Not supplied'], ['Version', p.version || 'Not supplied'], ['Website', meta.website || p.website], ['Source', meta.integration || p.source], ['Authorization supported', meta.connection?.auth_type || 'Provider managed'], ['Authorization used', meta.connection?.auth_type || 'Not connected']];
    return <div className="cc"><nav className="bc" aria-label="Breadcrumb"><ActionLink onClick={() => go({
          v: settings ? 'settings' : 'directory'
        })}>{settings ? 'Plugin settings' : 'Plugins'}</ActionLink><Ic n="chevR" s={14} /><b>{p.name}</b></nav>{settings ? <div className="hd3"><Tile p={p} sz={76} i={44} r={18} /><div className="gr"><h1 style={{
            fontSize: 24
          }}>{p.name}</h1><span style={{
            color: 'var(--dim,#B4B4B4)',
            fontSize: 13
          }}>{p.description}</span></div><button className="bo" onClick={() => go({
          v: 'detail',
          p: p.id
        })}>View details</button><button className="dn2" disabled={p.protected || p.required || p.manageable === false} onClick={() => setDlg({
          t: 'uninstall',
          p
        })}>Uninstall</button></div> : <div className="dc" style={{
        paddingTop: 8
      }}><Tile p={p} sz={76} i={44} r={18} /><div className="dt"><h1 style={{
            fontSize: 24
          }}>{p.name}</h1><div className="dact" style={{
            position: 'relative'
          }}>{p.installed !== false ? <><button className="ib" aria-label="More actions" aria-haspopup="menu" onClick={() => setOpen(!open)}><Ic n="dots" s={20} /></button>{open && <Pop close={() => setOpen(false)} style={{
                top: 44
              }} items={items} />}<button className="bt" onClick={() => tryNow(p)}><Ic n="chat" s={14} />Try now</button></> : <button className="bt" onClick={() => setDlg({
              t: 'install',
              p
            })}><Ic n="plus" s={14} />Install plugin</button>}</div></div><p className="sub">{p.description}</p></div>}{settings ? <Connection key={p.id} p={p}>{c => <Accounts p={p} c={c} />}</Connection> : <><div className="hero">{(A.prompts[brand(p)] || [p.description, p.notes || 'Use the connected account’s available tools.', meta.integration || p.category || 'Explore this plugin']).map((t, i) => <div className="pr" key={i}><Tile p={p} sz={20} i={16} r={4} /><p><b>{p.name}</b> {t}</p><button className="ar" aria-label="Try this prompt" onClick={() => tryNow(p, t)}><Ic n="fwd" s={14} /></button></div>)}</div><p className="ds0">{p.notes || p.description}</p><h2 className="sc">Apps <span>{p.apps?.length || 0}</span></h2>{(p.apps || []).map(a => <div className="sr" role="button" tabIndex={0} key={a.id || a.name} onClick={() => setDlg({
          t: 'app',
          p,
          app: a
        })} onKeyDown={e => e.target === e.currentTarget && e.key === 'Enter' && setDlg({
          t: 'app',
          p,
          app: a
        })}><Tile p={p} sz={44} i={26} r={10} /><div className="m"><b>{name(a)}</b><span>{a.description || p.description}</span></div><Ic n="chevR" s={16} /></div>)}</>}{p.id==='discord'&&renderDiscord&&<details className="ds" onToggle={e=>setWorkspaceOpen(e.currentTarget.open)}><summary>Discord workspace and data import</summary>{workspaceOpen&&renderDiscord()}</details>}{(p.mcp_connectors||[]).length>0&&<section aria-label="MCP servers"><h2 className="sc">MCP servers <span>{p.mcp_connectors.length}</span></h2>{p.mcp_connectors.map(server=><div className="sr" role="button" tabIndex={0} key={server.name||server.id} aria-label={'Open MCP server '+name(server)} onClick={()=>setDlg({t:'app',p,app:server,mcp:true})} onKeyDown={e=>e.target===e.currentTarget&&e.key==='Enter'&&setDlg({t:'app',p,app:server,mcp:true})}><Tile p={p} sz={44} i={26} r={10}/><div className="m"><b>{name(server)}</b><span>{server.description||p.description}</span></div><Ic n="chevR" s={16}/></div>)}</section>}{included.length > 0 && <><h2 className={settings ? 'h2s' : 'sc'}>Skills <span>{included.length}</span></h2><div className={settings ? 'lc' : ''} style={settings ? {
          marginTop: 0
        } : undefined}>{included.map(s => <div className={settings ? 'li' : 'sr'} key={s.id || s.name} role="button" tabIndex={0} onClick={() => setDlg({
            t: 'skill',
            s
          })} onKeyDown={e => e.target === e.currentTarget && e.key === 'Enter' && setDlg({
            t: 'skill',
            s
          })}><Ic n="cubeo" s={22} /><div className="m"><b>{name(s)}</b><span>{s.description}</span></div><Ic n="chevR" s={16} /></div>)}</div></>}{settings ? <><h2 className="h2s">About</h2><div className="lc" style={{
          marginTop: 0
        }}>{info.map(([a, b]) => <div className="ab" key={a}><span>{a}</span><span>{link(b) ? <a href={b} target="_blank" rel="noopener noreferrer">{b}</a> : b || 'Not supplied'}</span></div>)}</div></> : <><h2 className="sc">Information</h2><dl className="in" aria-label="Plugin information">{[['Capabilities', (p.capabilities || []).join(', ') || 'Published tools'], ...info.slice(0, 2), ['Category', p.category], ['Source', meta.integration || p.source]].map(([a, b]) => <React.Fragment key={a}><dt>{a}</dt><dd>{b}</dd></React.Fragment>)}{[['Website', meta.website || p.website], ['Documentation', meta.documentation_url]].map(([a, b]) => <React.Fragment key={a}><dt>{a}</dt><dd>{link(b) ? <a href={b} target="_blank" rel="noopener noreferrer" aria-label={a}><Ic n="globe" /></a> : 'Not supplied'}</dd></React.Fragment>)}</dl><p className="lg">Manage account access and available tools in <ActionLink onClick={() => go({
            v: 'settings',
            p: p.id
          })}>plugin settings</ActionLink>.</p></>}</div>;
  }
  function SkillRow({
    s
  }) {
    const {
        setDlg,
        skillAction,
        busy
      } = useX(),
      [open, setOpen] = useState(false),
      owned = s.read_only || s.is_external || s.origin === 'builtin' || s.source === 'external';
    return <div className="sr2" role="button" tabIndex={0} onClick={() => setDlg({
      t: 'skill',
      s
    })} onKeyDown={e => e.target === e.currentTarget && e.key === 'Enter' && setDlg({
      t: 'skill',
      s
    })}><span className="ct2"><Ic n="cubeo" s={22} /></span><div className="m el"><b>{name(s)}</b><span>{s.description || s.summary}</span></div><span className="sl">{s.owner_plugin || s.origin || s.source || 'Personal'}</span><button className="ib" aria-label={'Skill actions for ' + name(s)} aria-haspopup="menu" onClick={e => {
        e.stopPropagation();
        setOpen(!open);
      }}><Ic n="dots" /></button><Sw value={s.state !== 'archived'} label={'Enable ' + name(s)} disabled={busy || owned} onChange={v => skillAction(v ? 'restore' : 'archive', s)} />{open && <Pop close={() => setOpen(false)} style={{
        right: 60,
        top: 66,
        width: 170
      }} items={[{
        label: 'Open',
        action: () => setDlg({
          t: 'skill',
          s
        })
      }, {
        label: 'Details',
        action: () => setDlg({
          t: 'skill',
          s,
          details: true
        })
      }, {
        label: 'Remove',
        danger: true,
        disabled: owned,
        reason: 'Owned by an external installation.',
        action: () => skillAction('remove', s)
      }]} />}</div>;
  }
  function Skills() {
    const {
        skills,
        refresh,
        setDlg,
        go
      } = useX(),
      [tab, setTab] = useState('Personal'),
      [q, setQ] = useState(''),
      rows = skills.filter(s => name(s).toLowerCase().includes(q.toLowerCase())),
      personal = s => !s.owner_plugin && !['builtin', 'system'].includes(s.origin);
    return <div className="cc"><div className="hd"><div><h1>Skills</h1><p className="sub">Extend Vellum with task-specific skills</p></div><div className="tl"><Search q={q} setQ={setQ} ph="Search skills" /><button className="ib" aria-label="Refresh skills" onClick={refresh}><Ic n="refresh" /></button><button className="ib" aria-label="Manage skills" onClick={() => go({
            v: 'settings',
            tab: 'skills'
          })}><Ic n="gear" /></button><button className="addp" onClick={() => setDlg({
            t: 'skillAdd'
          })}>Add</button></div></div><h2 className="shd" style={{
        marginTop: 34
      }}>Installed</h2><div className="sgrid" style={{
        marginTop: 14
      }}>{rows.slice(0, 6).map(s => <div className="sk3" role="button" tabIndex={0} key={s.id || s.name} onClick={() => setDlg({
          t: 'skill',
          s
        })} onKeyDown={e => e.target === e.currentTarget && e.key === 'Enter' && setDlg({
          t: 'skill',
          s
        })}><Ic n="cubeo" s={32} /><div className="m"><b>{name(s)}</b><span>{s.description}</span></div><span className="ok2"><Ic n="check" /></span></div>)}</div>{rows.length > 6 && <ActionLink className="more" onClick={() => go({
        v: 'settings',
        tab: 'skills'
      })}>See {rows.length - 6} more</ActionLink>}<div className="seg" style={{
        marginTop: 40
      }}>{['Personal', 'System'].map(t => <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{t}</button>)}</div><div style={{
        marginTop: 14
      }}>{rows.filter(s => tab === 'Personal' ? personal(s) : !personal(s)).map(s => <SkillRow key={s.id || s.name} s={s} />)}</div></div>;
  }
  function Settings({
    tab = 'plugins',
    plugin
  }) {
    const {
        plugins: catalog,
        skills,
        skillsLoaded,
        go,
        setDlg,
        changePlugin,
        busy
      } = useX(),
      plugins = catalog.filter(p => p.installed !== false),
      [q, setQ] = useState('');
    if (plugin) {
      const p = plugins.find(p => p.id === plugin);
      return p ? <Detail p={p} settings /> : <div className="cc">Plugin no longer available.</div>;
    }
    const apps = plugins.flatMap(p => (p.apps || []).map(item => ({
        p,
        item
      }))),
      mcps = plugins.flatMap(p => (p.mcp_connectors || []).map(item => ({
        p,
        item
      }))),
      cnt = {
        plugins: plugins.length,
        apps: apps.length,
        mcps: mcps.length,
        skills: skillsLoaded ? skills.length : '…'
      },
      match = t => String(t).toLowerCase().includes(q.toLowerCase());
    return <div className="cc"><div className="hd"><div><h1>Plugins</h1><p className="sub">Manage plugins, skills, and MCPs</p></div><div className="tl"><button className="bo" onClick={() => go({
            v: 'directory'
          })}>Browse directory</button><Add settings /></div></div><div className="hd" style={{
        marginTop: 34,
        alignItems: 'center'
      }}><div className="pl">{[['plugins', 'Plugins'], ['apps', 'Apps'], ['mcps', 'MCPs'], ['skills', 'Skills']].map(([k, l]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => {
            setQ('');
            go({
              v: 'settings',
              tab: k
            });
          }}>{l}<i>{cnt[k]}</i></button>)}</div><Search q={q} setQ={setQ} ph={{
          plugins: 'Search plugins',
          apps: 'Search apps',
          mcps: 'Search MCP servers',
          skills: 'Search skills'
        }[tab]} /></div>{tab === 'plugins' && <div className="lc">{plugins.filter(p => match(p.name)).map(p => <div className="li" role="button" tabIndex={0} key={p.id} onClick={() => go({
          v: 'settings',
          p: p.id
        })} onKeyDown={e => e.target === e.currentTarget && e.key === 'Enter' && go({
          v: 'settings',
          p: p.id
        })}><Tile p={p} sz={44} i={26} /><div className="m"><b>{p.name}</b><span>{p.description}</span></div><Sw value={p.enabled !== false} label={'Enable ' + p.name} disabled={busy || p.required || p.manageable === false} onChange={v => changePlugin(p, v)} /><Ic n="chevR" s={16} /></div>)}</div>}{tab === 'apps' && <div className="lc">{apps.filter(({
          p,
          item
        }) => match(name(item) + ' ' + p.name)).map(({
          p,
          item
        }, i) => <div className="li" role="button" tabIndex={0} key={p.id + i} onClick={() => setDlg({
          t: 'app',
          p,
          app: item
        })} onKeyDown={e => e.target === e.currentTarget && e.key === 'Enter' && setDlg({
          t: 'app',
          p,
          app: item
        })}><Tile p={p} sz={44} i={26} /><div className="m el"><b>{name(item)}</b><span>{item.description || p.description}</span></div><Sw value={p.enabled !== false} label={'Enable ' + name(item)} disabled={busy || p.required || p.manageable === false} onChange={v => changePlugin(p, v)} /><Ic n="chevR" s={16} /></div>)}</div>}{tab === 'mcps' && <>{[['Servers', true], ['From plugins', false]].map(([label, custom]) => <React.Fragment key={label}><h2 className="h2s" style={{
            fontSize: 15,
            marginTop: 40
          }}>{label}</h2><div className="lc" style={{
            marginTop: 0
          }}>{mcps.filter(({
              p,
              item
            }) => p.id.startsWith('custom-') === custom && match(name(item) + ' ' + p.name)).map(({
              p,
              item
            }, i) => <div className="li" style={{
              minHeight: custom ? 64 : 52
            }} key={p.id + i}><ActionLink className="gr" style={{
                color: 'inherit'
              }} onClick={() => setDlg({
                t: 'app',
                p,
                app: item,
                mcp: true
              })}>{name(item)}</ActionLink><button className={custom ? 'ib' : 'bo'} aria-label={'Configure ' + name(item)} onClick={() => go({
                v: 'settings',
                p: p.id
              })}>{custom ? <Ic n="gear" /> : p.metadata?.connection?.connected ? 'Manage' : 'Authenticate'}</button>{custom && <Sw value={p.enabled !== false} label={'Enable ' + name(item)} disabled={busy || p.required} onChange={v => changePlugin(p, v)} />}</div>)}</div></React.Fragment>)}<h2 className="h2s" style={{
          fontSize: 15
        }}>MCP Apps</h2><div className="lc" style={{
          marginTop: 0
        }}><div className="li"><div className="m"><b>App data</b><span>Clear site data and cache from all MCP apps</span></div><button className="bo" disabled title="Vellum does not yet host MCP app widgets or their site-data store.">Clear all app data</button></div></div></>}{tab === 'skills' && <div style={{
        marginTop: 26
      }}>{skills.filter(s => match(name(s) + ' ' + s.description)).map(s => <SkillRow key={s.id || s.name} s={s} />)}</div>}</div>;
  }
  function ToolGroups({
    tools
  }) {
    const [expanded, setExpanded] = useState(null),
      groups = [['w', 'Write', tools.filter(t => !t.read_only)], ['r', 'Read', tools.filter(t => t.read_only)]];
    return <><p style={{
        margin: '18px 0 0',
        color: 'var(--dim,#BDBDBD)'
      }}>The app contains {tools.length} tools ({groups[0][2].length} write, {groups[1][2].length} read)</p><div className="gc" style={{
        marginTop: 18
      }}>{groups.map(([id, label, list]) => <React.Fragment key={id}><button className="gcr" style={{
            width: '100%',
            background: 'none',
            border: 0,
            cursor: 'pointer'
          }} aria-expanded={expanded === id} onClick={() => setExpanded(expanded === id ? null : id)}><span>{label} <span style={{
                color: 'var(--dim,#9A9A9A)'
              }}>{list.length}</span></span><Ic n={expanded === id ? 'chevD' : 'chevR'} s={16} /></button>{expanded === id && list.map(t => <div className="tr2" key={t.name || t.id}><span>{t.name || t.id}</span><span>{t.description}{t.input_schema && <details><summary>Schema</summary><pre className="tool-schema">{JSON.stringify(t.input_schema, null, 2)}</pre></details>}</span></div>)}</React.Fragment>)}</div></>;
  }
  function PublishedTools({
    p,
    c
  }) {
    const [googleTools, setGoogleTools] = useState(null),
      [error, setError] = useState(''),
      started = useRef(false);
    useEffect(() => {
      if (started.current || !c.status?.configured && !c.unsupported) return;
      started.current = true;
      if (c.browse) {
        c.browse();
        return;
      }
      const service = {
        'gmail': 'gmail',
        'google-drive': 'drive',
        'google-calendar': 'calendar',
        'google-contacts': 'contacts'
      }[p.id];
      if (service) {
        let cancelled = false;
        (async () => {
          const rows = [];
          let offset = 0;
          do {
            const page = await window.VellumApi.plugins.googleCatalog({
              service,
              offset,
              limit: 100
            });
            rows.push(...page.methods.map(m => ({
              name: m.method_id,
              description: m.description,
              read_only: m.read_only
            })));
            offset = page.next_offset;
          } while (offset != null);
          if (!cancelled) setGoogleTools(rows);
        })().catch(e => !cancelled && setError(e.message));
        return () => {
          cancelled = true;
        };
      }
    }, [c.status?.configured]);
    const tools = c.tools || googleTools;
    return <>{tools ? <ToolGroups tools={tools} /> : <p className="notice" role="status">{c.browse || ['gmail', 'google-drive', 'google-calendar', 'google-contacts'].includes(p.id) ? 'Loading published tools…' : (p.tools || []).length + ' registered tool entries. This provider does not expose an inspectable catalog here.'}</p>}{error && <p className="error" role="alert">{error}</p>}</>;
  }
  function AppDialog({
    p,
    app,
    mcp = false,
    close
  }) {
    const {
      changePlugin,
      busy
    } = useX();
    return <Dlg w={750} close={close} label={p.name + (mcp ? ' MCP server' : ' app')}><div className="dh" style={{
        alignItems: 'flex-start'
      }}><Tile p={p} sz={50} i={28} r={14} /><span style={{
          flex: 1
        }} /><Sw value={p.enabled !== false} label={'Enable ' + p.name} disabled={busy || p.required || p.manageable === false} onChange={v => changePlugin(p, v)} /><button className="ib" aria-label="Close" onClick={close}><Ic n="x" /></button></div><h2 style={{
        margin: '18px 0 0',
        fontSize: 24
      }}>{app ? name(app) : p.name} <span style={{
          fontWeight: 400,
          color: 'var(--dim,#B4B4B4)'
        }}>{mcp ? 'MCP server' : 'App'}</span></h2><p style={{
        margin: '10px 0 0',
        fontSize: 16,
        lineHeight: 1.9,
        color: 'var(--dim,#C8C8C8)'
      }}>{app?.description || p.description}</p><Connection p={p}>{c => <><PublishedTools p={p} c={c} /><Feedback p={p} c={c} /></>}</Connection><div className="df" style={{
        justifyContent: 'flex-end'
      }}><button className="bt" onClick={close}>Close</button></div></Dlg>;
  }
  function SkillDialog({
    s,
    details,
    close
  }) {
    const {
        skillAction,
        busy
      } = useX(),
      [detail, setDetail] = useState(null),
      [error, setError] = useState(''),
      [raw, setRaw] = useState(false),
      n = name(s),
      Markdown = window.VellumUI.AnswerMarkdown;
    useEffect(() => {
      const c = new AbortController();
      window.VellumApi.plugins.skillDetail(n, c.signal).then(setDetail).catch(e => {
        if (!c.signal.aborted) setError(e.message);
      });
      return () => c.abort();
    }, [n]);
    return <Dlg w={750} close={close} label={n + ' skill'}><div className="dh"><Ic n="cubeo" s={36} /><div><h2>{n}</h2><span className="tg" style={{
            marginTop: 6,
            display: 'inline-block'
          }}>SKILL.md</span></div><Sw label={'Enable ' + n} value={s.state !== 'archived'} disabled={busy || detail?.read_only || s.is_external || s.origin === 'builtin' || s.source === 'external'} onChange={v => skillAction(v ? 'restore' : 'archive', s)} /><button className="ib" aria-label="Close" onClick={close}><Ic n="x" /></button></div><div className="mdc"><span>Name</span><span>{n}</span><span>Description</span><span>{detail?.description || s.description}</span>{details && <><span>Source</span><span>{detail?.provenance?.repository_url || detail?.provenance?.source || s.source}</span><span>Owner</span><span>{detail?.owner_plugin || s.owner_plugin || 'Personal'}</span></>}</div>{error ? <p className="error" role="alert">{error}</p> : detail ? <><div className="df"><button className="bs" onClick={() => setRaw(!raw)}>{raw ? 'Preview' : 'Source'}</button><button className="bs" disabled={!detail.skill_md} onClick={() => navigator.clipboard.writeText(detail.skill_md).catch(() => setError('Clipboard is unavailable. Select and copy the source.'))}>Copy Markdown</button>{window.VellumDesktop && <button className="bs" onClick={() => window.VellumDesktop.invoke('skill_file', {
            name: n,
            operation: 'open'
          }).catch(() => setError('The file could not be opened.'))}>Open file</button>}</div><div className="md">{detail.skill_md ? raw || !Markdown ? <pre>{detail.skill_md}</pre> : <Markdown text={detail.skill_md} /> : <p>SKILL.md is unavailable from this source.</p>}</div></> : <p className="notice" role="status">Loading SKILL.md…</p>}</Dlg>;
  }
  function Uninstall({
    p,
    close
  }) {
    const {
        applyReviewed,
        busy
      } = useX(),
      [error, setError] = useState('');
    return <Dlg w={480} close={close} label={'Uninstall ' + p.name}><div className="wi"><Ic n="warn" s={22} /></div><h2 style={{
        margin: 0,
        fontSize: 18
      }}>Uninstall {p.name}?</h2><p style={{
        color: 'var(--dim,#BDBDBD)',
        lineHeight: 1.8,
        margin: '10px 0 0'
      }}>This removes {p.name} and its tools from your Vellum installation. Your {p.name} account, source files and data aren’t deleted.</p><label className="ck" title="Disconnect separately in the account menu before uninstalling."><input type="checkbox" disabled checked={false} readOnly /> Also disconnect my {p.name} account</label>{error && <p className="error" role="alert">{error}</p>}<div className="df" style={{
        justifyContent: 'flex-end'
      }}><button className="bs" disabled={busy} onClick={close}>Cancel</button><button className="bt dn" disabled={busy} onClick={async () => {
          try {
            await applyReviewed('plugin.uninstall', {
              plugin_id: p.id
            });
            close();
          } catch (e) {
            setError(e.message);
          }
        }}>Uninstall</button></div></Dlg>;
  }
  function Manage({
    p,
    close,
    install = false
  }) {
    const {
        changePlugin,
        submit,
        setDlg,
        skillAction,
        busy
      } = useX(),
      [step, setStep] = useState(install ? 0 : 1);
    const canRemove = !p.protected && !p.required && p.manageable !== false;
    return <Dlg w={install ? 560 : 720} close={close} label={(install ? 'Install ' : 'Manage ') + p.name}>
      <DH p={p} t={(install ? 'Install ' : '') + p.name} close={close} sub={<span className={install ? 'sub' : 'ok'} style={{
        margin: 0,
        fontSize: 12
      }}>{install ? 'Step ' + (step + 1) + ' of 3' : (p.installed !== false ? 'Installed' : 'Not installed') + ' · v' + (p.version || '—')}</span>} />
      {install && <ol className="stp">{['Review permissions', 'Connect ' + p.name + ' account', 'Install plugin'].map((t, i) => <li key={t}><span className={'d' + (i === step ? ' c' : '')} style={i > step ? {
            background: '#444'
          } : undefined}>{i < step ? <Ic n="check" s={13} /> : i + 1}</span>{t}</li>)}</ol>}
      {install && step === 0 ? <><div className="ds"><h3>This plugin can</h3>{(p.capabilities || []).length ? p.capabilities.map(t => <div className="ln" key={t}><div className="gr">{t}</div></div>) : <p>Use the tools and permissions published by {p.name}. Review account access on its consent screen.</p>}</div><div className="df" style={{
          justifyContent: 'flex-end'
        }}><button className="bs" onClick={close}>Cancel</button><button className="bt" disabled={busy} onClick={async () => {
            if (p.installed === false) await submit('plugin.install', {
              plugin_id: p.id
            });else if (p.enabled === false && !(await changePlugin(p, true))) return;
            setStep(1);
          }}>Continue</button></div></> : <Connection p={p}>{c => {
          const connected = !!c.status?.connected,
            provider = p.id.startsWith('app-') ? 'producthunt' : p.id,
            connect = () => c.status?.configured && !connected && c.run ? c.run(provider + '.connection.verify') : c.choose ? c.choose() : c.connect?.();
          if(c.anonymous||c.bot)return <><Accounts p={p} c={c}/>{c.anonymous&&<PublishedTools p={p} c={c}/>}<div className="df"><button className="bs" onClick={close}>Close</button>{!install&&<button className="bs rd" disabled={!canRemove} onClick={()=>setDlg({t:'uninstall',p})}>Uninstall</button>}{install&&<button className="bt" disabled={!connected} onClick={close}>Done</button>}</div></>;
          return <><Setup c={c} p={p} />{install ? <p style={{
              color: 'var(--dim,#BDBDBD)',
              lineHeight: 1.8
            }}>Sign in so Vellum can act on your {p.name} workspace. You can disconnect anytime in settings.</p> : <>
          <div className="ds"><h3>Connection</h3><div className="ln"><div className="gr"><b>{connected ? 'Workspace connected' : 'Not connected'}</b><span>{connected ? c.status.email || c.status.account_name || 'Vellum can use the authorized workspace.' : 'Connect your account to use its tools.'}</span></div><button className="bs" disabled={c.busy || p.enabled === false || !c.connect && !c.choose || !!c.pending} onClick={connect}>{c.status?.configured && !connected && c.run ? 'Verify connection' : 'Reconnect'}</button><button className="bs" disabled={!connected || c.busy || !!c.pending} onClick={() => c.disconnect ? c.disconnect() : c.run?.(provider + '.connection.disconnect')}>Disconnect</button></div></div>
          <div className="ds"><h3>Permissions</h3><div className="ln"><div className="gr">Read your {p.name} content</div><span className="tg">Read</span><Sw value={connected} label="Read" disabled onChange={() => {}} /></div><div className="ln"><div className="gr">Create and update items</div><span className="tg">Write</span><Sw value={connected && c.status?.auth_type === 'oauth'} label="Write" disabled onChange={() => {}} /></div><div className="ln"><div className="gr">Delete items</div><span className="pill mute">Provider permissions</span></div></div>
          {(p.skills || []).length > 0 && <div className="ds"><h3>Included</h3>{p.skills.map(s => <div className="ln" key={s.id || s.name}><Ic n="cubeo" /><div className="gr"><b>{name(s)}</b><span>Skill</span></div><Sw value={s.enabled !== false} label={name(s)} disabled={s.read_only || s.owner_plugin || busy} onChange={v => skillAction(v ? 'restore' : 'archive', s)} /></div>)}</div>}
        </>}
        {install && step === 2 && <><div className="pg" role="progressbar" aria-label="Install progress" aria-valuenow={100} aria-valuemin={0} aria-valuemax={100}><i style={{
                  width: '100%'
                }} /></div><ul className="stp" style={{
                marginTop: 14,
                color: '#A8A8A8'
              }}>{['Enabled ' + p.name, 'Verified account connection', String(c.status?.mcp_tool_count ?? p.tools?.length ?? 0) + ' available tools'].map(t => <li key={t}><Ic n="check" s={16} />{t}</li>)}</ul></>}
        <Feedback c={c} p={p} />{c.open && <GoogleChooser c={c} p={p} />}
        <div className="df" style={install ? {
              justifyContent: 'flex-end'
            } : undefined}>{install ? <button className="bs" onClick={() => setStep(Math.max(0, step - 1))}>Back</button> : <button className="bs rd" disabled={!canRemove} onClick={() => setDlg({
                t: 'uninstall',
                p
              })}><Ic n="trash" s={14} /> Uninstall</button>}{install && step === 1 && !connected ? <button className="bt" disabled={c.busy || p.enabled === false || !c.connect && !c.choose || !!c.pending} onClick={connect}>Connect {p.name}</button> : <button className="bt" disabled={install && step === 2 && !connected} onClick={() => install && step === 1 ? setStep(2) : close()}>{install && step === 1 ? 'Install plugin' : 'Done'}</button>}</div></>;
        }}</Connection>}
    </Dlg>;
  }
  const Field = ({
    label,
    value,
    setValue,
    placeholder,
    multiline = false
  }) => {
    const id = React.useId();
    return <div className="fd"><label htmlFor={id}>{label}</label>{multiline ? <textarea id={id} className="fi" style={{
        height: 110
      }} value={value} onChange={e => setValue(e.target.value)} placeholder={placeholder} /> : <input id={id} className="fi" value={value} onChange={e => setValue(e.target.value)} placeholder={placeholder} />}</div>;
  };
  function AddDialog({
    kind: requestedKind,
    close
  }) {
    const kind = requestedKind === 'create' ? 'archive' : requestedKind;
    const {
        submit,
        setDlg
      } = useX(),
      [n, sn] = useState(''),
      [d, sd] = useState(''),
      [source, ss] = useState(''),
      [ref, sr] = useState(''),
      [paths, sp] = useState(''),
      [url, su] = useState(''),
      [tab, st] = useState('Server URL'),
      [auth, sa] = useState('None'),
      [ack, sc] = useState(false),
      [file, sf] = useState(null),
      [busy, sb] = useState(false),
      [error, se] = useState(''),
      label = {
        marketplace: 'Add plugin marketplace',
        create: 'New Plugin',
        archive: 'New Plugin',
        mcp: 'Add custom MCP server',
        skillAdd: 'Add skill'
      }[kind];
    const save = async () => {
      sb(true);
      se('');
      try {
        let action = 'plugin.add',
          body = {
            kind: kind === 'archive' ? 'archive' : kind === 'mcp' ? 'mcp' : 'create',
            name: n.trim() || file?.name.replace(/\.zip$/i, '') || 'New plugin',
            description: d
          };
        if (kind === 'marketplace') {
          if (ref.trim()) throw Error('This source supports its default Git ref only.');
          if (paths.includes('\n')) throw Error('Use one relative skills directory.');
          action = 'plugin.marketplace.add';
          body = {
            repo: source.trim().replace(/^https:\/\/github.com\//, '').replace(/^git@github.com:/, '').replace(/\.git$/, '').replace(/\/$/, ''),
            path: paths.trim() || 'skills/'
          };
        }
        if (kind === 'mcp') {
          if (auth !== 'None') throw Error('Arbitrary-server OAuth setup is not available yet. Use a supported provider or an unauthenticated endpoint.');
          if (tab !== 'Server URL') throw Error('Configure a tunnel outside Vellum, then add its public server URL.');
          body = {
            ...body,
            transport: 'http',
            url: url.trim()
          };
        }
        if (kind === 'archive') {
          if (!file || !file.name.toLowerCase().endsWith('.zip')) throw Error('Vellum currently accepts declarative ZIP plugin archives.');
          if (file.size > 2 * 1024 * 1024) throw Error('The backend archive limit is 2 MiB.');
          const bytes = new Uint8Array(await file.arrayBuffer());
          let raw = '';
          for (let i = 0; i < bytes.length; i += 8192) raw += String.fromCharCode(...bytes.subarray(i, i + 8192));
          body.archive_b64 = btoa(raw);
        }
        if (kind === 'skillAdd') {
          action = 'skill.mutation.submit';
          body = {
            operation: 'install',
            identifier: source.trim(),
            category: 'community'
          };
        }
        await submit(action, body);
        close();
      } catch (e) {
        se(e.message);
      } finally {
        sb(false);
      }
    };
    const valid = kind === 'marketplace' || kind === 'skillAdd' ? source.trim() : kind === 'archive' ? file : kind === 'mcp' ? n.trim() && url.trim() && ack : n.trim();
    return <Dlg w={kind === 'archive' || kind === 'create' ? 640 : 700} close={close} label={label}><DH t={label} close={close} sub={kind === 'marketplace' ? <p className="sub" style={{
        marginTop: 8
      }}>Add from a public GitHub repository.</p> : null} />{kind === 'marketplace' ? <><Field label="Source" value={source} setValue={ss} placeholder="vellum/plugins or git@github.com:org/repo.git" /><Field label="Git ref" value={ref} setValue={sr} placeholder="main" /><Field label="Sparse paths" value={paths} setValue={sp} placeholder="plugins/vellum" multiline /></> : kind === 'skillAdd' ? <Field label="Skill source" value={source} setValue={ss} placeholder="Marketplace skill identifier" /> : kind === 'archive' ? <label className="dz" onDragOver={e => e.preventDefault()} onDrop={e => {
        e.preventDefault();
        sf(e.dataTransfer.files[0] || null);
      }}><input type="file" className="vh" accept=".zip,application/zip" onChange={e => sf(e.target.files[0] || null)} /><Ic n="upload" s={22} /><span style={{
          marginTop: 6
        }}>{file ? file.name : <>Drag and drop your plugin here, or <span className="lk">click to upload</span></>}</span><small>Only .zip archives are supported</small><small>Maximum size: 2 MiB</small></label> : <><Field label="Name" value={n} setValue={sn} placeholder={kind === 'mcp' ? 'Custom Tool' : 'My plugin'} /><Field label="Description (optional)" value={d} setValue={sd} placeholder="Explain what it does in a few words" /></>}{kind === 'mcp' && <><div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          marginTop: 14
        }}><button className="ch" disabled title="Custom icon storage is not supported by this backend yet.">Choose icon</button><span style={{
            color: 'var(--dim,#B4B4B4)',
            fontSize: 12.5
          }}>Optional PNG, up to 10 KB</span></div><div className="fd"><span className="fl">Connection</span><div className="cn" role="group" aria-label="Connection type">{['Server URL', 'Tunnel'].map(t => <button key={t} className={tab === t ? 'on' : ''} aria-pressed={tab === t} onClick={() => st(t)}>{t}</button>)}</div><input className="fi" aria-label={tab} placeholder="https://example.com/mcp" value={url} onChange={e => su(e.target.value)} /></div><label className="fd">Authentication<select className="fi" value={auth} onChange={e => sa(e.target.value)}><option>OAuth</option><option>API key</option><option>None</option></select></label><button className="adv" disabled><span className="gr" style={{
            gap: 4
          }}><b>Advanced OAuth settings</b><span>Review discovered OAuth settings, or enter them manually, then choose a client setup method and configure default scopes</span></span><Ic n="chevR" s={16} /></button><div className="wn"><Ic n="warn" /><span>Custom MCP servers introduce risk.</span></div><label className="cs"><input type="checkbox" style={{
            width: 18,
            height: 18,
            marginTop: 2
          }} checked={ack} onChange={e => sc(e.target.checked)} /><span className="gr"><b>I understand and want to continue</b><span>Only connect to MCP servers you trust. An untrusted server may access or steal information shared through app use, or trick Vellum into using tools in unintended ways, including changing or deleting data.</span></span></label></>}{error && <p className="error" role="alert">{error}</p>}<div className="df" style={{
        alignItems: 'center'
      }}>{kind === 'archive' ? <button className="bs sec2" onClick={() => setDlg({
          t: 'mcp'
        })}>Add custom MCP server</button> : kind === 'mcp' ? <button className="bs sec2" onClick={() => setDlg({
          t: 'archive'
        })}>Upload plugin archive</button> : <span />}<span style={{
          display: 'flex',
          gap: 10
        }}><button className="bs" disabled={busy} onClick={close}>Cancel</button><button className="bt" disabled={busy || !valid} onClick={save}>{busy ? 'Checking…' : kind === 'marketplace' ? 'Add marketplace' : kind === 'mcp' ? 'Create as a plugin' : kind === 'skillAdd' ? 'Review skill' : 'Add plugin'}</button></span></div></Dlg>;
  }
  function Review({
    pending,
    close
  }) {
    const {
      decide,
      plugins,
      busy
    } = useX();
    return <Dlg close={close} label="Review change"><DH t="Review change" close={close} /><p className="notice">{pending.receipt.message}</p><div className="mdc"><span>Action</span><span>{pending.request.action_id}</span><span>Target</span><span>{plugins.find(p=>p.id===pending.request.arguments.plugin_id)?.name || pending.request.arguments.name || pending.request.arguments.repo || pending.request.arguments.operation}</span></div><div className="df"><button className="bs" disabled={busy} onClick={() => decide(false)}>Cancel</button><button className="bt" disabled={busy} onClick={() => decide(true)}>Confirm</button></div></Dlg>;
  }
  function Workspace({
    sidebarVisible=true,
    onSidebarVisibility,
    SidebarIcon,
    initialRoute,
    apps = [],
    mode = 'manage',
    catalogState,
    onRetry,
    onPluginState,
    onAdd,
    onConfirmAdd,
    onCancelAdd,
    onSkillAction,
    onManage,
    onBrowse,
    onNavigateSettings,
    onExit,
    Logo,
    renderDiscord,
    onTry
  }) {
    const [r, setR] = useState(initialRoute || {
        v: mode === 'directory' ? 'directory' : 'settings',
        tab: 'plugins'
      }),
      [dlg, setDlg] = useState(null),
      [error, setError] = useState(''),
      [busy, setBusy] = useState(false),
      [skills, setSkills] = useState([]),
      [skillsLoaded, setSkillsLoaded] = useState(false),
      skillsRequested = useRef(false),
      [pending, setPending] = useState(null),
      mounted = useRef(true),
      pendingRef = useRef(null),
      scroll = useRef(null),
      plugins = apps.map(p => ({
        ...p,
        apps: p.apps || [],
        skills: p.skills || [],
        mcp_connectors: p.mcp_connectors || []
      }));
    useEffect(() => {
      mounted.current = true;
      return () => {
        mounted.current = false;
        const p = pendingRef.current;
        if (p && !p.mutation) onCancelAdd?.(p.receipt).catch(() => {});
      };
    }, []);
    const loadSkills = async () => {
      try {
        let rows = [],
          cursor = '',
          seen = new Set();
        do {
          const result = await window.VellumApi.plugins.skillsCatalog({
            view: 'installed',
            limit: 100,
            ...(cursor ? {
              cursor
            } : {})
          });
          rows.push(...(result.items || []));
          const next = result.next_cursor || '';
          if (next && seen.has(next)) throw Error('The skill catalog returned a repeated page cursor.');
          seen.add(next);
          cursor = next;
        } while (cursor);
        if (mounted.current) {
          setSkills(rows);
          setSkillsLoaded(true);
        }
      } catch (e) {
        if (mounted.current) setError(e.message || 'Skills are unavailable.');
      }
    };
    useEffect(() => {
      if ((mode !== 'directory' || r.v === 'skills') && !skillsRequested.current) {
        skillsRequested.current = true;
        loadSkills();
      }
    }, [mode, r.v]);
    const refresh = async () => {
      await onRetry?.();
      if (skillsRequested.current) await loadSkills();
    };
    useEffect(() => {
      const q = new URLSearchParams(location.search),
        p = plugins.find(p => q.has((p.id === 'google-workspace' ? 'google' : p.id) + '_oauth'));
      if (p) setR({
        v: 'settings',
        p: p.id
      });
    }, [apps]);
    const go = next => {
      setError('');
      setDlg(null);
      if (next.v === 'settings' && mode === 'directory' && onManage) onManage(next);else if (next.v === 'directory' && mode !== 'directory' && onBrowse) onBrowse();else setR(next);
      scroll.current?.scrollTo?.(0, 0);
    };
    const toggleSidebar=async()=>{
      if(busy||!onSidebarVisibility)return;
      setBusy(true);setError('');
      try{const receipt=await onSidebarVisibility(!sidebarVisible);if(receipt?.status!=='applied')throw Error(receipt?.message||'Plugin sidebar visibility was not saved.');}
      catch(error){setError(error.message);}finally{setBusy(false);}
    };
    const changePlugin = async (p, value) => {
      if (busy) return false;
      setBusy(true);
      setError('');
      try {
        const receipt = await onPluginState(p.id, value);
        if (receipt?.status !== 'applied') throw Error(receipt?.message || 'Plugin state was not saved.');
        await onRetry?.();
        return true;
      } catch (e) {
        setError(e.message);
        return false;
      } finally {
        setBusy(false);
      }
    };
    const submit = async (action_id, args) => {
      const request = {
          action_id,
          arguments: args
        },
        receipt = await onAdd(action_id, args);
      if (receipt?.status === 'confirmation_required') {
        const p = {
          request,
          receipt
        };
        pendingRef.current = p;
        setPending(p);
        return receipt;
      }
      if (receipt?.status !== 'applied') throw Error(receipt?.message || 'The change was not applied.');
      const mutation = receipt.result?.mutation;
      if (mutation?.status === 'pending') {
        const p = {
          mutation,
          request,
          receipt
        };
        pendingRef.current = p;
        setPending(p);
      }
      await refresh();
      return receipt;
    };
    const applyReviewed=async(action_id,args)=>{
      setBusy(true);
      try{
        let receipt=await onAdd(action_id,args);
        if(receipt?.status==='confirmation_required')receipt=await onConfirmAdd(receipt);
        if(receipt?.status!=='applied')throw Error(receipt?.message||'The installation change was not applied.');
        await refresh();
        return receipt;
      }finally{setBusy(false);}
    };
    const decide = async confirmed => {
      const p = pending;
      if (!p || busy) return;
      setBusy(true);
      setError('');
      try {
        const receipt = p.mutation ? await onSkillAction(confirmed ? 'skill.mutation.approve' : 'skill.mutation.reject', {
          mutation_id: p.mutation.id
        }) : await (confirmed ? onConfirmAdd(p.receipt) : onCancelAdd(p.receipt));
        if (confirmed && receipt?.status !== 'applied') throw Error(receipt?.message || 'The change was not applied.');
        pendingRef.current = null;
        setPending(null);
        await refresh();
      } catch (e) {
        setError(e.message);
      } finally {
        setBusy(false);
      }
    };
    const skillAction = async (operation, s) => {
      setBusy(true);
      setError('');
      try {
        await submit('skill.mutation.submit', {
          operation,
          name: name(s)
        });
      } catch (e) {
        setError(e.message);
      } finally {
        setBusy(false);
      }
    };
    const tryNow = (p, text) => onTry ? onTry(p, text) : setError('Return to chat and ask Vellum to use ' + p.name + '.');
    const settings = r.v === 'settings',
      p = plugins.find(p => p.id === r.p),
      close = () => setDlg(null);
    return <X.Provider value={{
      plugins,
      skills,
      skillsLoaded,
      go,
      setDlg,
      refresh,
      changePlugin,
      skillAction,
      submit,
      applyReviewed,
      decide,
      setError,
      busy,
      Logo,
      renderDiscord,
      tryNow,
      loading: catalogState?.loading
    }}><div className="vplug" data-ui-reference="plugins"><div className="bd"><div className="ct">{mode === 'directory' && sidebarVisible && <aside id="vellum-plugin-sidebar" data-ui-reference="plugin-sidebar" className="pn" aria-label="Customize"><div className="pnh"><h2>Customize</h2>{onSidebarVisibility&&<button className="ib" aria-label="Hide plugin sidebar" aria-controls="vellum-plugin-sidebar" aria-expanded="true" disabled={busy} onClick={toggleSidebar}>{SidebarIcon?<SidebarIcon size={18}/>:<Ic n="window"/>}</button>}</div><ActionLink className={'ni2' + (r.v !== 'skills' ? ' on' : '')} onClick={() => go({
                v: 'directory'
              })}><Ic n="plug" />Plugins</ActionLink><ActionLink className={'ni2' + (r.v === 'skills' ? ' on' : '')} onClick={() => go({
                v: 'skills'
              })}><Ic n="grid" />Skills</ActionLink><div className="lbl">Installed</div>{plugins.filter(p => p.installed !== false).map(p => <ActionLink key={p.id} className="pi" onClick={() => go({
                v: 'detail',
                p: p.id
              })}><Tile p={p} sz={22} i={14} r={6} />{p.name}</ActionLink>)}</aside>}<main className="mn" ref={scroll}>{mode==='directory'&&!sidebarVisible&&<button className="ib plugin-sidebar-reveal" aria-label="Show plugin sidebar" aria-controls="vellum-plugin-sidebar" aria-expanded="false" disabled={busy} onClick={toggleSidebar}>{SidebarIcon?<SidebarIcon size={18}/>:<Ic n="window"/>}</button>}{(error || catalogState?.error) && <div className="cc" style={{
                paddingBottom: 0
              }}><p className="error" role="alert">{error || catalogState.error}</p><button className="bs" onClick={refresh}>Retry</button></div>}{r.v === 'directory' && <Directory />}{r.v === 'category' && <Directory category={r.category} />} {r.v === 'detail' && p && <Detail key={p.id} p={p} />} {r.v === 'skills' && <Skills />}{settings && <Settings key={r.tab || r.p || 'plugins'} tab={r.tab} plugin={r.p} />}</main></div></div>{dlg?.t === 'uninstall' && <Uninstall p={dlg.p} close={close} />} {dlg?.t === 'manage' && <Manage p={plugins.find(p => p.id === dlg.p.id) || dlg.p} close={close} />} {dlg?.t === 'install' && <Manage p={plugins.find(p => p.id === dlg.p.id) || dlg.p} close={close} install />}{dlg?.t === 'app' && <AppDialog p={plugins.find(p => p.id === dlg.p.id) || dlg.p} app={dlg.app} mcp={dlg.mcp} close={close} />} {dlg?.t === 'skill' && <SkillDialog s={dlg.s} details={dlg.details} close={close} />} {['create', 'archive', 'marketplace', 'mcp', 'skillAdd'].includes(dlg?.t) && <AddDialog kind={dlg.t} close={close} />} {pending && <Review pending={pending} close={() => decide(false)} />}</div></X.Provider>;
  }
  window.VellumUI = window.VellumUI || {};
  window.VellumUI.PluginWorkspace = Workspace;
})();
