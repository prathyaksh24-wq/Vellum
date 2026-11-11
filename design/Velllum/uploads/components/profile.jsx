/* Profile presentation adapted from the supplied Vellum handoff. */
(function () {
  const {useEffect, useLayoutEffect, useMemo, useRef, useState} = React;
  const Icon = props => <window.VellumUI.AppIcon {...props}/>;
  const dateKey = value => [value.getFullYear(),String(value.getMonth()+1).padStart(2,'0'),String(value.getDate()).padStart(2,'0')].join('-');
  const calendarDate = value => {
    const [year,month,day]=value.split('-').map(Number);
    return new Date(year,month-1,day,12);
  };
  const formatDate = value => calendarDate(value).toLocaleDateString(undefined,{weekday:'long',year:'numeric',month:'long',day:'numeric'});

  function calendar(days, today) {
    const end=calendarDate(today),start=new Date(end);
    start.setDate(start.getDate()-start.getDay()-52*7);
    const counts=new Map(days.map(day=>[day.date,day.count]));
    const cells=[],months=[];
    let previousMonth=-1;
    for(let week=0;week<53;week++) {
      for(let day=0;day<7;day++) {
        const current=new Date(start);
        current.setDate(start.getDate()+week*7+day);
        if(current>end)break;
        const key=dateKey(current);
        cells.push({w:week,d:day,c:counts.get(key)||0,date:current,key});
        if(day===0 && current.getMonth()!==previousMonth) {
          if(!months.length || week-months[months.length-1][0]>=3)months.push([week,current.toLocaleDateString(undefined,{month:'short'})]);
          previousMonth=current.getMonth();
        }
      }
    }
    let active=0,longest=0,streak=0,busiest=null;
    for(const cell of cells) {
      if(cell.c){active++;streak++;longest=Math.max(longest,streak);}
      else streak=0;
      if(cell.c && (!busiest || cell.c>busiest.c))busiest=cell;
    }
    let current=0,index=cells.length-1;
    if(cells[index]?.c===0)index--;
    while(index>=0 && cells[index].c>0){current++;index--;}
    return {cells,months,active,longest,current,busiest,total:cells.reduce((sum,cell)=>sum+cell.c,0)};
  }

  function Avatar({profile,className=''}) {
    const account=React.useContext(window.VellumUI.Accounts.Context);
    const name=profile?.displayName || 'Local user';
    return <span className={'profile-avatar '+className}>
      {account?.photo ? <img src={account.photo} alt=""/> : name.trim().split(/\s+/).slice(0,2).map(word=>word[0]).join('').toUpperCase()}
    </span>;
  }

  function Menu({anchor,label,onClose,children}) {
    const ref=useRef(null),[position,setPosition]=useState(null);
    useLayoutEffect(()=>{
      const rect=anchor.getBoundingClientRect();
      setPosition({left:Math.max(8,Math.min(rect.left,innerWidth-230)),top:Math.min(rect.bottom+6,innerHeight-240)});
      ref.current?.querySelector('button')?.focus();
    },[anchor]);
    useEffect(()=>{
      const outside=event=>{if(!ref.current?.contains(event.target) && !anchor.contains(event.target))onClose();};
      const keys=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();onClose();anchor.focus();}};
      document.addEventListener('pointerdown',outside);
      document.addEventListener('keydown',keys);
      return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',keys);};
    },[anchor,onClose]);
    return ReactDOM.createPortal(<div ref={ref} className="profile-menu" role="group" aria-label={label} data-shell-overlay="true" style={position||{visibility:'hidden'}}>
      {children}
    </div>,document.body);
  }

  function Skyline({cells,months,palette,view,legend,selected,onSelect}) {
    const host=useRef(null),canvas=useRef(null),tooltip=useRef(null),engine=useRef(null);
    const onSelectRef=useRef(onSelect),[active,setActive]=useState(-1);
    onSelectRef.current=onSelect;
    useEffect(()=>{
      engine.current=window.VellumUI.ProfileSky.mountSky(canvas.current,{
        tip:(index,x,y)=>{
          if(!tooltip.current)return;
          tooltip.current.style.opacity=index<0?'0':'1';
          tooltip.current.style.transform='translate('+Math.max(82,Math.min(host.current.clientWidth-82,x))+'px,'+Math.max(30,y-10)+'px) translate(-50%,-100%)';
        },
        onActive:setActive,
        onPick:index=>onSelectRef.current(index<0?null:index),
      });
      let lastWidth=host.current.clientWidth;
      const resize=typeof ResizeObserver==='function'?new ResizeObserver(entries=>{
        const width=entries[0]?.contentRect.width;
        if(width!==lastWidth){lastWidth=width;engine.current?.resize();}
      }):null;
      resize?.observe(host.current);
      return()=>{resize?.disconnect();engine.current.destroy();engine.current=null;};
    },[]);
    useEffect(()=>{engine.current.setData(cells,53,months);},[cells,months]);
    useEffect(()=>{engine.current.setPal(palette);},[palette]);
    useEffect(()=>{engine.current.setView(view);},[view]);
    useEffect(()=>{engine.current.setLegend(legend);},[legend]);
    useEffect(()=>{engine.current.setPin(selected??-1);},[selected]);
    const cell=cells[active];
    return <div className="profile-sky" ref={host}>
      <canvas ref={canvas} tabIndex={0} role="img" aria-label={'Activity heat map for the last year in '+(view==='3d'?'Skyline':'Flat')+' view. Use arrow keys to select days, Home or End to jump, and Escape to clear.'}/>
      <div className="profile-sky-tooltip" ref={tooltip} aria-hidden="true">{cell && <><strong>{cell.c} {cell.c===1?'response':'responses'}</strong><span>{cell.date.toLocaleDateString(undefined,{month:'short',day:'numeric'})}</span></>}</div>
      <span className="sr-only" aria-live="polite">{cell?cell.c+' responses on '+formatDate(cell.key):''}</span>
    </div>;
  }

  const paletteNames={github:'Green',ocean:'Ocean',ember:'Ember',grape:'Grape',sunset:'Sunset',mono:'Mono'};
  function Palette({value,onChange}) {
    const [anchor,setAnchor]=useState(null);
    const {PALS,EMPTY}=window.VellumUI.ProfileSky;
    const strip=key=><span className="profile-palette-strip" aria-hidden="true">{[EMPTY,...PALS[key]].map((color,index)=><i key={index} style={{background:color}}/>)}</span>;
    return <div className="profile-palette">
      <button type="button" className="btn" aria-label={'Activity palette: '+paletteNames[value]} aria-haspopup="listbox" aria-expanded={!!anchor} onClick={event=>setAnchor(anchor?null:event.currentTarget)}>
        {strip(value)}{paletteNames[value]}<Icon name="ChevronDown" size={13}/>
      </button>
      {anchor && <Menu anchor={anchor} label="Activity colors" onClose={()=>setAnchor(null)}>
        <window.VellumUI.SharedRowBackground role="listbox" label="Activity palette" refreshKey={value}>
          {Object.entries(paletteNames).map(([key,label])=><button key={key} type="button" role="option" aria-selected={key===value} data-shared-row="" onClick={()=>{onChange(key);setAnchor(null);anchor.focus();}}>
            {strip(key)}<span>{label}</span>{key===value && <Icon name="Check" size={14}/>}
          </button>)}
        </window.VellumUI.SharedRowBackground>
      </Menu>}
    </div>;
  }

  function Profile({profile,onSave}) {
    const account=React.useContext(window.VellumUI.Accounts.Context);
    const [editing,setEditing]=useState(false),[draft,setDraft]=useState(profile),[saving,setSaving]=useState(false),[error,setError]=useState('');
    const [photoMenu,setPhotoMenu]=useState(null),upload=useRef(null);
    const [activity,setActivity]=useState(null),[activityError,setActivityError]=useState(''),[reload,setReload]=useState(0);
    const [palette,setPalette]=useState('github'),[view,setView]=useState('3d'),[legend,setLegend]=useState(-1),[selected,setSelected]=useState(null);
    const [details,setDetails]=useState(null),[detailsError,setDetailsError]=useState('');
    const github=account.state.accounts.find(identity=>identity.provider==='github' && /^[a-zA-Z0-9-]+$/.test(identity.username));
    const zone=Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    useEffect(()=>{
      let live=true;
      window.VellumApi.accounts.profileActivity(zone).then(data=>{if(live){setActivity(data);setActivityError('');}}).catch(()=>{if(live)setActivityError('Activity could not load. Try again.');});
      return()=>{live=false;};
    },[zone,reload]);
    const data=useMemo(()=>calendar(activity?.days||[],activity?.today||dateKey(new Date())),[activity]);
    const chosen=selected===null?null:data.cells[selected];
    useEffect(()=>{
      if(!chosen){setDetails(null);return;}
      let live=true;
      setDetails(null);setDetailsError('');
      window.VellumApi.accounts.profileActivity(zone,chosen.key).then(next=>{if(live)setDetails(next.selected_items);}).catch(()=>{if(live)setDetailsError('This day could not load. Select it again to retry.');});
      return()=>{live=false;};
    },[chosen?.key,zone,reload]);
    async function save(event) {
      event.preventDefault();
      if(saving)return;
      setSaving(true);setError('');
      try{await onSave({displayName:draft.displayName,website:draft.website||''});setEditing(false);}
      catch(failure){setError(failure.message||'Your profile could not be saved. Try again.');}
      finally{setSaving(false);}
    }
    async function photo(event) {
      const file=event.target.files?.[0];
      event.target.value='';
      if(!file)return;
      if(!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size>5*1024*1024){setError('Choose a PNG, JPG, or WebP image smaller than 5 MB.');return;}
      const url=URL.createObjectURL(file),image=new Image();
      try{
        await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=reject;image.src=url;});
        account.setPhoto(url);setError('');
      }catch(_){URL.revokeObjectURL(url);setError('This image could not open. Choose another photo.');}
    }
    const move=delta=>{
      let index=selected+delta;
      while(index>=0 && index<data.cells.length && !data.cells[index].c)index+=delta;
      if(index>=0 && index<data.cells.length)setSelected(index);
    };
    return <section className="vellum-profile" aria-label="Profile">
      <h1>Profile</h1><p className="profile-subtitle">Your details and activity in Vellum.</p>
      <div className="profile-identity">
        <button type="button" className="profile-photo" aria-label="Change profile photo" aria-expanded={!!photoMenu} onClick={event=>setPhotoMenu(photoMenu?null:event.currentTarget)}>
          <Avatar profile={profile}/><span className="profile-camera"><Icon name="Camera" size={20}/><span>Change</span></span>
        </button>
        <input ref={upload} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={photo}/>
        {photoMenu && <Menu anchor={photoMenu} label="Profile photo" onClose={()=>setPhotoMenu(null)}>
          <button type="button" onClick={()=>{upload.current.click();setPhotoMenu(null);}}><Icon name="ArrowUp" size={16}/>Upload a photo</button>
          {account.photo && <button type="button" onClick={()=>{account.setPhoto(null);setPhotoMenu(null);}}><Icon name="Trash" size={16}/>Remove photo</button>}
        </Menu>}
        <div className="profile-identity-name"><h2>{profile.displayName}</h2>{profile.username && <span>@{profile.username.replace(/^@/,'')}</span>}</div>
        {!editing && <button type="button" className="btn" onClick={()=>{setDraft(profile);setEditing(true);setError('');}}>Edit profile</button>}
      </div>
      {editing ? <form className="profile-edit" onSubmit={save}>
        <label>Name<span className="profile-input"><Icon name="User" size={16}/><input aria-label="Profile name" required autoFocus maxLength={120} value={draft.displayName} onChange={event=>setDraft({...draft,displayName:event.target.value})}/></span></label>
        <label>Website<span className="profile-input"><Icon name="Link" size={16}/><input aria-label="Profile website" type="url" maxLength={2048} placeholder="https://" value={draft.website||''} onChange={event=>setDraft({...draft,website:event.target.value})}/></span></label>
        <div className="profile-edit-actions"><button type="button" className="btn" disabled={saving} onClick={()=>{setEditing(false);setError('');}}>Cancel</button><button type="submit" className="btn primary" disabled={saving}>{saving?'Saving…':'Save'}</button></div>
      </form> : profile.website && <div className="profile-links"><Icon name="Link" size={16}/><a href={profile.website} target="_blank" rel="noopener noreferrer">{profile.website}</a></div>}
      {github && <div className="profile-links"><a href={'https://github.com/'+github.username} target="_blank" rel="noopener noreferrer" aria-label={'GitHub profile for '+github.username}>GitHub · {github.username}</a></div>}
      {error && <p className="profile-error" role="alert">{error}</p>}
      <div className="profile-activity">
        <div className="profile-activity-head"><h2>{activity?data.total.toLocaleString()+' responses in the last year':'Activity in the last year'}</h2>
          <div className="profile-chart-controls"><Palette value={palette} onChange={setPalette}/>
            <div className="profile-view-switch" role="group" aria-label="Chart view">
              {[['2d','Flat'],['3d','Skyline']].map(([value,label])=><button type="button" key={value} aria-pressed={view===value} onClick={()=>setView(value)}>{label}</button>)}
            </div>
          </div>
        </div>
        {activityError ? <p role="alert" className="profile-error">{activityError} <button type="button" className="btn" onClick={()=>setReload(current=>current+1)}>Retry</button></p> :
          !activity ? <div className="profile-activity-loading" role="status">Loading recorded activity…</div> : <>
            <Skyline cells={data.cells} months={data.months} palette={palette} view={view} legend={legend} selected={selected} onSelect={setSelected}/>
            <div className="profile-legend"><span className="profile-chart-hint">{view==='3d'?'Click a day for details · drag to orbit · double-click to reset':'Click a day for details · arrow keys to explore'}</span>
              <span>Less</span>{[window.VellumUI.ProfileSky.EMPTY,...window.VellumUI.ProfileSky.PALS[palette]].map((color,index)=><button key={index} type="button" aria-label={'Highlight activity level '+index} aria-pressed={legend===index} onMouseEnter={()=>setLegend(index)} onMouseLeave={()=>setLegend(-1)} onFocus={()=>setLegend(index)} onBlur={()=>setLegend(-1)} style={{background:color}}/>)}<span>More</span>
            </div>
            <label className="profile-day-picker">Choose a day<input type="date" aria-label="Select activity day" min={data.cells[0].key} max={activity.today} value={chosen?.key||''} onChange={event=>{const index=data.cells.findIndex(cell=>cell.key===event.target.value);setSelected(index>=0?index:null);}}/></label>
            <div className="profile-stats">
              {[['Current streak',data.current+(data.current===1?' day':' days')],['Longest streak',data.longest+(data.longest===1?' day':' days')],['Active days',data.active],['Busiest day',data.busiest?data.busiest.c+' · '+data.busiest.date.toLocaleDateString(undefined,{month:'short',day:'numeric'}):'—']].map(([label,value])=><div key={label}><span>{label}</span><strong style={{color:window.VellumUI.ProfileSky.PALS[palette][3]}}>{value}</strong></div>)}
            </div>
            {chosen && <section className="profile-day-card" aria-label="Day details" aria-live="polite">
              <div className="profile-day-head"><div><h3>{formatDate(chosen.key)}</h3><span>{chosen.c} {chosen.c===1?'response':'responses'}{chosen.key===activity.today?' · today':''}</span></div>
                <div><button type="button" className="tbtn" aria-label="Previous active day" onClick={()=>move(-1)} disabled={!data.cells.slice(0,selected).some(cell=>cell.c)}><Icon name="ChevronLeft" size={16}/></button><button type="button" className="tbtn" aria-label="Next active day" onClick={()=>move(1)} disabled={!data.cells.slice(selected+1).some(cell=>cell.c)}><Icon name="ChevronRight" size={16}/></button><button type="button" className="tbtn" aria-label="Close day details" onClick={()=>setSelected(null)}><Icon name="X" size={16}/></button></div>
              </div>
              {detailsError ? <p role="alert">{detailsError}</p> : !details ? <p role="status">Loading day…</p> : !details.length ? <p>No recorded responses this day.</p> : <ul>{details.map(item=><li key={item.id}><time dateTime={item.at}>{new Date(item.at).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'})}</time><span>{item.label}</span></li>)}{chosen.c>details.length && <li className="profile-more">Showing the first {details.length} responses.</li>}</ul>}
            </section>}
            <p className="profile-activity-note">Recorded responses on this device, shown in {zone}. Earlier activity may be unavailable.</p>
          </>}
      </div>
      <h2 className="profile-recent-title">Recent activity</h2>
      <div className="profile-recent">
        {activity?.recent.length ? activity.recent.map(item=><div key={item.id}><span>{item.label}</span><time dateTime={item.at}>{new Date(item.at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}</time></div>) :
          <p>{activityError?'Activity is unavailable.':activity?'Your recorded responses will appear here.':'Loading recent activity…'}</p>}
      </div>
    </section>;
  }

  function AccountDetails({profile,onSave}) {
    const [editing,setEditing]=useState(null),[value,setValue]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
    async function save(event) {
      event.preventDefault();
      if(busy)return;
      setBusy(true);setError('');
      try{await onSave({[editing]:value});setEditing(null);}
      catch(failure){setError(failure.message||'Account details could not be saved. Try again.');}
      finally{setBusy(false);}
    }
    return <div className="profile-account-details">
      <h1>Account</h1><h2>General</h2>
      <div className="profile-account-group">
        {[['displayName','Name'],['username','Username'],['email','Email']].map(([key,label])=><div className="profile-account-row" key={key}>
          <span>{label}</span>
          {editing===key ? <form onSubmit={save}><input aria-label={label} type={key==='email'?'email':'text'} required={key==='displayName'} maxLength={key==='email'?254:120} autoFocus value={value} onChange={event=>setValue(event.target.value)}/><button type="submit" className="btn" disabled={busy}>{busy?'Saving…':'Save'}</button><button type="button" className="tbtn" aria-label={'Cancel editing '+label.toLowerCase()} disabled={busy} onClick={()=>{setEditing(null);setError('');}}><Icon name="X" size={15}/></button></form> :
            <><span className="profile-account-value">{key==='username' && profile[key]?'@'+profile[key].replace(/^@/,''):profile[key]||'Add '+label.toLowerCase()}</span><button type="button" className="tbtn" aria-label={'Edit '+label.toLowerCase()} data-tip={'Edit '+label.toLowerCase()} onClick={()=>{setValue(profile[key]||'');setEditing(key);setError('');}}><Icon name="Edit" size={16}/></button></>}
        </div>)}
      </div>
      {error && <p className="profile-error" role="alert">{error}</p>}
      <p className="profile-activity-note">Profile details are saved on this device. Editing contact email does not change your sign-in address.</p>
    </div>;
  }
  window.VellumUI=Object.assign(window.VellumUI||{},{Profile:{Page:Profile,AccountDetails,Avatar,calendar}});
})();
