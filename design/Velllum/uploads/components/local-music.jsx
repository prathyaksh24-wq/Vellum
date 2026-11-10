/* Local presentation shares the existing library, App Actions and audio owner. */
(function () {
  const {useState,useEffect,useRef,useMemo}=React;
  const emptyEntries = [];

  const LocalPlaylistCover = React.memo(function LocalPlaylistCover({group, Icon}) {
    const images = new Set();
    for (const entry of group.entries) {
      if (entry.artwork_url) images.add(entry.artwork_url);
      if (images.size === 4) break;
    }
    return <span className={'mw-collection-cover'+(images.size>1?' collage':'')} aria-hidden="true">
      {images.size ? [...images].map(src => <img key={src} src={src} alt="" loading="lazy" referrerPolicy="no-referrer"/>) : <Icon name="list"/>}
    </span>;
  });
  function useLocalMusic({active=false,onImported}={}) {
    const [library,setLibrary]=useState(null),[catalog,setCatalog]=useState(null),[player,setPlayer]=useState(null);
    const [selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
    const [downloadTarget,setDownloadTarget]=useState('');
    const [controlBusy,setControlBusy]=useState(false);
    const controlGuard=useRef(false);
    const guard=useRef(false),alive=useRef(true),audioInput=useRef(null),manifestInput=useRef(null),folderInput=useRef(null);
    const controller=useRef(null),api=window.VellumApi?.localMusic;
    const autoImports=useRef(new Set());
    const available=name => !!api && !!catalog?.actions?.some(action => action.id==='local_music.'+name);
    async function refresh(fresh=false) {
      if(!api)return null;
      const next=await api.library({fresh});
      if(alive.current){
        setLibrary(next);setSelected(value => next.collections.some(item => item.id===value)?value:next.collections[0]?.id || '');
        for(const group of next.collections){
          if(!autoImports.current.delete(group.id))continue;
          setSelected(group.id);setDownloadTarget('');onImported?.('playlist');
          setNotice(group.name+' is ready in your library.');
        }
      }
      return next;
    }
    useEffect(() => {
      alive.current=true;
      window.VellumApi.appActions.catalog().then(value => {if(alive.current)setCatalog(value);}).catch(err => {if(alive.current)setError(err.message);});
      return () => {alive.current=false;};
    },[]);
    const canRead=available('playlist');
    const hasActiveJobs=!!library?.jobs?.some(job => job.status==='queued' || job.status==='running');
    useEffect(() => {
      if(!canRead || !active)return;
      let disposed=false,timer;
      const poll=async () => {if(document.visibilityState!=='hidden'){try{await refresh();}catch(err){if(!disposed)setError(err.message);}}if(!disposed)timer=setTimeout(poll,hasActiveJobs?2000:15000);};
      poll();return () => {disposed=true;clearTimeout(timer);};
    },[canRead,active,hasActiveJobs]);
    useEffect(() => {
      if(!active || !available('playback') || !window.VellumLocalMusicPlayback)return;
      controller.current=window.VellumLocalMusicPlayback.start();
      return window.VellumLocalMusicPlayback.subscribe(setPlayer);
    },[active,available('playback')]);
    async function perform(task) {
      if(guard.current)return;
      guard.current=true;setBusy(true);setError('');setNotice('');
      try{const result=await task();await refresh(true);return result;}
      catch(err){if(alive.current)setError(err.message);return null;}
      finally{guard.current=false;if(alive.current)setBusy(false);}
    }
    async function action(name,args) {
      if(!available(name))throw new Error('Enable Local Music in Plugins to use this control.');
      const receipt=await api.action(name,args);
      if(receipt.status!=='applied')throw new Error(receipt.message || 'This music action could not be applied.');
      if(alive.current && name!=='playback')setNotice(receipt.message);
      return receipt.result;
    }
    const files=async event => {
      const chosen=Array.from(event.target.files || []);event.target.value='';
      const supported=chosen.filter(file => /\.(mp3|flac|m4a|aac|ogg|opus|wav|webm|aif|aiff|wma|ape|wv|mp4|m4b|alac)$/i.test(file.name));
      const result=await perform(async () => {
        if(!supported.length)throw new Error('Choose audio files such as MP3, FLAC, M4A, AAC, WAV, OGG, Opus, AIFF, WMA or APE.');
        for(const file of supported){const receipt=await api.upload(file);if(receipt.status!=='applied')throw new Error(receipt.message);setNotice(receipt.message);}
        if(supported.length<chosen.length)setNotice('Audio files imported. Other file types were skipped.');
        return true;
      });
      if(result){setSelected('imports');onImported?.();}
      return result;
    };
    const importManifest=async event => {
      const file=event.target.files?.[0];event.target.value='';if(!file)return;
      const result=await perform(async () => {
        if(file.size>4*1024*1024)throw new Error('Choose a playlist manifest smaller than 4 MB.');
        let data;try{data=JSON.parse(await file.text());}catch(_){throw new Error('This playlist is not a readable JSON manifest.');}
        return action('playlist',{name:data.name || 'Imported playlist',entries:data.entries,completeness:data.completeness || 'unknown',source_origin:data.source_url || ''});
      });
      if(result){setSelected(result.collection_id);onImported?.();}
      return result;
    };
    const chooseFile=() => audioInput.current?.click();
    const chooseFolder=() => folderInput.current?.click();
    const importLink=async url => {
      const result=await perform(() => action('playlist',{url:url.trim(),download_mp3:true,auto_import:true}));
      if(!result)return result;
      autoImports.current.add(result.collection_id);setDownloadTarget(result.collection_id);
      const next=await refresh();
      return {...result,imported:!!next?.collections.some(group=>group.id===result.collection_id)};
    };
    const downloadCollection=id => perform(() => action('download',{collection_id:id}));
    const remove=args => perform(() => action('remove',args));
    const refreshSource=id => perform(() => action('refresh',{collection_id:id}));
    const manageJob=(id,operation) => perform(() => action('job',{job_id:id,operation}));
    const finishImport=async id => {
      const result=await perform(() => action('playlist',{pending_import_id:id}));
      if(result){setSelected(result.collection_id);setDownloadTarget('');onImported?.();}
      return result;
    };
    const control=async args => {
      if(controlGuard.current)return;
      controlGuard.current=true;setControlBusy(true);setError('');
      try{
        const result=await action('playback',args);
        controller.current?.wake();
        return result;
      }catch(err){if(alive.current)setError(err.message);return null;}
      finally{controlGuard.current=false;if(alive.current)setControlBusy(false);}
    };
    const collection=library?.collections.find(item => item.id===selected);
    const entries=useMemo(()=>library?.collections.flatMap(item => item.entries) || emptyEntries,[library?.collections]);
    const state=player || library?.player;
    const current=entries.find(item => item.id===state?.observed?.entry_id);
    const play=(item,rows=collection?.entries || entries) => {
      const queue=rows.filter(row => row.available).map(row => row.id);
      if(!queue.length)return;
      return control({action:'play',entry_ids:queue,position:item?Math.max(0,queue.indexOf(item.id)):0});
    };
    return {library,catalog,selected,setSelected,collection,entries,state,current,busy,controlBusy,error,notice,available,refresh,perform,action,
      audioInput,manifestInput,folderInput,files,importManifest,chooseFile,chooseFolder,importLink,control,play,setError,
      downloadTarget,setDownloadTarget,downloadCollection,manageJob,finishImport,remove,refreshSource};
  }

  function LocalMusicContent({local,view='home',onNavigate=()=>{},Icon,Artwork}) {
    const [url,setUrl]=useState('');
    const [rowLimit,setRowLimit]=useState(100);
    const drafts=local.library?.pending_imports || [];
    const collection=local.collection;
    const jobs=new Map((local.library?.jobs || []).map(job => [job.entry_id,job]));
    const downloads=[...drafts,...(local.library?.collections || []).filter(group =>
      group.entries.some(entry => entry.provider!=='local' && !entry.available))];
    const target=downloads.find(group => group.id===local.downloadTarget) || downloads[0];
    const pending=drafts.some(group => group.id===target?.id);
    const targetRows=target?.entries || [];
    const ready=targetRows.filter(item => item.available).length;
    const active=targetRows.some(item => ['queued','running'].includes(jobs.get(item.id)?.status));
    const needsDownload=targetRows.some(item => !item.available && item.provider!=='local');
    const unfinished=downloads.filter(group => group.entries.some(entry => !entry.available));
    const canConvert=!!local.library?.mp3_available;
    const rows=collection?.entries || local.entries;
    useEffect(() => setRowLimit(100),[local.selected,target?.id,view]);

    const clock=value => Math.floor((value || 0)/60000)+':'+String(Math.floor((value || 0)/1000)%60).padStart(2,'0');
    const cover=item => <Artwork item={{...item,name:item.title,kind:'track'}}/>;
    const addLink=async event => {
      event.preventDefault();
      if(!canConvert || local.busy || !url.trim())return;
      const result=await local.importLink(url);
      if(result){
        setUrl('');
        onNavigate(result.imported?'playlist':'import');
      }
    };
    const linkForm=<form className="mw-import-source" onSubmit={addLink}>
      <label htmlFor="mw-playlist-link">Song or playlist link</label>
      <input id="mw-playlist-link" type="url" required value={url} onChange={event => setUrl(event.target.value)} placeholder="https://"/>
      <button className="music-button primary" type="submit"
        disabled={!canConvert || !url.trim() || local.busy || !local.available('playlist')}>
        {local.busy?'Preparing…':'Convert to MP3'}
      </button>
      {local.library && !canConvert && <small>Install the optional music tools to enable MP3 conversion.</small>}
    </form>;
    const showMore=count => count>rowLimit && <button className="music-button" onClick={() => setRowLimit(limit => limit+100)}>Show more songs</button>;
    const openDownloads=id => {
      local.setDownloadTarget(id);
      onNavigate('import');
    };
    const groupCover=group => <LocalPlaylistCover group={group} Icon={Icon}/>;
    const playlistMenu=(group,pending=false)=><details className="mw-playlist-menu"
      onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))event.currentTarget.open=false;}}
      onKeyDown={event=>{if(event.key==='Escape'){event.currentTarget.open=false;event.currentTarget.querySelector('summary').focus();}}}>
      <summary aria-label={'Actions for '+group.name} title="Playlist actions"><Icon name="more"/></summary>
      <div>
        {group.source_url && <button disabled={local.busy || !local.available('refresh')} onClick={()=>local.refreshSource(group.id)}>Refresh song list</button>}
        {!pending && <a href={window.VellumApi.localMusic.exportUrl(group.id)} download>Export song list</a>}
        <button className="mw-remove-action" disabled={local.busy || !local.available('remove')} onClick={()=>local.remove({collection_id:group.id})}>Remove playlist</button>
      </div>
    </details>;
    const completeness=group => group.completeness!=='complete' && <p className="mw-source-note">
      <strong>Incomplete source list.</strong> {group.note || 'The source may contain more songs than it exposed here.'}
    </p>;

    if(view==='add')return <div className="mw-add-page">
      <button className="mw-text-button mw-add-back" onClick={()=>onNavigate('home')}><Icon name="chevron"/>Back to your music</button>
      <header><h1>Add your music</h1><p>Import audio from your device or prepare MP3s from a song or playlist link.</p></header>
      <div className="mw-add-grid">
        <section className="mw-add-card upload">
          <Icon name="upload"/><h2>Import audio files</h2><p>Choose songs or an entire folder from your device.</p>
          <button className="music-button primary" disabled={local.busy || !local.available('file')} onClick={local.chooseFile}>Choose files</button>
          <button className="mw-text-button" disabled={local.busy || !local.available('file')} onClick={local.chooseFolder}>Choose folder</button>
        </section>
        <section className="mw-add-card">
          <Icon name="link"/><h2>Convert a link to MP3</h2><p>Paste a song or playlist link. Finished MP3s are added to your library automatically.</p>
          {linkForm}
        </section>
        <section className="mw-add-card">
          <Icon name="playlist-add"/><h2>Import a playlist file</h2><p>Restore a Vellum playlist from a JSON file.</p>
          <button className="music-button" disabled={local.busy || !local.available('playlist')} onClick={() => local.manifestInput.current?.click()}>Choose playlist file</button>
          <button className="mw-text-button" onClick={() => openDownloads('')}>View downloads</button>
        </section>
      </div>
    </div>;

    if(view==='import')return <div className="mw-content mw-import-page">
      <div className="mw-page-heading">
        <div><h1>Downloads</h1><p>Review your MP3s and import them when the queue finishes.</p></div>
        <button className="music-button" onClick={() => onNavigate('home')}>Back to your music</button>
      </div>
      {unfinished.length>0 && <div className="mw-download-groups" aria-label="Download playlists">
        {unfinished.map(group=><button key={group.id} className="mw-download-group" aria-pressed={target?.id===group.id} onClick={()=>local.setDownloadTarget(group.id)}>
          {groupCover(group)}<span><b>{group.name}</b><small>{group.entries.filter(entry=>entry.available).length} of {group.entries.length} ready</small></span>
        </button>)}
      </div>}
      {target && <section className="mw-download-list">
        <div className="mw-page-heading">
          <div className="mw-download-title">{groupCover(target)}<div><h2>{target.name}</h2><p role="status">{ready} of {targetRows.length} songs ready</p></div></div>
          <div className="mw-actions">
            {pending && <button className="music-button primary" disabled={active || !ready || local.busy || !local.available('playlist')}
              onClick={async () => {if(await local.finishImport(target.id))onNavigate('home');}}>
              {ready>0 && ready<targetRows.length && !active?'Import available songs':'Import playlist'}
            </button>}
            {needsDownload && <button className="music-button primary"
              disabled={active || !canConvert || local.busy || !local.available('download')}
              onClick={() => local.downloadCollection(target.id)}>{pending?'Retry unfinished songs':'Download missing MP3s'}</button>}
            {playlistMenu(target,pending)}
          </div>
        </div>
        {completeness(target)}
        {pending && ready>0 && ready<targetRows.length && !active && <p className="mw-caption">Unavailable songs stay in the playlist so you can retry them later.</p>}
        <div className="mw-download-table-head" aria-hidden="true"><span>Song</span><span>Progress</span><span>Actions</span></div>
        <ul className="mw-download-rows">
          {targetRows.slice(0,rowLimit).map((item,index) => {
            const job=jobs.get(item.id);
            const label=item.available?'Ready':job?.status==='running'?
              {finding:'Finding recording',downloading:'Downloading',converting:'Converting to MP3'}[job.stage] || 'Starting':
              {queued:'Queued',failed:'Failed',cancelled:'Cancelled',complete:'File unavailable'}[job?.status] || 'Audio needed';
            const percent=job?.status==='running'?job.progress:null;
            const canCancel=['queued','running'].includes(job?.status);
            const canRetry=!item.available && ['failed','cancelled'].includes(job?.status);
            return <li className="mw-download-row" key={item.id}>
              {item.artwork_url?cover(item):<span className="mw-song-index" aria-hidden="true">{index+1}</span>}
              <div className="mw-download-track"><b>{item.title}</b><small>{item.artist}</small>{job?.error && <small>{job.error}</small>}</div>
              <div className="mw-download-state">
                <span>{label}{percent!=null?' '+percent+'%':''}</span>
                {percent!=null && <progress value={percent} max="100" aria-label={label+' progress for '+item.title}/>}
              </div>
              <div className="mw-download-actions">
                {(canCancel || canRetry) && <button className="music-button" disabled={local.busy || !local.available('job') || canRetry && !canConvert}
                  aria-label={(canCancel?'Cancel ':'Retry ')+item.title}
                  onClick={() => local.manageJob(job.id,canCancel?'cancel':'retry')}>{canCancel?'Cancel':'Retry'}</button>}
                <button className="mw-icon-button" aria-label={'Remove '+item.title+' from playlist'} title="Remove from playlist"
                  disabled={local.busy || !local.available('remove')} onClick={() => local.remove({entry_id:item.id})}><Icon name="close"/></button>
              </div>
            </li>;
          })}
        </ul>
        {showMore(targetRows.length)}
      </section>}
      {!target && <div className="music-empty"><h2>No downloads in progress</h2><p>Paste a song or playlist link to add music.</p><button className="music-button primary" onClick={()=>onNavigate('add')}>Add music</button></div>}
    </div>;

    if(view!=='playlist' || !collection)return <div className="mw-content mw-local-library">
      <div className="mw-page-heading">
        <div><h1>Your music</h1><p>Songs and playlists you added.</p></div>
        <div className="mw-actions">
          <button className="music-button" onClick={() => openDownloads('')}>Downloads</button>
          <button className="music-button primary" onClick={() => onNavigate('add')}>Add music</button>
        </div>
      </div>
      <section className="mw-library-list" aria-label="Your playlists">
        {local.library?.collections.map(item=><div className="mw-library-item" key={item.id}>
          <button className="mw-library-open" aria-label={'Open local playlist '+item.name} onClick={()=>{local.setSelected(item.id);onNavigate('playlist');}}>
            {groupCover(item)}<span><b>{item.name}</b><small>{item.entries.length} songs · {item.entries.filter(entry=>entry.available).length} ready{item.completeness!=='complete'?' · Incomplete source list':''}</small></span>
          </button>
          {playlistMenu(item)}
        </div>)}
        {!local.library?.collections.length && <p className="music-empty">Add songs or a playlist to start your library.</p>}
      </section>
    </div>;

    return <div className="mw-content mw-local-library">
      <button className="mw-text-button mw-library-back" onClick={()=>onNavigate('home')}><Icon name="chevron"/>Your music</button>
      <header className="mw-local-playlist-header">
        {groupCover(collection)}<div><h1>{collection.name}</h1><p>{rows.length} songs · {rows.filter(item=>item.available).length} ready</p></div>
      </header>
      {completeness(collection)}
      <div className="mw-local-toolbar">
        <button className="music-button primary" disabled={local.controlBusy || !rows.some(item=>item.available) || !local.available('playback')}
          onClick={()=>local.play(null,rows)}><Icon name="play"/>Play playlist</button>
        {rows.some(item=>item.provider!=='local'&&!item.available) && <button className="music-button" onClick={()=>openDownloads(collection.id)}>Download missing songs</button>}
        <span className="mw-toolbar-spacer"/>{playlistMenu(collection)}
      </div>
      <section aria-label="Playlist songs">
        {rows.slice(0,rowLimit).map((item,index) => <div className={'mw-local-song'+(local.current?.id===item.id?' current':'')} key={item.id}>
          <button className="mw-song-main" disabled={!item.available || local.controlBusy || !local.available('playback')}
            aria-label={'Play local '+item.title} onClick={() => local.play(item,rows)}>
            {item.artwork_url?cover(item):<span className="mw-song-index" aria-hidden="true">{index+1}</span>}
            <span><b>{item.title}</b><small>{[item.artist,item.album].filter(Boolean).join(' · ') || 'Local audio'}</small></span>
          </button>
          <span className="mw-source-tag">{item.available?'File':'Audio needed'}</span>
          <span className="mw-song-time">{clock(item.duration_ms)}</span>
          <button className="mw-icon-button" aria-label={'Remove '+item.title+' from playlist'} title="Remove from playlist"
            disabled={local.busy || !local.available('remove')} onClick={() => local.remove({entry_id:item.id})}><Icon name="close"/></button>
        </div>)}
        {showMore(rows.length)}
        {!rows.length && <p className="music-empty">No songs in this playlist yet.</p>}
      </section>
    </div>;
  }
  window.VellumUI=window.VellumUI || {};
  window.VellumUI.useLocalMusic=useLocalMusic;
  window.VellumUI.LocalMusicContent=LocalMusicContent;
  window.VellumUI.LocalPlaylistCover=LocalPlaylistCover;
})();
