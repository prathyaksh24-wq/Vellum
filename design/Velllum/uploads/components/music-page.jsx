/* The Music view consumes SpotifyPlayer's canonical snapshot and App Actions.
   View-only search, tabs and collection selection are ephemeral presentation. */
(function () {
  const {useState, useEffect, useRef} = React;
  const asset = name => 'assets/music/' + name;
  const Icon = ({name, className=''}) => <img className={'music-icon ' + className} src={asset('icons/' + name + '.svg')} alt="" aria-hidden="true"/>;
  const time = ms => { const seconds = Math.floor(Math.max(0, ms || 0) / 1000); return Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0'); };
  const artwork = item => item.artwork_url || item.album?.images?.[0]?.url || item.images?.[0]?.url || '';
  const artists = item => (item.artists || []).map(a => typeof a === 'string' ? a : a.name).filter(Boolean).join(', ');

  function PixelCover({src, title}) {
    const canvas = useRef(null);
    const [ready, setReady] = useState(false);
    useEffect(() => {
      let cancelled = false;
      const context = canvas.current?.getContext('2d');
      context?.clearRect(0, 0, 40, 40); setReady(false);
      if (!src || !context) return;
      // Drawing display-only pixels needs no CORS readback or image export.
      // Omit crossOrigin so CDNs that omit CORS headers still display correctly.
      const image = new Image();
      image.onload = () => {
        if (cancelled) return;
        context.drawImage(image, 0, 0, 40, 40); setReady(true);
      };
      image.src = src;
      return () => { cancelled = true; image.onload = null; };
    }, [src]);
    return <canvas ref={canvas} width="40" height="40" className={'music-pixel-cover' + (ready ? ' ready' : '')} role="img" aria-label={src ? 'Pixelated cover for ' + title : 'No cover available'}/>;
  }

  function Artwork({item, className=''}) {
    const src = artwork(item);
    return src ? <img className={'music-artwork ' + className} src={src} alt={'Cover for ' + item.name} loading="lazy"/>
      : <span className={'music-artwork music-artwork-empty ' + className}><Icon name={item.kind === 'artist' ? 'music' : 'album'}/></span>;
  }

  function Range({label, value, max, onCommit, disabled}) {
    const [draft, setDraft] = useState(null);
    const current = Math.max(0, Math.min(max, draft ?? value ?? 0));
    const commit = event => { onCommit(Number(event.currentTarget.value)); setDraft(null); };
    return <input type="range" aria-label={label} min="0" max={max} step="1" value={current} disabled={disabled}
      style={{'--music-range-progress':(current / Math.max(1, max) * 100) + '%'}}
      onChange={event => setDraft(Number(event.target.value))} onPointerUp={commit}
      onKeyUp={event => { if (['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','PageUp','PageDown'].includes(event.key)) commit(event); }}
      onBlur={() => setDraft(null)} onPointerCancel={() => setDraft(null)}/>;
  }

  const collectionSorts = [['original','Spotify order'],['title','Name A–Z'],['title_desc','Name Z–A']];
  const songSorts = [['original','Playlist order'],['title','Title A–Z'],['artist','Artist A–Z'],['album','Album A–Z'],['duration','Shortest first'],['duration_desc','Longest first']];
  function sorted(items, order) {
    if (order === 'original') return items;
    const field = order.startsWith('title') ? item => item.name : order === 'artist' ? artists : order === 'album' ? item => item.album : item => item.duration_ms || 0;
    return [...items].sort((a,b) => {
      const result = order.startsWith('duration') ? field(a)-field(b) : String(field(a) || '').localeCompare(String(field(b) || ''),undefined,{numeric:true,sensitivity:'base'});
      return order.endsWith('_desc') ? -result : result;
    });
  }
  function SortMenu({label, value, options, onChange, disabled}) {
    const [open,setOpen] = useState(false), ref = useRef(null);
    useEffect(() => {
      if (!open) return;
      const close = event => { if (!ref.current?.contains(event.target)) setOpen(false); };
      document.addEventListener('pointerdown',close);
      return () => document.removeEventListener('pointerdown',close);
    },[open]);
    return <div className="music-sort" ref={ref} onKeyDown={event => { if (event.key === 'Escape') {setOpen(false);ref.current?.querySelector('button')?.focus();} }}>
      <button className="music-button" aria-label={label} aria-expanded={open} aria-haspopup="menu" disabled={disabled} onClick={() => setOpen(!open)}>Sort<span>{options.find(([id]) => id === value)?.[1]}</span></button>
      {open && <div className="music-sort-options" role="menu" aria-label={label}>{options.map(([id,text]) => <button key={id} role="menuitemradio" aria-checked={id === value} onClick={() => {setOpen(false);onChange(id);}}>{text}</button>)}</div>}
    </div>;
  }

  function MusicPage({music, spotify, onReconnect, onRefreshConnection, onCloseMusic, onSelectCollection}) {
    const {player, playback, upcoming, run, busy, error, refresh, enable} = music;
    const connected = !!spotify?.connected;
    const [provider, setProvider] = useState('spotify');
    const [query, setQuery] = useState('');
    const [searchKind, setSearchKind] = useState('track');
    const [search, setSearch] = useState(null);
    const [collection, setCollection] = useState([]);
    const [nextOffset, setNextOffset] = useState(null);
    const [liked, setLiked] = useState(null);
    const [libraryTab, setLibraryTab] = useState('playlists');
    const [loading, setLoading] = useState(false);
    const [libraryError, setLibraryError] = useState('');
    const [catalog, setCatalog] = useState(false);
    const [editableAction,setEditableAction] = useState(false);
    const [catalogError, setCatalogError] = useState('');
    const [searching, setSearching] = useState(false);
    const [searchError, setSearchError] = useState('');
    const [notice, setNotice] = useState('');
    const [queueExpanded, setQueueExpanded] = useState(false);
    const [collectionView, setCollectionView] = useState('grid');
    const [detail, setDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState('');
    const [detailRestricted, setDetailRestricted] = useState(false);
    const [collectionOrder, setCollectionOrder] = useState('original');
    const [songOrder, setSongOrder] = useState('original');
    const [sortLoading, setSortLoading] = useState(false);
    const [editor,setEditor] = useState(null);
    const [editBusy,setEditBusy] = useState(false), [editError,setEditError] = useState('');
    const [editSearch,setEditSearch] = useState(''), [editResults,setEditResults] = useState([]);
    const [pendingEdit,setPendingEdit] = useState(null);
    const pageRef = useRef(null), collectionScroll = useRef(0);
    const detailRevision = useRef(0), detailAbort = useRef(null);
    const loadRevision = useRef(0), searchRevision = useRef(0), searchAbort = useRef(null);
    const mutedVolume = useRef(50);
    const sortAbort = useRef(null), metadataRevision = useRef(0), detailRef = useRef(null), editGuard = useRef(false);
    detailRef.current = detail;
    const track = player?.track;
    const isPlaying = connected && !!player?.is_playing;
    const volume = player?.device?.volume_percent;
    const title = track?.name || 'Your next favorite song';
    const artist = (player?.artists || []).join(', ');
    const cover = player?.artwork_url || '';

    useEffect(() => {
      let alive = true;
      window.VellumApi.plugins.capabilities().then(contract => {
        const available = contract.features?.spotify?.enabled && contract.features.spotify.endpoints?.browse && contract.features.spotify.endpoints?.search;
        if (alive) { setCatalog(!!available); if (!available) setCatalogError('Music search and library browsing are unavailable on this backend.'); }
      }).catch(() => { if (alive) setCatalogError('Could not check music availability.'); });
      return () => { alive = false; loadRevision.current++; searchRevision.current++; searchAbort.current?.abort(); detailRevision.current++; detailAbort.current?.abort(); sortAbort.current?.abort(); metadataRevision.current++; };
    }, []);
    useEffect(() => {
      let alive = true;setEditableAction(false);
      if (connected) window.VellumApi.appActions?.catalog().then(contract => {
        if (alive) setEditableAction(contract.actions?.some(action => action.id === 'spotify.playlist.edit') || false);
      }).catch(() => { if (alive) setEditableAction(false); });
      return () => {alive = false;};
    },[connected]);

    async function loadLibrary(offset = 0, signal) {
      const revision = ++loadRevision.current;
      setLoading(true); setLibraryError('');
      try {
        const page = await window.VellumApi.plugins.spotifyBrowse({kind:libraryTab, offset, limit:20}, signal);
        if (revision !== loadRevision.current) return;
        setCollection(previous => offset ? [...previous, ...page.items.filter(item => !previous.some(p => p.uri === item.uri))] : page.items);
        setNextOffset(page.next_offset);
      } catch (err) { if (revision === loadRevision.current && err.name !== 'AbortError') setLibraryError(err.message); }
      finally { if (revision === loadRevision.current) setLoading(false); }
    }
    async function refreshLiked(signal) {
      try {
        const page = await window.VellumApi.plugins.spotifyBrowse({kind:'liked',limit:1},signal);
        if (!signal?.aborted) setLiked({id:'liked',uri:'liked',name:'Liked Songs',kind:'liked',artwork_url:page.items[0]?.artwork_url || '',total:page.total,playable:true});
      } catch (_) {}
    }
    const refreshLibrary = () => {sortAbort.current?.abort();setSortLoading(false);setCollectionOrder('original');loadLibrary();refreshLiked();};
    useEffect(() => {
      setCollection([]); setNextOffset(null);
      sortAbort.current?.abort(); setSortLoading(false); setCollectionOrder('original');
      if (!connected || !catalog) return;
      const abort = new AbortController();
      loadLibrary(0, abort.signal);
      refreshLiked(abort.signal);
      return () => { abort.abort(); loadRevision.current++; };
    }, [connected, catalog, libraryTab]);

    async function chooseSort(order, songs = false) {
      if (order === 'original') { (songs ? setSongOrder : setCollectionOrder)(order); return; }
      sortAbort.current?.abort(); const abort = new AbortController(); sortAbort.current = abort;
      setSortLoading(true); setNotice('');
      const source = detailRef.current?.source;
      let rows = songs ? detailRef.current.items : collection;
      let offset = songs ? detailRef.current.nextOffset : nextOffset;
      try {
        // Sort the complete collection, including later pages, without changing Spotify's order.
        const seen = new Set();
        while (offset !== null && offset !== undefined) {
          if (seen.has(offset) || rows.length >= 5000) throw new Error('This collection is too large to sort completely. Use Spotify order or narrow your collection.');
          seen.add(offset);
          const params = songs ? source.kind === 'liked' ? {kind:'liked'} : {kind:source.kind+'_tracks',source_id:source.id} : {kind:libraryTab};
          const page = await window.VellumApi.plugins.spotifyBrowse({...params,offset,limit:50},abort.signal);
          if (abort.signal.aborted) return;
          rows = songs ? [...rows,...page.items.map((item,index) => ({...item,position:item.position ?? offset+index}))] : [...rows,...page.items.filter(item => !rows.some(row => row.uri === item.uri))];
          offset = page.next_offset ?? null;
        }
        if (abort.signal.aborted) return;
        if (songs) {setDetail(previous => previous?.source.uri === source.uri ? {...previous,items:rows,nextOffset:null} : previous);setSongOrder(order);}
        else {setCollection(rows);setNextOffset(null);setCollectionOrder(order);}
      } catch (err) { if (err.name !== 'AbortError') setNotice(err.message); }
      finally { if (!abort.signal.aborted) setSortLoading(false); }
    }

    async function loadMetadata(source) {
      const revision = ++metadataRevision.current;
      if (source.kind !== 'playlist') return;
      try {
        const page = await window.VellumApi.plugins.spotifyBrowse({kind:'playlist_details',source_id:source.id});
        if (revision !== metadataRevision.current) return;
        const metadata = page.items[0];
        if (metadata?.id === source.id) setDetail(previous => previous?.source.uri === source.uri ? {...previous,source:{...previous.source,...metadata}} : previous);
      } catch (_) { /* Playback remains usable when Spotify withholds metadata. */ }
    }

    useEffect(() => {
      if (!connected || !catalog) return;
      const changed = event => {
        refreshLibrary();
        const source = detailRef.current?.source;
        if (source && (!event.detail?.playlist_id || source.id === event.detail.playlist_id)) {
          if (event.detail?.removed) {closeCollection();onSelectCollection?.(null);}
          else {loadDetail(source);loadMetadata(source);}
        }
      };
      window.addEventListener('vellum:spotify-library-refresh',changed);
      return () => window.removeEventListener('vellum:spotify-library-refresh',changed);
    },[connected,catalog,libraryTab]);

    async function editPlaylist(args) {
      if (!editableAction || editGuard.current || pendingEdit) return;
      editGuard.current = true; setEditBusy(true); setEditError('');
      try {
        const receipt = await window.VellumApi.plugins.spotifyPlaylistEdit(args);
        if (receipt.status !== 'confirmation_required') throw new Error(receipt.message || 'Playlist edit could not be prepared.');
        setPendingEdit({receipt,arguments:args});
      } catch (err) {setEditError(err.message);}
      finally {editGuard.current = false;setEditBusy(false);}
    }
    async function finishEdit(confirm) {
      if (editGuard.current || !pendingEdit) return;
      editGuard.current = true; setEditBusy(true);setEditError('');
      const pending = pendingEdit;
      try {
        const api = window.VellumApi.plugins;
        const receipt = confirm ? await api.spotifyPlaylistConfirm(pending.receipt,pending.arguments) : await api.spotifyPlaylistCancel(pending.receipt);
        setPendingEdit(null);
        if (confirm && receipt.status !== 'applied') throw new Error(receipt.message || 'Spotify did not verify this change.');
        if (confirm) {setEditor(null);setEditResults([]);setNotice(receipt.message);window.dispatchEvent(new CustomEvent('vellum:spotify-library-refresh',{detail:receipt.result}));}
      } catch (err) {setEditError(err.message);}
      finally {editGuard.current = false;setEditBusy(false);}
    }
    async function findEditSongs(event) {
      event.preventDefault(); if (!editSearch.trim() || editGuard.current) return;
      editGuard.current = true;setEditBusy(true);setEditError('');
      try {const page = await window.VellumApi.plugins.spotifySearch({query:editSearch.trim(),kind:'track'});setEditResults(page.items);}
      catch (err) {setEditError(err.message);}
      finally {editGuard.current = false;setEditBusy(false);}
    }

    async function find(event, kind = searchKind) {
      event?.preventDefault();
      if (!query.trim() || !catalog || !connected || editBusy || pendingEdit) return;
      detailAbort.current?.abort(); detailRevision.current++; setDetail(null);
      searchAbort.current?.abort(); const abort = new AbortController(); searchAbort.current = abort;
      const revision = ++searchRevision.current;
      setSearching(true); setSearchError(''); setSearch({query:query.trim(), items:[]});
      try {
        const page = await window.VellumApi.plugins.spotifySearch({query:query.trim(), kind}, abort.signal);
        if (revision === searchRevision.current) setSearch({...page, query:query.trim()});
      } catch (err) { if (revision === searchRevision.current && err.name !== 'AbortError') setSearchError(err.message); }
      finally { if (revision === searchRevision.current) setSearching(false); }
    }
    const clearSearch = () => { searchAbort.current?.abort(); searchRevision.current++; setSearching(false); setSearch(null); setQuery(''); setSearchError(''); };
    async function playItem(item, entries = []) {
      setNotice('');
      if (!item.playable || busy) return;
      if (item.kind === 'artist') {
        try {
          const page = await window.VellumApi.plugins.spotifyBrowse({kind:'artist_tracks', artist_id:item.id});
          if (!page.items.length) { setNotice('No playable tracks were returned for this artist.'); return; }
          const applied = await run({action:'play', uris:page.items.filter(t => t.playable).map(t => t.uri).slice(0,50)});
          if (applied && search) clearSearch();
        } catch (err) { setNotice(err.message); }
      } else if (['playlist','album'].includes(item.kind)) { const applied = await run({action:'play', context_uri:item.uri}); if (applied && search) clearSearch(); }
      else {
        const playable = entries.filter(t => t.kind === 'track' && t.playable && t.uri);
        const index = playable.findIndex(t => t.uri === item.uri);
        const applied = await run({action:'play', uris:(index < 0 ? [item] : playable.slice(index)).slice(0,50).map(t => t.uri)});
        if (applied && search) clearSearch();
      }
    }
    async function loadDetail(source, offset = 0) {
      if (!offset) setSongOrder('original');
      detailAbort.current?.abort(); const abort = new AbortController(); detailAbort.current = abort;
      const revision = ++detailRevision.current;
      setDetailLoading(true); setDetailError(''); setDetailRestricted(false);
      try {
        const params = source.kind === 'liked' ? {kind:'liked',offset,limit:50} : {kind:source.kind + '_tracks',source_id:source.id,offset,limit:50};
        const page = await window.VellumApi.plugins.spotifyBrowse(params,abort.signal);
        if (revision !== detailRevision.current) return;
        const rows = page.items.map((item,index) => ({...item,position:item.position ?? offset + index,artwork_url:item.artwork_url || (source.kind === 'album' ? source.artwork_url : '')}));
        setDetail(previous => ({source:previous?.source.uri === source.uri ? previous.source : source,items:offset ? [...(previous?.items || []),...rows] : rows,total:page.total,nextOffset:page.next_offset ?? null}));
      } catch (err) { if (revision === detailRevision.current && err.name !== 'AbortError') {
        const restricted = [403,404].includes(err.status) && source.kind === 'playlist';
        setDetailRestricted(restricted);
        setDetailError(restricted ? (err.status === 403 ? 'Spotify will not share this playlist’s song list with Vellum.' : 'Spotify has not exposed this playlist’s song list to Vellum.') + ' You can still request playback of this exact playlist, or open it in Spotify.' : err.message);
      } }
      finally { if (revision === detailRevision.current) setDetailLoading(false); }
    }
    const openCollection = source => {
      sortAbort.current?.abort();setSortLoading(false);setSongOrder('original');setEditor(null);setPendingEdit(null);setEditError('');setEditResults([]);
      collectionScroll.current = pageRef.current?.scrollTop || 0;
      clearSearch(); setNotice(''); setDetail({source,items:[],total:source.total ?? null,nextOffset:null});
      onSelectCollection?.(['playlist','album'].includes(source.kind) ? source : null);
      loadDetail(source);loadMetadata(source);
    };
    const closeCollection = () => {
      if (pendingEdit && !editGuard.current) window.VellumApi.plugins.spotifyPlaylistCancel(pendingEdit.receipt).catch(() => {});
      sortAbort.current?.abort();setSortLoading(false);metadataRevision.current++;
      detailAbort.current?.abort(); detailRevision.current++; setDetailLoading(false);setDetailError('');setDetail(null);
      setEditor(null);setPendingEdit(null);setEditError('');setEditResults([]);onSelectCollection?.(null);
    };
    useEffect(() => {
      if (pageRef.current) pageRef.current.scrollTop = detail ? 0 : collectionScroll.current;
    },[detail?.source.uri]);
    const playDetail = item => {
      if (!detail || busy) return;
      if (detail.source.kind === 'liked') {
        const index = item ? detail.items.indexOf(item) : 0;
        const tracks = detail.items.slice(Math.max(0,index)).filter(t => t.playable && t.uri).slice(0,50);
        if (tracks.length) run({action:'play',uris:tracks.map(t => t.uri)});
      } else run({action:'play',context_uri:detail.source.uri,...(item ? {offset_position:item.position} : {})});
    };
    const chooseProvider = id => { setProvider(id); clearSearch(); closeCollection(); };
    const volumeToggle = () => {
      if (volume == null) return;
      if (volume > 0) mutedVolume.current = volume;
      run({action:'set_volume', volume_percent:volume === 0 ? mutedVolume.current : 0});
    };
    const repeat = player?.repeat || 'off';
    const button = (name, label, body, active=false, primary=false) => <button type="button" className={'music-control' + (active ? ' on' : '') + (primary ? ' primary' : '')}
      aria-label={label} aria-pressed={['shuffle','repeat','repeat-one'].includes(name) ? active : undefined}
      title={label} disabled={!connected || busy} onClick={() => run(body)}><Icon name={name}/></button>;

    return <section ref={pageRef} className="music-page" aria-label="Music" data-control-busy={String(busy)} data-ui-reference="music.page">
      <div className="music-page-inner">
        <header className="music-heading"><div className="music-title">{onCloseMusic && <button className="music-back" aria-label="Back to chat" onClick={onCloseMusic}><Icon name="chevron"/></button>}<h1>Music</h1></div><form className="music-search" role="search" onSubmit={find}>
          <button type="submit" aria-label="Search music" disabled={!connected || !catalog || provider !== 'spotify'}><Icon name="search"/></button>
          <input aria-label="Search songs, artists, albums" placeholder="Search music or paste a Spotify playlist link" value={query} onChange={e => setQuery(e.target.value)} disabled={!connected || !catalog || provider !== 'spotify'}/>
          {query && <button type="button" aria-label="Clear music search" onClick={clearSearch}><Icon name="close"/></button>}
        </form></header>
        <nav className="music-providers" aria-label="Music services">
          <button className={provider === 'spotify' ? 'selected' : ''} onClick={() => chooseProvider('spotify')} aria-pressed={provider === 'spotify'}><img src={asset('spotify-Spotify_Full_Logo_RGB_White.png')} alt="Spotify"/><span className={'music-connection-dot' + (connected ? ' connected' : '')} aria-label={connected ? 'Connected' : 'Disconnected'}/></button>
          <span className="music-provider-divider"/>
          <button className={provider === 'apple' ? 'selected' : ''} onClick={() => chooseProvider('apple')} aria-pressed={provider === 'apple'}><img className="music-service-logo" src={asset('apple-music.png')} alt=""/>Apple Music<Icon name="link"/></button>
          <span className="music-provider-divider"/>
          <button className={provider === 'youtube' ? 'selected' : ''} onClick={() => chooseProvider('youtube')} aria-pressed={provider === 'youtube'}><img className="music-service-logo" src={asset('youtube-music.png')} alt=""/>YouTube Music<Icon name="link"/></button>
        </nav>

        {provider !== 'spotify' ? <div className="music-unconnected"><Icon name="music"/><h2>{provider === 'apple' ? 'Apple Music' : 'YouTube Music'}</h2><p>This service is not connected to Vellum yet.</p><button className="music-button" onClick={() => chooseProvider('spotify')}>Back to Spotify</button></div> : <>
          {detail ? <section className="music-detail" aria-label={detail.source.name + ' tracks'}>
            <button className="music-detail-back" disabled={editBusy} onClick={closeCollection}><Icon name="chevron"/>Back to your collection</button>
            <header className="music-detail-header"><Artwork item={detail.source}/><div><p>{detail.source.kind === 'liked' ? 'Your library' : detail.source.kind === 'album' ? 'Album' : 'Playlist'}</p><h2>{detail.source.name}</h2><span>{artists(detail.source)}{artists(detail.source) && detail.total !== null ? ' · ' : ''}{detail.total !== null ? detail.total + ' songs' : ''}</span></div></header>
            <div className="music-detail-toolbar"><button className="music-detail-play" aria-label={'Play ' + detail.source.name} disabled={busy || detailLoading && !detail.items.length || !detailRestricted && !detail.items.some(t => t.playable)} onClick={() => playDetail()}><Icon name="play"/>Play</button><span>{detail.items.length < detail.total ? detail.items.length + ' of ' + detail.total + ' songs' : ''}</span>
              <div className="music-detail-tools"><SortMenu label="Sort playlist songs" value={songOrder} options={songSorts} disabled={detailLoading || sortLoading || editBusy} onChange={order => chooseSort(order,true)}/>
                <button className="music-button" aria-label="Refresh playlist songs" disabled={detailLoading || editBusy || sortLoading} onClick={() => {loadDetail(detail.source);loadMetadata(detail.source);}}><Icon name="refresh"/></button>
                {detail.source.kind === 'playlist' && <><button className="music-button" disabled={!editableAction || !detail.source.editable || editBusy || !!pendingEdit} onClick={() => {setEditor({name:detail.source.name,description:detail.source.description || ''});setEditError('');}}>Edit playlist</button><button className="music-button" disabled={!editableAction || editBusy || !!pendingEdit} onClick={() => editPlaylist({operation:'remove',playlist_id:detail.source.id})}>Remove from library</button></>}
              </div>
            </div>
            {detail.source.kind === 'playlist' && !detail.source.editable && <p className="music-empty">Playlist editing is available for playlists you own. You can remove saved playlists from your library.</p>}
            {editor && <section className="music-playlist-editor" aria-label="Edit playlist">
              <form onSubmit={event => {event.preventDefault();editPlaylist({operation:'update_details',playlist_id:detail.source.id,name:editor.name.trim(),description:editor.description});}}>
                <label>Playlist name<input aria-label="Playlist name" maxLength="200" value={editor.name} disabled={editBusy || !!pendingEdit} onChange={event => setEditor({...editor,name:event.target.value})}/></label>
                <label>Description<textarea aria-label="Playlist description" maxLength="300" value={editor.description} disabled={editBusy || !!pendingEdit} onChange={event => setEditor({...editor,description:event.target.value})}/></label>
                <div className="music-editor-actions"><button className="music-button" type="submit" disabled={editBusy || !!pendingEdit || !editor.name.trim()}>Review changes</button><button className="music-button" type="button" disabled={editBusy || !!pendingEdit} onClick={() => {setEditor(null);setEditResults([]);setEditError('');}}>Close editor</button></div>
              </form>
              <form className="music-add-song" onSubmit={findEditSongs}><label htmlFor="music-add-query">Add songs</label><div><input id="music-add-query" aria-label="Search songs to add" value={editSearch} placeholder="Song title or artist" disabled={editBusy || !!pendingEdit} onChange={event => setEditSearch(event.target.value)}/><button className="music-button" type="submit" disabled={editBusy || !!pendingEdit || !editSearch.trim()}>Search</button></div></form>
              <div className="music-edit-results">{editResults.map(item => <div className="music-edit-song" key={item.uri}><Artwork item={item}/><span><b>{item.name}</b><small>{artists(item)}</small></span><button className="music-button" aria-label={'Add ' + item.name + ' to playlist'} disabled={!editableAction || editBusy || !!pendingEdit || !item.playable} onClick={() => editPlaylist({operation:'add_items',playlist_id:detail.source.id,uris:[item.uri]})}>Add</button></div>)}</div>
            </section>}
            {pendingEdit && <section className="music-edit-confirm" aria-label="Confirm playlist change"><p>{pendingEdit.receipt.message}</p><div><button className="music-button" disabled={editBusy} onClick={() => finishEdit(true)}>{pendingEdit.arguments.operation === 'remove' ? 'Remove playlist' : 'Save change'}</button><button className="music-button" disabled={editBusy} onClick={() => finishEdit(false)}>Cancel change</button></div></section>}
            {editBusy && <p className="music-empty" role="status">Checking Spotify…</p>}
            {editError && <p className="music-error" role="alert">{editError}</p>}
            {sortLoading && <p className="music-empty" role="status">Loading all songs to sort…</p>}
            {detailError && <p className="music-error" role="alert">{detailError} {detailRestricted ? <a className="music-button" href={'https://open.spotify.com/playlist/' + detail.source.id} target="_blank" rel="noopener noreferrer">Open in Spotify</a> : <button className="music-button" onClick={() => loadDetail(detail.source,detail.nextOffset ?? 0)}>Try again</button>}</p>}
            <div className="music-track-head" aria-hidden="true"><span>#</span><span>Title</span><span>Album</span><span>Time</span></div>
            <div className="music-track-list">{sorted(detail.items,songOrder).map((item,index) => <div className="music-track-item" key={item.position ?? index}><button className={'music-track-row' + (item.uri && item.uri === track?.uri ? ' current' : '')} aria-label={'Play ' + item.name + (artists(item) ? ' by ' + artists(item) : '')} disabled={busy || !item.playable} onClick={() => playDetail(item)}>
              <span className="music-track-number"><span>{(item.position ?? index) + 1}</span><Icon name="play"/></span><span className="music-track-title"><Artwork item={item}/><span><b>{item.name}</b><small>{artists(item) || (item.playable ? '' : 'Unavailable')}</small></span></span><span className="music-track-album">{item.album || (detail.source.kind === 'album' ? detail.source.name : '')}</span><span className="music-track-time">{item.duration_ms ? time(item.duration_ms) : '—'}</span>
            </button>{detail.source.editable && <button className="music-song-remove" aria-label={'Remove ' + item.name + ' from playlist'} title="Remove all occurrences from playlist" disabled={!editableAction || editBusy || !!pendingEdit || !item.playable} onClick={() => editPlaylist({operation:'remove_items',playlist_id:detail.source.id,uris:[item.uri]})}><Icon name="close"/></button>}</div>)}</div>
            {detailLoading && <p className="music-empty" role="status">Loading songs…</p>}
            {!detailLoading && !detailError && !detail.items.length && <p className="music-empty">No tracks were returned for this collection.</p>}
            {detail.nextOffset !== null && <button className="music-button music-load-more" disabled={detailLoading || sortLoading} onClick={() => loadDetail(detail.source,detail.nextOffset)}>Load more songs</button>}
          </section> : search !== null ? <div className="music-search-results">
            <div className="music-section-heading"><h2>Search results</h2><button className="music-button" onClick={clearSearch}>Back to your music</button></div>
            <div className="music-library-tabs" aria-label="Search type">{[['track','Songs'],['artist','Artists'],['album','Albums'],['playlist','Playlists']].map(([id,label]) => <button key={id} className={searchKind === id ? 'on' : ''} onClick={() => {setSearchKind(id); find(null,id);}}>{label}</button>)}</div>
            {searching ? <p className="music-empty" role="status">Searching Spotify…</p> : searchError ? <p className="music-error" role="alert">{searchError}</p> : !search.items.length ? <p className="music-empty">No results for “{search.query}”.</p> : <div className="music-results-list">{search.items.map(item => <button className="music-result" key={item.uri} disabled={busy || !item.playable} onClick={() => ['playlist','album'].includes(item.kind) ? openCollection(item) : playItem(item, search.items)}><Artwork item={item}/><span><b>{item.name}</b><small>{artists(item) || item.kind}</small></span><Icon name={['playlist','album'].includes(item.kind) ? 'chevron' : 'play'}/></button>)}</div>}
          </div> : <>
            <div className="music-listening-room">
              <div className="music-turntable" aria-label={isPlaying ? 'Vinyl playing' : 'Vinyl paused'}>
                <div className="music-record-perspective"><div className="music-record" style={{animationPlayState:isPlaying ? 'running' : 'paused'}} data-playing={String(isPlaying)}>
                  <img className="music-record-base" src={asset('vinyl-disc.png')} alt="" draggable="false"/>
                  <PixelCover src={cover} title={title}/>
                </div></div>
                <img className="music-tonearm" src={asset('tonearm.png')} alt="" draggable="false"/>
              </div>
              <div className="music-now-playing">
                <div className="music-eyebrow">Now playing</div>
                <div className="music-current-track"><Artwork item={{name:title,artwork_url:cover}}/><div><h2>{title}</h2><p>{artist || (connected ? 'Choose something from your collection' : 'Connect Spotify to start listening')}</p><span>{player?.album || ''}</span>{track?.uri && <a className="music-spotify-link" href={'https://open.spotify.com/' + track.uri.split(':').slice(1).join('/')} target="_blank" rel="noopener noreferrer">Open in Spotify<Icon name="external"/></a>}</div></div>
                <div className="music-progress"><Range label="Music playback position" value={player?.progress_ms} max={Math.max(1,player?.duration_ms || 1)} disabled={!track || busy} onCommit={position_ms => run({action:'seek',position_ms})}/><div className="music-times"><span>{time(player?.progress_ms)}</span><span>{time(player?.duration_ms)}</span></div></div>
                <div className="music-controls">
                  {button('shuffle','Shuffle', {action:'set_shuffle',shuffle:!player?.shuffle},!!player?.shuffle)}
                  {button('previous','Previous song',{action:'previous'})}
                  {button(isPlaying ? 'pause' : 'play',isPlaying ? 'Pause music' : 'Play music',{action:isPlaying ? 'pause' : 'play'},false,true)}
                  {button('next','Next song',{action:'next'})}
                  {button(repeat === 'track' ? 'repeat-one' : 'repeat','Repeat: ' + repeat,{action:'set_repeat',state:repeat === 'off' ? 'context' : repeat === 'context' ? 'track' : 'off'},repeat !== 'off')}
                </div>
                <div className="music-volume"><button aria-label={volume === 0 ? 'Unmute music' : 'Mute music'} disabled={volume == null || busy} onClick={volumeToggle}><Icon name={volume === 0 ? 'mute' : 'volume'}/></button><Range label="Music volume" value={volume} max={100} disabled={volume == null || busy} onCommit={volume_percent => run({action:'set_volume',volume_percent})}/><output aria-label="Music volume percentage">{volume == null ? '—' : volume + '%'}</output></div>
                <div className="music-up-next"><div className="music-section-heading"><h3>Up next</h3><div className="music-queue-actions">{upcoming.length > 3 && <button className="music-queue-toggle" aria-expanded={queueExpanded} onClick={() => setQueueExpanded(!queueExpanded)}>{queueExpanded ? 'Show less' : 'See queue'}</button>}<button aria-label="Refresh music queue" disabled={!connected} onClick={() => refresh(true).catch(() => {})}><Icon name="refresh"/></button></div></div><div className={'music-queue-list' + (queueExpanded ? ' expanded' : '')}>{upcoming.slice(0,queueExpanded ? upcoming.length : 3).map(item => <button className="music-queue-item" key={item.uri || item.id} disabled={busy} onClick={() => playItem({...item,kind:'track',playable:true},upcoming.map(t => ({...t,kind:'track',playable:true})))}><Artwork item={item}/><span><b>{item.name}</b><small>{artists(item)}</small></span><Icon name="play"/></button>)}</div>{!upcoming.length && <p className="music-empty">Choose a playlist to keep the music going.</p>}</div>
                {!connected ? <button className="music-button" disabled={spotify?.status === 'loading'} onClick={spotify?.status === 'unreachable' ? onRefreshConnection : onReconnect}>{spotify?.status === 'loading' ? 'Checking Spotify…' : spotify?.status === 'unreachable' ? 'Retry connection' : 'Connect Spotify'}</button> : !playback.ready && playback.status !== 'shared' && <button className="music-button" disabled={['loading','connecting'].includes(playback.status)} onClick={!spotify.web_playback_ready || playback.status === 'reauth_required' ? onReconnect : enable}>{playback.status === 'autoplay_required' ? 'Enable audio' : ['loading','connecting'].includes(playback.status) ? 'Connecting player…' : 'Enable playback in Vellum'}</button>}
                {playback.message && !playback.ready && <p className="music-player-status" role="status">{playback.message}</p>}
              </div>
            </div>
            <section className="music-collection" aria-label="Your collection">
              <div className="music-section-heading"><h3>Your collection</h3><div className="music-library-tabs">{[['playlists','Playlists'],['albums','Albums']].map(([id,label]) => <button key={id} className={libraryTab === id ? 'on' : ''} onClick={() => setLibraryTab(id)}>{label}</button>)}<SortMenu label="Sort music collection" value={collectionOrder} options={collectionSorts} disabled={loading || sortLoading || !connected} onChange={order => chooseSort(order)}/><span className="music-view-switch" role="group" aria-label="Collection view">{[['grid','Grid view'],['list','List view']].map(([id,label]) => <button key={id} aria-label={label} aria-pressed={collectionView === id} onClick={() => setCollectionView(id)}><Icon name={id}/></button>)}</span><button aria-label="Refresh music collection" disabled={loading || sortLoading || !catalog || !connected} onClick={refreshLibrary}><Icon name="refresh"/></button></div></div>
              {catalogError && <p className="music-error" role="alert">{catalogError}</p>}
              {libraryTab === 'playlists' && connected && catalog && <p className="music-empty">Spotify may omit personalized mixes from this list. Paste a playlist’s Spotify link in search to open that exact playlist.</p>}
              {libraryError && <p className="music-error" role="alert">{libraryError} <button className="music-button" onClick={() => loadLibrary()}>Try again</button></p>}
              <div className={collectionView === 'grid' ? 'music-collection-grid' : 'music-collection-list'}>{libraryTab === 'playlists' && connected && liked && <button className="music-collection-card" onClick={() => openCollection(liked)}><Artwork item={liked}/><span><b>Liked Songs</b><small>{liked.total} songs</small></span><Icon name="chevron"/></button>}{sorted(collection,collectionOrder).map(item => <button className="music-collection-card" key={item.uri} onClick={() => openCollection(item)}><Artwork item={item}/><span><b>{item.name}</b><small>{artists(item) || (item.linked ? 'Linked in Vellum' : item.kind === 'playlist' ? 'Playlist' : item.kind)}</small></span><Icon name="chevron"/></button>)}</div>
              {sortLoading && <p className="music-empty" role="status">Loading your full collection to sort…</p>}
              {loading && <p className="music-empty" role="status">Loading your collection…</p>}
              {connected && catalog && !loading && !libraryError && !collection.length && <p className="music-empty">No saved {libraryTab === 'liked' ? 'songs' : libraryTab} returned by Spotify.</p>}
              {nextOffset !== null && <button className="music-button music-load-more" disabled={loading || sortLoading} onClick={() => loadLibrary(nextOffset)}>Load more</button>}
            </section>
          </>}
        </>}
        {(error || notice) && <p className="music-error" role="alert">{error || notice}</p>}
      </div>
    </section>;
  }
  window.VellumUI = window.VellumUI || {};
  window.VellumUI.MusicPage = MusicPage;
})();
