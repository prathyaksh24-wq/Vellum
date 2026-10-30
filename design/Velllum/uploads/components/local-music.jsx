/* Local presentation shares the existing library, App Actions and audio owner. */
(function () {
  const {useState,useEffect,useRef}=React;
  function useLocalMusic({active=false,onImported}={}) {
    const [library,setLibrary]=useState(null),[catalog,setCatalog]=useState(null),[player,setPlayer]=useState(null);
    const [selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
    const guard=useRef(false),alive=useRef(true),audioInput=useRef(null),manifestInput=useRef(null),folderInput=useRef(null),fileTarget=useRef('');
    const controller=useRef(null),api=window.VellumApi?.localMusic;
    const available=name => !!api && !!catalog?.actions?.some(action => action.id==='local_music.'+name);
    async function refresh() {
      if(!api)return null;
      const next=await api.library();
      if(alive.current){setLibrary(next);setSelected(value => next.collections.some(item => item.id===value)?value:next.collections[0]?.id || '');}
      return next;
    }
    useEffect(() => {
      alive.current=true;
      window.VellumApi.appActions.catalog().then(value => {if(alive.current)setCatalog(value);}).catch(err => {if(alive.current)setError(err.message);});
      return () => {alive.current=false;};
    },[]);
    const canRead=available('playlist');
    useEffect(() => {
      if(!canRead || !active)return;
      let disposed=false,timer;
      const poll=async () => {if(document.visibilityState!=='hidden'){try{await refresh();}catch(err){if(!disposed)setError(err.message);}}if(!disposed)timer=setTimeout(poll,15000);};
      poll();return () => {disposed=true;clearTimeout(timer);};
    },[canRead,active]);
    useEffect(() => {
      if(!active || !available('playback') || !window.VellumLocalMusicPlayback)return;
      controller.current=window.VellumLocalMusicPlayback.start();
      return window.VellumLocalMusicPlayback.subscribe(setPlayer);
    },[active,available('playback')]);
    async function perform(task) {
      if(guard.current)return;
      guard.current=true;setBusy(true);setError('');setNotice('');
      try{const result=await task();await refresh();await controller.current?.wake();return result;}
      catch(err){if(alive.current)setError(err.message);return null;}
      finally{guard.current=false;if(alive.current)setBusy(false);}
    }
    async function action(name,args) {
      if(!available(name))throw new Error('Enable Local Music in Plugins to use this control.');
      const receipt=await api.action(name,args);
      if(receipt.status!=='applied')throw new Error(receipt.message || 'This music action could not be applied.');
      if(alive.current)setNotice(receipt.message);
      return receipt.result;
    }
    const files=async event => {
      const chosen=Array.from(event.target.files || []),entryId=fileTarget.current;event.target.value='';
      const supported=chosen.filter(file => /\.(mp3|flac|m4a|aac|ogg|opus|wav|webm)$/i.test(file.name));
      const result=await perform(async () => {
        if(!supported.length)throw new Error('Choose audio files in MP3, FLAC, AAC, WAV, OGG, M4A, Opus or WebM format.');
        for(const file of supported){const receipt=await api.upload(file,entryId);if(receipt.status!=='applied')throw new Error(receipt.message);setNotice(receipt.message);}
        if(supported.length<chosen.length)setNotice('Audio files imported. Other file types were skipped.');
        return true;
      });
      if(result){if(!entryId)setSelected('imports');onImported?.();}
      return result;
    };
    const importManifest=event => {
      const file=event.target.files?.[0];event.target.value='';if(!file)return;
      return perform(async () => {
        if(file.size>4*1024*1024)throw new Error('Choose a playlist manifest smaller than 4 MB.');
        let data;try{data=JSON.parse(await file.text());}catch(_){throw new Error('This playlist is not a readable JSON manifest.');}
        const result=await action('playlist',{name:data.name || 'Imported playlist',entries:data.entries,completeness:data.completeness || 'unknown',source_origin:data.source_url || ''});
        setSelected(result.collection_id);return result;
      });
    };
    const chooseFile=entryId => {fileTarget.current=entryId || '';if(audioInput.current){audioInput.current.multiple=!entryId;audioInput.current.click();}};
    const chooseFolder=() => {fileTarget.current='';folderInput.current?.click();};
    const importLink=url => perform(async () => {const result=await action('playlist',{url:url.trim()});setSelected(result.collection_id);return result;});
    const control=args => perform(() => action('playback',args));
    const collection=library?.collections.find(item => item.id===selected);
    const entries=library?.collections.flatMap(item => item.entries) || [];
    const state=player || library?.player;
    const current=entries.find(item => item.id===state?.observed?.entry_id);
    const play=(item,rows=collection?.entries || entries) => {
      const queue=rows.filter(row => row.available).map(row => row.id);
      if(!queue.length)return;
      return control({action:'play',entry_ids:queue,position:item?Math.max(0,queue.indexOf(item.id)):0});
    };
    return {library,catalog,selected,setSelected,collection,entries,state,current,busy,error,notice,available,refresh,perform,action,
      audioInput,manifestInput,folderInput,files,importManifest,chooseFile,chooseFolder,importLink,control,play,setError};
  }

  function LocalMusicContent({local,view='home',onNavigate=()=>{},Icon,Artwork}) {
    const [url,setUrl]=useState(''),[listUrl,setListUrl]=useState('');
    const [rowLimit,setRowLimit]=useState(100);
    useEffect(() => setRowLimit(100),[local.selected,view]);
    const rows=local.collection?.entries || local.entries;
    const clock=value => Math.floor((value || 0)/60000)+':'+String(Math.floor((value || 0)/1000)%60).padStart(2,'0');
    const cover=item => {const song=item.entries?.find(entry=>entry.artwork_url || entry.provider==='spotify' && entry.source_id);return <Artwork item={{...(song || item),name:item.name || item.title,kind:item.entries?'playlist':'track'}}/>;};
    const addLink=async event => {
      event.preventDefault();
      try{
        const target=new URL(url);
        if(target.protocol!=='https:')throw new Error('Use an HTTPS link.');
        if(['open.spotify.com','music.apple.com'].includes(target.hostname)){if(await local.importLink(target.href))onNavigate('import');return;}
        local.setError('Direct audio links and podcast feeds are not connected yet. Choose an audio file from your device.');
      }catch(err){local.setError(err.message || 'Enter a valid HTTPS link.');}
    };
    if(view==='add')return <div className="mw-add-page">
      <header><h1>Add your music</h1><p>Local mode plays music you own, with no subscription needed. Choose how to start.</p></header>
      <div className="mw-add-grid">
        <section className="mw-add-card upload"><Icon name="upload"/><h2>Upload files</h2><p>Choose audio files or a folder. MP3, FLAC, AAC, WAV and OGG.</p><button className="music-button primary" disabled={local.busy || !local.available('file')} onClick={() => local.chooseFile('')}>Choose files</button><button className="mw-text-button" disabled={local.busy || !local.available('file')} onClick={local.chooseFolder}>Choose folder</button></section>
        <section className="mw-add-card"><Icon name="link"/><h2>Paste a link</h2><p>Import song or playlist information from Spotify or Apple Music, then match it to audio files you own.</p><form onSubmit={addLink}><input type="url" aria-label="Link" placeholder="https://" value={url} onChange={event => setUrl(event.target.value)}/><button className="music-button primary" disabled={!url.trim() || local.busy || !local.available('playlist')}>Import song list</button></form><small>This imports song information. Add owned audio files for local playback.</small></section>
        <section className="mw-add-card"><Icon name="playlist-add"/><h2>Import a playlist</h2><p>Bring a playlist’s song list from Spotify or Apple Music. Match each song to files you own.</p><button className="music-button" disabled={local.busy || !local.available('playlist')} onClick={() => onNavigate('import')}>Import list</button></section>
      </div><p className="mw-add-footnote">Prefer your streaming account? Switch to Connected mode in the sidebar.</p>
    </div>;
    if(view==='import')return <div className="mw-content mw-import-page">
      <div className="mw-page-heading"><div><h1>Match songs</h1><p>{local.collection?.name || 'Import a playlist’s song list, then add your audio files.'}</p></div><button className="music-button" onClick={() => onNavigate('home')}>Back to your music</button></div>
      <ol className="mw-steps"><li className={!local.collection?'active':''}><span>1</span>Choose source</li><li className={local.collection?'active':''}><span>2</span>Match songs</li><li><span>3</span>Add to library</li></ol>
      <form className="mw-import-source" onSubmit={async event => {event.preventDefault();if(await local.importLink(listUrl))setListUrl('');}}><label htmlFor="mw-playlist-link">Playlist link</label><div><input id="mw-playlist-link" type="url" value={listUrl} onChange={event => setListUrl(event.target.value)} placeholder="Spotify or public Apple Music playlist link"/><button className="music-button primary" disabled={local.busy || !listUrl.trim() || !local.available('playlist')}>Import song list</button><button className="music-button" type="button" disabled={local.busy || !local.available('playlist')} onClick={() => local.manifestInput.current?.click()}>Import manifest</button></div></form>
      {local.collection && <><div className="mw-banner"><b>{rows.filter(item => item.available).length} of {rows.length}</b> matched to files on this device. Add files for the rest, or keep the missing songs for later.</div><p className="mw-caption">{local.collection.note} {local.collection.completeness!=='complete'?'Playlist completeness: '+local.collection.completeness+'.':''}</p><div className="mw-match-head"><span>#</span><span>Title</span><span>Artist</span><span>Status</span></div>{rows.map((item,index) => <div className="mw-match-row" key={item.id}><span>{index+1}</span><b className="mw-match-title">{item.artwork_url && cover(item)}<span>{item.title}</span></b><span>{item.artist || 'Unknown artist'}</span><span>{item.available?<small className="mw-match-ready">On this device</small>:<><small>Not found</small><button className="music-button" disabled={local.busy || !local.available('file')} aria-label={'Import audio for '+item.title} onClick={() => local.chooseFile(item.id)}>Add file</button></>}</span></div>)}<button className="music-button primary" onClick={() => onNavigate('home')}>Open your music</button></>}
    </div>;
    return <div className="mw-content mw-local-library">
      <div className="mw-page-heading"><div><h1>Your music</h1><p>Songs and playlists you added.</p></div><button className="music-button primary" onClick={() => onNavigate('add')}>Add music</button></div>
      <section><h2>Playlists</h2><div className="mw-local-collections">{local.library?.collections.map(item => <button className="music-collection-card" key={item.id} aria-label={'Open local playlist '+item.name} onClick={() => local.setSelected(item.id)} aria-pressed={local.selected===item.id}><Icon name="list"/><b>{item.name}</b><small>{item.entries.filter(entry => entry.available).length} of {item.entries.length} songs matched</small></button>)}</div></section>
      <section><div className="music-section-heading"><h2>{local.collection?.name || 'Songs'}</h2><div><button className="music-button" disabled={local.busy || !rows.some(item => item.available) || !local.available('playback')} onClick={() => local.play(null,rows)}>Play available songs</button>{local.collection && <><button className="mw-text-button" onClick={() => onNavigate('import')}>Match missing songs</button><a className="mw-text-button" href={window.VellumApi.localMusic.exportUrl(local.collection.id)} download>Export song list</a></>}</div></div>
      {rows.slice(0,rowLimit).map((item,index) => <div className={'mw-local-song'+(local.current?.id===item.id?' current':'')} key={item.id}><button className="mw-song-main" disabled={!item.available || local.busy || !local.available('playback')} aria-label={'Play local '+item.title} onClick={() => local.play(item,rows)}>{item.artwork_url?cover(item):<span className="mw-song-index" aria-hidden="true">{index+1}</span>}<span><b>{item.title}</b><small>{[item.artist,item.album].filter(Boolean).join(' · ') || 'Local audio'}</small></span></button><span className="mw-source-tag">{item.available?'File':'Audio needed'}</span><span className="mw-song-time">{clock(item.duration_ms)}</span>{!item.available && <button className="music-button" disabled={local.busy || !local.available('file')} aria-label={'Import audio for '+item.title} onClick={() => local.chooseFile(item.id)}>Add file</button>}</div>)}
      {rows.length>rowLimit && <button className="music-button" onClick={() => setRowLimit(limit => limit+100)}>Show more songs</button>}
      {!rows.length && <p className="music-empty">No songs in this playlist yet.</p>}</section>
    </div>;
  }
  window.VellumUI=window.VellumUI || {};
  window.VellumUI.useLocalMusic=useLocalMusic;
  window.VellumUI.LocalMusicContent=LocalMusicContent;
})();
