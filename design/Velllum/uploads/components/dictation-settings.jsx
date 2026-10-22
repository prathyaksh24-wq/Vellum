(function () {
  const {useEffect,useRef,useState}=React;
  const api=window.VellumApi.voice;
  const preferenceEvent='vellum:dictation-preferences';
  const fallback={settings:{language:'auto',save_history:true,dictionary:[],hold_shortcut:'',toggle_shortcut:'Ctrl+Shift+D'},available_languages:['en','hi','kn','ta']};
  const iconPaths={copy:'M9 9h11v11H9z M15 9V4H4v11h5',more:'M5 12h.01 M12 12h.01 M19 12h.01',download:'M12 3v12m-5-5 5 5 5-5 M4 16v5h16v-5',trash:'M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7',plus:'M12 5v14 M5 12h14',edit:'m15 4 5 5 M4 20l5-1L21 7l-5-5L4 14z',check:'m5 12 4 4L19 6'};
  const Icon=({name})=><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{name==='more'?[5,12,19].map(cx=><circle key={cx} cx={cx} cy="12" r="1" fill="currentColor" stroke="none"/>):<path d={iconPaths[name]}/>}</svg>;
  function usePreferences(onAction) {
    const [view,setView]=useState(fallback),[error,setError]=useState(''),[busy,setBusy]=useState(false),[ready,setReady]=useState(false);
    const alive=useRef(true),saving=useRef(false);
    const refresh=async()=>{
      try {const value=await api.dictationPreferences();if(alive.current){setView(value);setReady(true);setError('');}}
      catch(err){if(alive.current)setError(err.message);}
    };
    useEffect(()=>{
      alive.current=true;void refresh();
      const changed=event=>{if(event.detail?.settings){setView(value=>({...value,settings:event.detail.settings}));setReady(true);setError('');}};
      window.addEventListener(preferenceEvent,changed);
      return ()=>{alive.current=false;window.removeEventListener(preferenceEvent,changed);};
    },[]);
    const save=async patch=>{
      if(saving.current)return false;
      saving.current=true;setBusy(true);setError('');
      try {
        const receipt=await onAction?.('dictation.settings.update',{patch});
        if(receipt?.status!=='applied' || !receipt.result?.dictation_settings)throw new Error(receipt?.message || 'Dictation settings could not be saved.');
        window.dispatchEvent(new CustomEvent(preferenceEvent,{detail:{settings:receipt.result.dictation_settings}}));
        return true;
      } catch(err){if(alive.current)setError(err.message || 'Dictation settings could not be saved.');return false;}
      finally {saving.current=false;if(alive.current)setBusy(false);}
    };
    return {...view,error,busy,ready,save,refresh};
  }
  function chord(event) {
    const key=/^Key[A-Z]$/.test(event.code)?event.code.slice(3):/^Digit[0-9]$/.test(event.code)?event.code.slice(5):/^(Space|F(?:[1-9]|1[0-2]))$/.test(event.code)?event.code:'';
    if(!key || !(event.ctrlKey || event.altKey || event.metaKey))return '';
    return [['Ctrl',event.ctrlKey],['Alt',event.altKey],['Shift',event.shiftKey],['Meta',event.metaKey]].filter(([,on])=>on).map(([name])=>name).concat(key).join('+');
  }
  // App-focused shortcuts share the existing composer recorder; they never send a chat.
  function useShortcuts() {
    const prefs=usePreferences();
    useEffect(()=>{
      if(!prefs.ready)return;
      let held=false,locked=false,timer=null,pressedAt=0,active=false;
      const send=detail=>window.dispatchEvent(new CustomEvent('vellum-composer',{detail}));
      const reset=()=>{clearTimeout(timer);timer=null;held=false;locked=false;};
      const state=event=>{active=!['idle','error'].includes(event.detail);if(!active)reset();};
      const down=event=>{
        if(event.repeat || event.defaultPrevented || event.target?.closest?.('[data-shortcut-capture]'))return;
        const key=chord(event);if(!key)return;
        if(key===prefs.settings.toggle_shortcut){event.preventDefault();send('dictation');return;}
        if(key!==prefs.settings.hold_shortcut)return;
        event.preventDefault();
        if(timer){clearTimeout(timer);timer=null;locked=true;held=false;return;}
        if(locked || active){reset();send('dictation-stop');return;}
        held=true;pressedAt=Date.now();send('dictation-start');
      };
      const release=event=>{
        if(!held)return;
        // Releasing either the main key or a modifier ends a held chord.
        const key=prefs.settings.hold_shortcut.split('+').pop();
        if(event.code!==('Key'+key) && event.code!==('Digit'+key) && event.code!==key && !/^(Control|Shift|Alt|Meta)/.test(event.code))return;
        held=false;
        if(Date.now()-pressedAt<250)timer=setTimeout(()=>{timer=null;send('dictation-stop');},300);
        else send('dictation-stop');
      };
      const blur=()=>{if(held || timer){reset();send('dictation-stop');}};
      window.addEventListener('keydown',down);window.addEventListener('keyup',release);window.addEventListener('blur',blur);window.addEventListener('vellum:dictation-state',state);
      return()=>{blur();reset();window.removeEventListener('keydown',down);window.removeEventListener('keyup',release);window.removeEventListener('blur',blur);window.removeEventListener('vellum:dictation-state',state);};
    },[prefs.ready,prefs.settings.hold_shortcut,prefs.settings.toggle_shortcut]);
    return prefs.settings;
  }
  function Language({value='auto',languages=fallback.available_languages,onChange,disabled=false}) {
    const ordered=[...new Set(languages)].sort((a,b)=>api.languageName(a).localeCompare(api.languageName(b)));
    return <window.VellumUI.VSelect className="pdrop-select dictation-language" ariaLabel="Dictation language" value={value} disabled={disabled} onValueChange={onChange} menuWidth={214} options={[{value:'auto',label:'Auto detect'},...ordered.map(code=>({value:code,label:api.languageName(code)}))]}/>;
  }
  function Shortcut({label,description,value,onSave,disabled}) {
    const [editing,setEditing]=useState(false),[draft,setDraft]=useState(value || ''),[error,setError]=useState('');
    const save=async()=>{if(await onSave(draft))setEditing(false);};
    return <div className="dictation-setting-row"><div><h3>{label}</h3><p>{description}</p></div>{editing?<div className="dictation-shortcut-edit"><input data-shortcut-capture="true" autoFocus readOnly value={draft || 'Press shortcut'} aria-label={label+' keys'} onKeyDown={event=>{event.preventDefault();event.stopPropagation();if(event.key==='Escape'){setEditing(false);return;}if(['Backspace','Delete'].includes(event.key)){setDraft('');setError('');return;}const next=chord(event);if(next){setDraft(next);setError('');}else if(!['Control','Alt','Shift','Meta'].includes(event.key))setError('Include Ctrl, Alt or Meta.');}}/><button disabled={disabled} onClick={()=>void save()}>Save</button><button onClick={()=>setEditing(false)}>Cancel</button>{error&&<span role="alert">{error}</span>}</div>:<button className="dictation-shortcut" aria-label={'Set '+label.toLowerCase()} disabled={disabled} onClick={()=>{setDraft(value || '');setEditing(true);}}><span>{value || 'Off'}</span><Icon name="edit"/></button>}</div>;
  }
  function Settings({onAction,onConfirm,onCancel}) {
    const prefs=usePreferences(onAction);
    const [view,setView]=useState(null),[query,setQuery]=useState(''),[language,setLanguage]=useState(''),[offset,setOffset]=useState(0);
    const [loading,setLoading]=useState(true),[error,setError]=useState(''),[pending,setPending]=useState(null),[busy,setBusy]=useState(false),[copied,setCopied]=useState(''),[menu,setMenu]=useState(''),[expanded,setExpanded]=useState('');
    const [words,setWords]=useState([]),[dirty,setDirty]=useState(false);
    const revision=useRef(0),alive=useRef(true),menuRef=useRef(null),dictionaryRef=useRef(null);
    useEffect(()=>{if(!dirty)setWords(prefs.settings.dictionary || []);},[prefs.settings.dictionary,dirty]);
    const load=async()=>{
      const current=++revision.current;setLoading(true);setError('');
      try {const data=await api.dictationHistory({offset,limit:30,query,language});if(alive.current && revision.current===current){setView(data);if(offset && data.total<=offset)setOffset(Math.max(0,offset-30));}}
      catch(err){if(alive.current && revision.current===current)setError(err.message || 'Dictation history could not load.');}
      finally {if(alive.current && revision.current===current)setLoading(false);}
    };
    useEffect(()=>{alive.current=true;return()=>{alive.current=false;revision.current++;};},[]);
    useEffect(()=>{const timer=setTimeout(load,query?200:0);return()=>{clearTimeout(timer);revision.current++;};},[offset,query,language]);
    useEffect(()=>{const changed=()=>{void load();};window.addEventListener('vellum:dictation-history',changed);return()=>window.removeEventListener('vellum:dictation-history',changed);},[offset,query,language]);
    useEffect(()=>{if(!copied)return;const timer=setTimeout(()=>setCopied(''),1800);return()=>clearTimeout(timer);},[copied]);
    useEffect(()=>{if(!menu)return;const close=event=>{if(event.key==='Escape' || (event.type==='pointerdown' && !menuRef.current?.contains(event.target)))setMenu('');};document.addEventListener('pointerdown',close);document.addEventListener('keydown',close);return()=>{document.removeEventListener('pointerdown',close);document.removeEventListener('keydown',close);};},[menu]);
    const copy=async entry=>{try{await navigator.clipboard.writeText(entry.text);setCopied(entry.id);}catch(_){setError('Copy failed. Open the transcript to select and copy its text.');}};
    const download=async entry=>{setMenu('');setError('');try{await api.downloadDictation(entry.id);}catch(err){setError(err.message);}};
    const remove=async entry=>{
      if(busy || pending)return;setMenu('');setBusy(true);setError('');
      try {const receipt=await onAction('dictation.history.delete',entry?{entry_id:entry.id}:{all:true});if(receipt?.status==='confirmation_required')setPending({receipt,label:entry?'Delete this recording and transcript?':'Clear all dictation history?'});else if(receipt?.status==='applied')await load();else throw new Error(receipt?.message || 'History could not be deleted.');}
      catch(err){setError(err.message);}finally{setBusy(false);}
    };
    const decide=async confirmed=>{
      if(!pending || busy)return;setBusy(true);setError('');
      try {const receipt=await (confirmed?onConfirm(pending.receipt):onCancel(pending.receipt));if(confirmed && receipt?.status!=='applied')throw new Error(receipt?.message || 'History could not be deleted.');setPending(null);if(confirmed)await load();}catch(err){setError(err.message);}finally{setBusy(false);}
    };
    const saveWords=async()=>{if(await prefs.save({dictionary:words.map(word=>word.trim()).filter(Boolean)}))setDirty(false);};
    const disabled=!prefs.ready || prefs.busy;
    return <section className="dictation-settings" aria-label="Dictation settings">
      <h2 className="set-title">Voice</h2><div className="dictation-tab" role="tablist" aria-label="Voice settings"><button role="tab" aria-selected="true">Dictation</button></div>
      <section className="dictation-group" aria-label="Dictation preferences">
        <Shortcut label="Dictation shortcut" description="Hold to dictate, or double-tap for hands-free" value={prefs.settings.hold_shortcut} disabled={disabled} onSave={hold_shortcut=>prefs.save({hold_shortcut})}/>
        <Shortcut label="Single-tap shortcut" description="Press once to start, and again to finish" value={prefs.settings.toggle_shortcut} disabled={disabled} onSave={toggle_shortcut=>prefs.save({toggle_shortcut})}/>
        <details className="dictation-advanced"><summary>Advanced</summary><p className="dictation-shortcut-note">Shortcuts work while Vellum is focused. Backspace clears a shortcut when editing.</p><div className="dictation-setting-row"><div><h3>Spoken language</h3><p>Select Kannada for Kannada with a few English words.</p></div><Language value={prefs.settings.language} languages={prefs.available_languages} onChange={language=>prefs.save({language})} disabled={disabled}/></div><div className="dictation-setting-row"><div><h3>Save recordings and transcripts</h3><p>{prefs.settings.save_history?'Keep every completed dictation on this device until you delete it.':'New dictations are not saved. Existing history stays until deleted.'}</p></div><button className={'sw'+(prefs.settings.save_history?' on':'')} role="switch" aria-label="Save dictation history" aria-checked={prefs.settings.save_history} disabled={disabled} onClick={()=>prefs.save({save_history:!prefs.settings.save_history})}/></div></details>
      </section>
      {(error || prefs.error)&&<p className="dictation-error" role="alert">{error || prefs.error}</p>}
      {pending&&<div className="dictation-confirm" role="alertdialog" aria-label={pending.label}><strong>{pending.label}</strong><p>This permanently removes saved audio and transcript text. Sent chat messages are kept.</p><div><button disabled={busy} onClick={()=>void decide(false)}>Keep history</button><button className="danger" disabled={busy} onClick={()=>void decide(true)}>Delete permanently</button></div></div>}
      <section className="dictation-group" aria-label="Recent recordings"><div className="dictation-group-heading"><div><h3>Recent recordings</h3><p>All your recordings and transcripts are saved on this device</p></div><button className="dictation-text-button" disabled={!view || !Object.keys(view.language_counts).length || busy || !!pending} onClick={()=>void remove(null)}>Clear history</button></div>
        <div className="dictation-history-tools"><input type="search" aria-label="Search dictation history" placeholder="Search transcripts" value={query} onChange={event=>{setQuery(event.target.value);setOffset(0);}}/><window.VellumUI.VSelect className="pdrop-select dictation-filter" ariaLabel="Filter dictation language" value={language} onValueChange={value=>{setLanguage(value);setOffset(0);}} menuWidth={214} options={[{value:'',label:'All languages'},...Object.entries(view?.language_counts || {}).map(([code,count])=>({value:code,label:api.languageName(code)+' ('+count+')'}))]}/></div>
        <div className="dictation-history-list" aria-busy={loading}>
          {loading&&!view&&<p className="dictation-empty" role="status">Loading recordings…</p>}
          {!loading&&(error || prefs.error)&&<button className="dictation-text-button" onClick={()=>{void prefs.refresh();void load();}}>Retry</button>}
          {!loading&&!error&&view?.items.length===0&&<p className="dictation-empty">{query || language?'No transcripts match these filters.':'Your next completed dictation will appear here. Earlier unsaved recordings cannot be recovered.'}</p>}
          {view?.items.map(entry=><article className="dictation-history-entry" key={entry.id}><div className="dictation-recording-row"><button className="dictation-transcript" aria-label={expanded===entry.id?'Collapse transcript':'Read transcript'} aria-expanded={expanded===entry.id} onClick={()=>setExpanded(expanded===entry.id?'':entry.id)}><span lang={entry.language || undefined}>{entry.text}</span><small><time dateTime={entry.created_at}>{new Date(entry.created_at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}</time><span>{entry.requested_language==='auto'?'Auto → ':''}{api.languageName(entry.language || entry.requested_language)}</span><span>{Math.round(entry.duration_seconds)}s</span></small></button><button className="dictation-icon" aria-label={copied===entry.id?'Copied':'Copy dictation'} title={copied===entry.id?'Copied':'Copy dictation'} onClick={()=>void copy(entry)}><Icon name={copied===entry.id?'check':'copy'}/></button><div className="dictation-more" ref={menu===entry.id?menuRef:null}><button className="dictation-icon" aria-label="Recording options" aria-expanded={menu===entry.id} onClick={()=>setMenu(menu===entry.id?'':entry.id)}><Icon name="more"/></button>{menu===entry.id&&<div className="dictation-recording-menu"><button disabled={!entry.has_recording} onClick={()=>void download(entry)}><Icon name="download"/>{entry.has_recording?'Download recording':'No saved audio'}</button><button disabled={busy || !!pending} onClick={()=>void remove(entry)}><Icon name="trash"/>Delete recording</button></div>}</div></div>{expanded===entry.id&&<p className="dictation-full-transcript" lang={entry.language || undefined}>{entry.text}</p>}</article>)}
        </div>
        {view&&view.total>0&&<div className="dictation-pagination"><span>{offset+1}–{Math.min(offset+view.items.length,view.total)} of {view.total}</span><button disabled={loading || offset===0} onClick={()=>setOffset(Math.max(0,offset-30))}>Previous</button><button disabled={loading || offset+30>=view.total} onClick={()=>setOffset(offset+30)}>Next</button></div>}
      </section>
      <section className="dictation-group" aria-label="Dictation dictionary" ref={dictionaryRef}><div className="dictation-group-heading"><div><h3>Dictation dictionary</h3><p>Words or phrases dictation should recognize</p></div><button className="dictation-add" disabled={disabled || words.length>=100} onClick={()=>{setWords([...words,'']);setDirty(true);setTimeout(()=>dictionaryRef.current?.querySelector('input:last-of-type')?.focus(),0);}}><Icon name="plus"/>Add entry</button></div>{words.length===0&&<p className="dictation-empty">Add names, places, or words you use often.</p>}{words.map((word,index)=><div className="dictation-word" key={index}><input aria-label={'Dictionary word '+(index+1)} placeholder="Word or phrase" maxLength={100} value={word} disabled={disabled} onChange={event=>{setWords(words.map((value,i)=>i===index?event.target.value:value));setDirty(true);}}/><button className="dictation-icon" aria-label={'Remove dictionary word '+(index+1)} disabled={disabled} onClick={()=>{setWords(words.filter((_,i)=>i!==index));setDirty(true);}}><Icon name="trash"/></button></div>)}{dirty&&<div className="dictation-dictionary-save"><span>Words guide recognition; they do not guarantee exact spelling.</span><button disabled={disabled} onClick={()=>void saveWords()}>Save words</button></div>}</section>
      <span className="dictation-copy-status" role="status">{copied?'Dictation copied':''}</span>
    </section>;
  }
  window.VellumUI=window.VellumUI || {};
  window.VellumUI.Dictation={Settings,Language,usePreferences,useShortcuts};
})();
