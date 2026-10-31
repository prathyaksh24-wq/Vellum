/* The Music view consumes SpotifyPlayer's canonical snapshot and App Actions.
   View-only search, tabs and collection selection are ephemeral presentation. */
(function () {
  const {useState, useEffect, useRef} = React;
  const asset = name => 'assets/music/' + name;
  const paths={
    panel:'M4 4h16v16H4zM9 4v16',home:'M3 11l9-8 9 8M5 10v10h14V10',search:'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5',
    ask:'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22',
    list:'M4 6h16M4 12h16M4 18h10',sources:'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
    settings:'M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M14 4v4M8 10v4M16 16v4',
    music:'M9 18V6l10-2v12M9 18a3 3 0 1 1-3-3 3 3 0 0 1 3 3zM19 16a3 3 0 1 1-3-3 3 3 0 0 1 3 3z',
    album:'M4 4h16v16H4zM9 15V9l6-1v6M9 15h-2M15 14h-2',play:'M7 4l13 8-13 8z',pause:'M7 4h3v16H7zM14 4h3v16h-3z',
    next:'M18 5v14M5 5l10 7-10 7z',previous:'M6 5v14M19 5L9 12l10 7z',
    shuffle:'M3 7h4l10 10h4M3 17h4l3-3M14 10l3-3h4M18 4l3 3-3 3M18 14l3 3-3 3',
    repeat:'M4 11V9a3 3 0 0 1 3-3h13M17 3l3 3-3 3M20 13v2a3 3 0 0 1-3 3H4M7 15l-3 3 3 3',
    'repeat-one':'M4 11V9a3 3 0 0 1 3-3h13M17 3l3 3-3 3M20 13v2a3 3 0 0 1-3 3H4M7 15l-3 3 3 3M11 10l1-1v6',
    heart:'M12 20s-8-5-8-11a4.5 4.5 0 0 1 8-2.5A4.5 4.5 0 0 1 20 9c0 6-8 11-8 11z',
    volume:'M4 9v6h4l5 4V5L8 9zM17 9a4 4 0 0 1 0 6',mute:'M4 9v6h4l5 4V5L8 9zM17 9l5 6M22 9l-5 6',
    queue:'M4 6h16M4 12h16M4 18h7M15 15l5 3-5 3z',close:'M6 6l12 12M18 6L6 18',chevron:'M15 6l-6 6 6 6',
    check:'M5 12l5 5 9-10',refresh:'M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12 1M18 17A7 7 0 0 1 6 16',
    upload:'M12 16V4M7 9l5-5 5 5M4 20h16',link:'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
    'playlist-add':'M4 6h12M4 12h8M4 18h8M17 14v6M14 17h6',more:'M5 12h.01M12 12h.01M19 12h.01',grid:'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
  };
  const Icon=({name,className=''}) => <svg className={'music-icon '+className} viewBox="0 0 24 24" fill={['play','pause'].includes(name)?'currentColor':'none'} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] || paths.music}/></svg>;
  const time = ms => { const seconds = Math.floor(Math.max(0, ms || 0) / 1000); return Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0'); };
  const artwork = item => item.artwork_url || item.album?.images?.[0]?.url || item.images?.[0]?.url || '';
  const artists = item => (item.artists || []).map(a => typeof a === 'string' ? a : a.name).filter(Boolean).join(', ');

  function Artwork({item, className=''}) {
    const provided=artwork(item),uri=(item.provider==='spotify' && /^[A-Za-z0-9]{22}$/.test(item.source_id || '')?'spotify:track:'+item.source_id:item.uri || ''),anchor=useRef(null);
    const [resolved,setResolved]=useState({uri:'',url:''});
    const src=provided || (resolved.uri===uri?resolved.url:'');
    useEffect(() => {
      const match=uri.match(/^spotify:track:([A-Za-z0-9]{22})$/);
      if(provided || !match || !window.VellumApi.plugins.spotifyTrackArtwork)return;
      let disposed=false,observer;
      const load=() => {
        observer?.disconnect();
        window.VellumApi.plugins.spotifyTrackArtwork(match[1]).then(result => {
          if(!disposed && result.id===match[1] && result.artwork_url)setResolved({uri,url:result.artwork_url});
        }).catch(()=>{});
      };
      if(typeof IntersectionObserver==='function' && anchor.current){
        observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting))load();},{rootMargin:'1200px'});
        observer.observe(anchor.current);
      }else load();
      return () => {disposed=true;observer?.disconnect();};
    },[provided,uri]);
    return src ? <img ref={anchor} className={'music-artwork ' + className} src={src} alt={'Cover for ' + item.name} decoding="async"/>
      : <span ref={anchor} className={'music-artwork music-artwork-empty ' + className}><Icon name={item.kind === 'artist' ? 'music' : 'album'}/></span>;
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

  function MusicPage({music, spotify, onReconnect, onRefreshConnection, onCloseMusic, onSelectCollection, onAskMusic, initialProvider='spotify'}) {
    const {player, playback, upcoming, run, busy, error, refresh, enable} = music;
    const connected = !!spotify?.connected;
    const [provider, setProvider] = useState(initialProvider);
    const [sidebarVisible,setSidebarVisible]=useState(true);
    const sidebarToggle=useRef(null),sidebarHide=useRef(null),sidebarChanged=useRef(false);
    const setSidebar=visible=>{sidebarChanged.current=true;setSidebarVisible(visible);};
    useEffect(()=>{if(sidebarChanged.current)(sidebarVisible?sidebarHide:sidebarToggle).current?.focus();},[sidebarVisible]);
    useEffect(()=>{const media=window.matchMedia('(max-width:760px)');const close=()=>{if(media.matches)setSidebar(false);};close();media.addEventListener('change',close);return()=>media.removeEventListener('change',close);},[]);
    const [screen,setScreen]=useState('home'),[themeMatch,setThemeMatch]=useState(true),[themeChoice,setThemeChoice]=useState('Midnight');
    const [playlists,setPlaylists]=useState([]),[albums,setAlbums]=useState([]),[recent,setRecent]=useState([]),[saveSelection,setSaveSelection]=useState([]),[askDraft,setAskDraft]=useState(''),[playlistLinks,setPlaylistLinks]=useState(''),[linkBusy,setLinkBusy]=useState(false);
    const linkGuard=useRef(false);
    const local=window.VellumUI.useLocalMusic({active:provider==='local',onImported:()=>setScreen('home')});
    useEffect(() => {
      const observed=music.player;
      if(!observed?.track?.uri?.startsWith('spotify:track:'))return;
      const snapshot={...observed.track,kind:'track',
        artwork_url:observed.artwork_url || artwork(observed.track),
        artists:observed.artists?.length?observed.artists:observed.track.artists || [],
        duration_ms:observed.duration_ms || observed.track.duration_ms || 0};
      setRecent(rows => [snapshot,...rows.filter(row => row.uri!==snapshot.uri)].slice(0,20));
    },[music.player?.track?.uri,music.player?.artwork_url,music.player?.artists,music.player?.duration_ms]);
    useEffect(() => {
      if(!spotify?.connected)return;
      const abort=new AbortController();
      window.VellumApi.plugins.spotifyBrowse({kind:'albums',offset:0,limit:20},abort.signal).then(page => {if(!abort.signal.aborted)setAlbums(page.items);}).catch(()=>{});
      return () => abort.abort();
    },[spotify?.connected]);
    const [query, setQuery] = useState('');
    const [suggestions,setSuggestions]=useState(null),[suggestionBusy,setSuggestionBusy]=useState(false),[suggestionIndex,setSuggestionIndex]=useState(-1);
    const suggestionAbort=useRef(null),suggestionSkip=useRef('');
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
      setEditableAction(!!connected && !!local.catalog?.actions?.some(action => action.id==='spotify.playlist.edit'));
    },[connected,local.catalog]);

    async function loadLibrary(offset = 0, signal) {
      const revision = ++loadRevision.current;
      setLoading(true); setLibraryError('');
      try {
        const page = await window.VellumApi.plugins.spotifyBrowse({kind:libraryTab, offset, limit:20}, signal);
        if (revision !== loadRevision.current) return;
        setCollection(previous => offset ? [...previous, ...page.items.filter(item => !previous.some(p => p.uri === item.uri))] : page.items);
        if(libraryTab==='playlists')setPlaylists(previous => offset?[...previous,...page.items.filter(item=>!previous.some(row=>row.uri===item.uri))]:page.items);
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

    async function find(event, kind = searchKind, text = query) {
      event?.preventDefault();
      if (!text.trim() || !catalog || !connected || editBusy || pendingEdit) return;
      suggestionAbort.current?.abort();setSuggestions(null);setSuggestionBusy(false);
      detailAbort.current?.abort(); detailRevision.current++; setDetail(null);
      searchAbort.current?.abort(); const abort = new AbortController(); searchAbort.current = abort;
      const revision = ++searchRevision.current;
      setSearching(true); setSearchError(''); setSearch({query:text.trim(), items:[]});
      try {
        const page = await window.VellumApi.plugins.spotifySearch({query:text.trim(), kind}, abort.signal);
        if (revision === searchRevision.current) setSearch({...page, query:text.trim()});
      } catch (err) { if (revision === searchRevision.current && err.name !== 'AbortError') setSearchError(err.message); }
      finally { if (revision === searchRevision.current) setSearching(false); }
    }
    const clearSearch = () => { suggestionAbort.current?.abort();setSuggestions(null);setSuggestionBusy(false);searchAbort.current?.abort(); searchRevision.current++; setSearching(false); setSearch(null); setQuery(''); setSearchError(''); };
    useEffect(() => {
      setSuggestions(null);setSuggestionIndex(-1);setSuggestionBusy(false);
      suggestionAbort.current?.abort();
      const text=query.trim();
      if(provider!=='spotify' || !['home','search'].includes(screen) || !connected || !catalog || text.length<2 || suggestionSkip.current===text)return;
      const abort=new AbortController();suggestionAbort.current=abort;
      const timer=setTimeout(async()=>{
        if(abort.signal.aborted)return;
        setSuggestionBusy(true);
        const pages=await Promise.allSettled(['track','artist'].map(kind=>window.VellumApi.plugins.spotifySearch({query:text,kind,limit:5},abort.signal)));
        if(abort.signal.aborted)return;
        const seen=new Set(),items=[];
        pages.forEach(page=>{if(page.status==='fulfilled')page.value.items.forEach(item=>{if(!seen.has(item.uri)){seen.add(item.uri);items.push(item);}});});
        setSuggestions({query:text,items:items.slice(0,10)});setSuggestionBusy(false);
      },300);
      return ()=>{clearTimeout(timer);abort.abort();};
    },[query,provider,screen,connected,catalog]);
    const selectSuggestion=item=>{
      suggestionAbort.current?.abort();setSuggestions(null);setSuggestionBusy(false);setSuggestionIndex(-1);
      if(item.kind==='artist'){openCollection(item);return;}
      suggestionSkip.current=item.name.trim();setQuery(item.name);setSearchKind('track');find(null,'track',item.name);
    };
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
        const params = source.kind === 'liked' ? {kind:'liked',offset,limit:50} : source.kind==='artist'?{kind:'artist_tracks',artist_id:source.id,offset,limit:50}:{kind:source.kind + '_tracks',source_id:source.id,offset,limit:50};
        const page = await window.VellumApi.plugins.spotifyBrowse(params,abort.signal);
        if (revision !== detailRevision.current) return;
        const rows = page.items.map((item,index) => ({...item,position:item.position ?? offset + index,artwork_url:item.artwork_url || (source.kind === 'album' ? source.artwork_url : '')}));
        setDetail(previous => ({source:previous?.source.uri === source.uri ? previous.source : source,items:offset ? [...(previous?.items || []),...rows] : rows,total:page.total,nextOffset:page.next_offset ?? null,readSource:page.source || 'api',completeness:page.completeness || 'complete',note:page.note || ''}));
      } catch (err) { if (revision === detailRevision.current && err.name !== 'AbortError') {
        const restricted = [403,404].includes(err.status) && source.kind === 'playlist';
        setDetailRestricted(restricted);
        setDetailError(restricted ? (err.status === 403 ? 'Spotify will not share this playlist’s song list with Vellum.' : 'Spotify has not exposed this playlist’s song list to Vellum.') + ' Spotify’s own playlist view is shown below. Vellum’s Play button still targets this exact playlist.' : err.message);
      } }
      finally { if (revision === detailRevision.current) setDetailLoading(false); }
    }
    const openCollection = source => {
      setProvider('spotify');setScreen('playlists');
      sortAbort.current?.abort();setSortLoading(false);setSongOrder('original');setEditor(null);setPendingEdit(null);setEditError('');setEditResults([]);
      collectionScroll.current = pageRef.current?.scrollTop || 0;
      clearSearch(); setNotice(''); setDetail({source,items:[],total:source.total ?? null,nextOffset:null});
      onSelectCollection?.(['playlist','album'].includes(source.kind) ? source : null);
      loadDetail(source);loadMetadata(source);
    };
    useEffect(() => {
      const lookup=window.VellumApi.plugins.spotifyTrackArtwork;
      if(!lookup || !detail?.items)return;
      let disposed=false;
      detail.items.filter(item=>!artwork(item) && /^spotify:track:[A-Za-z0-9]{22}$/.test(item.uri || '')).slice(-50).forEach(item=>{
        lookup(item.uri.split(':')[2]).then(result=>{if(!disposed && result.artwork_url){const image=new Image();image.src=result.artwork_url;}}).catch(()=>{});
      });
      return ()=>{disposed=true;};
    },[detail?.items]);
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
      if (['liked','artist'].includes(detail.source.kind)) {
        const index = item ? detail.items.indexOf(item) : 0;
        const tracks = detail.items.slice(Math.max(0,index)).filter(t => t.playable && t.uri).slice(0,50);
        if (tracks.length) run({action:'play',uris:tracks.map(t => t.uri)});
      } else run({action:'play',context_uri:detail.source.uri,...(item ? {offset_position:item.position} : {})});
    };
    const chooseProvider = id => { setProvider(id); setScreen('home'); clearSearch(); closeCollection(); };
    const volumeToggle = () => {
      if (volume == null) return;
      if (volume > 0) mutedVolume.current = volume;
      run({action:'set_volume', volume_percent:volume === 0 ? mutedVolume.current : 0});
    };
    const repeat = player?.repeat || 'off';
    const button = (name, label, body, active=false, primary=false) => <button type="button" className={'music-control' + (active ? ' on' : '') + (primary ? ' primary' : '')}
      aria-label={label} aria-pressed={['shuffle','repeat','repeat-one'].includes(name) ? active : undefined}
      title={label} disabled={!connected || busy} onClick={() => run(body)}><Icon name={name}/></button>;


    const isLocal=provider==='local',isApple=provider==='apple';
    const theme=isLocal?'Midnight':themeMatch?(isApple?'Apple Music':'Spotify'):themeChoice;
    const localView=screen==='home' && local.library && !local.library.collections.length?'add':screen;
    const lapsed=provider==='spotify' && connected && spotify?.product==='free';
    const expired=provider==='spotify' && ['reauth_required','authorization_required'].includes(spotify?.status);
    const canPlay=isLocal?local.available('playback'):provider==='spotify' && connected && !lapsed && !expired;
    const controlBusy=isLocal?local.busy:busy;
    const observed=isLocal?local.state?.observed || {}:null;
    const playing=isLocal?!!observed.playing:provider==='spotify' && !lapsed && !expired && !!player?.is_playing;
    const now=isLocal?(local.current?{...local.current,name:local.current.title,artists:[local.current.artist],artwork_url:local.current.artwork_url || '',uri:local.current.id}:null):isApple?null:track?{...track,artwork_url:player?.artwork_url || artwork(track),artists:player?.artists?.length?player.artists:track.artists}:null;
    const duration=isLocal?(observed.duration || 0)*1000:player?.duration_ms || 0;
    const progress=isLocal?(observed.seconds || 0)*1000:player?.progress_ms || 0;
    const level=isLocal?Math.round((local.state?.volume ?? .7)*100):volume;
    const shuffleOn=isLocal?!!local.state?.shuffle:!!player?.shuffle;
    const repeatMode=isLocal?local.state?.repeat || 'off':repeat;
    const footerVisible=!isLocal || !!local.library?.collections.length;
    const displayCollections=isLocal?local.library?.collections || []:isApple?[]:playlists;
    const navigate=id => {setScreen(id);clearSearch();closeCollection();};
    const control=(action,extra={}) => {
      if(!canPlay)return;
      if(isLocal){
        const mapped={play:observed.playing?'pause':'resume',pause:'pause',next:'next',previous:'previous',seek:'seek',set_volume:'volume',set_shuffle:'shuffle',set_repeat:'repeat'};
        local.control({action:mapped[action] || action,...extra});
      } else run({action,...extra});
    };
    const transport=(large=false) => <div className={'mw-transport'+(large?' large':'')}>
      <button className="mw-icon-button" aria-label="Shuffle music" aria-pressed={shuffleOn} disabled={!canPlay || controlBusy} onClick={() => control('set_shuffle',isLocal?{enabled:!shuffleOn}:{shuffle:!shuffleOn})}><Icon name="shuffle"/></button>
      <button className="mw-icon-button" aria-label="Previous song" disabled={!canPlay || controlBusy} onClick={() => control('previous')}><Icon name="previous"/></button>
      <button className="mw-icon-button primary" aria-label={playing?'Pause music':'Play music'} disabled={!canPlay || controlBusy || isLocal && !local.state?.queue?.length} onClick={() => control(playing?'pause':'play')}><Icon name={playing?'pause':'play'}/></button>
      <button className="mw-icon-button" aria-label="Next song" disabled={!canPlay || controlBusy} onClick={() => control('next')}><Icon name="next"/></button>
      <button className="mw-icon-button" aria-label="Repeat music" aria-pressed={repeatMode!=='off'} title={'Repeat: '+repeatMode} disabled={!canPlay || controlBusy} onClick={() => control('set_repeat',isLocal?{repeat:repeatMode==='off'?'all':repeatMode==='all'?'one':'off'}:{state:repeatMode==='off'?'context':repeatMode==='context'?'track':'off'})}><Icon name={repeatMode==='one'||repeatMode==='track'?'repeat-one':'repeat'}/></button>
    </div>;
    const seek=() => <div className="mw-progress"><span>{time(progress)}</span><Range label="Music playback position" value={progress} max={duration || 1} disabled={!canPlay || controlBusy || !duration} onCommit={position_ms => control('seek',isLocal?{seconds:position_ms/1000}:{position_ms})}/><span>{time(duration)}</span></div>;
    const coverCards=(items,limit) => <div className={'mw-cover-grid'+(collectionView==='list'?' music-collection-list':'')}>{items.slice(0,limit || items.length).map(item => <button className="music-collection-card" key={item.uri || item.id} onClick={() => openCollection(item)}><Artwork item={item}/><b>{item.name}</b><small>{artists(item) || (item.kind==='playlist'?'Playlist':item.kind==='album'?'Album':'Artist')}</small></button>)}</div>;
    const searchForm=() => <div className="mw-search-area"><form className="music-search" role="search" onSubmit={event => {setScreen('search');find(event);}} onBlur={event=>{if(!event.currentTarget.parentElement.contains(event.relatedTarget)){suggestionAbort.current?.abort();setSuggestions(null);setSuggestionBusy(false);}}}><Icon name="search"/><input aria-label="Search songs, artists, albums" role="combobox" aria-autocomplete="list" aria-expanded={!!suggestions?.items.length} aria-controls="mw-search-suggestions" aria-activedescendant={suggestionIndex>=0?'mw-suggestion-'+suggestionIndex:undefined} autoComplete="off" placeholder={isLocal?'Search your music':'Search artists, albums, tracks'} value={query} onChange={event => {suggestionSkip.current='';setQuery(event.target.value);if(isLocal)setScreen('search');}} onKeyDown={event=>{const rows=suggestions?.items || [];if(event.key==='Escape'){event.preventDefault();suggestionAbort.current?.abort();setSuggestions(null);setSuggestionBusy(false);setSuggestionIndex(-1);}else if(rows.length && ['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();setSuggestionIndex(value=>event.key==='ArrowDown'?(value+1)%rows.length:(value<1?rows.length-1:value-1));}else if(event.key==='Enter' && rows[suggestionIndex]){event.preventDefault();selectSuggestion(rows[suggestionIndex]);}}} disabled={isApple || !isLocal && (!connected || !catalog)}/>{query && <button type="button" className="mw-icon-button" aria-label="Clear music search" onClick={clearSearch}><Icon name="close"/></button>}<button className="mw-sr-only" type="submit" disabled={!connected || !catalog || isApple || isLocal}>Search music</button></form>{suggestionBusy && <p className="mw-suggestion-status" role="status">Finding suggestions…</p>}{suggestions?.items.length>0 && <div className="mw-suggestions" id="mw-search-suggestions" role="listbox" aria-label="Music suggestions">{suggestions.items.map((item,index)=><button type="button" role="option" id={'mw-suggestion-'+index} key={item.uri} aria-selected={suggestionIndex===index} tabIndex="-1" onMouseDown={event=>event.preventDefault()} onClick={()=>selectSuggestion(item)}><Artwork item={item}/><span><b>{item.name}</b><small>{item.kind==='artist'?'Artist':artists(item)}</small></span><small>{item.kind==='artist'?'Artist':'Song'}</small></button>)}</div>}</div>;

    const localRows=local.entries.filter(row => (row.title+' '+row.artist+' '+row.album).toLocaleLowerCase().includes(query.toLocaleLowerCase()));
    const savePlaylists=() => local.perform(async () => {
      let saved=0;
      for(const item of collection.filter(row => saveSelection.includes(row.id))){
        await local.action('playlist',{url:item.external_url || 'https://open.spotify.com/playlist/'+item.id});saved++;
      }
      if(saved){setProvider('local');setScreen('import');}
    });
    const addPlaylistLinks=async event => {
      event.preventDefault();if(linkGuard.current)return;
      linkGuard.current=true;setLinkBusy(true);setNotice('');
      try{
        const values=playlistLinks.split(/[\s,]+/).filter(Boolean);
        const uris=values.map(value => {
          const url=new URL(value);
          const match=url.pathname.match(/^\/(?:intl-[a-z]+\/)?playlist\/([A-Za-z0-9]{22})\/?$/i);
          if(url.protocol!=='https:' || url.hostname!=='open.spotify.com' || !match || url.username || url.password || ![null,'','443'].includes(url.port))throw new Error('Use full Spotify playlist links, separated by spaces or commas.');
          return 'spotify:playlist:'+match[1];
        });
        const receipt=await window.VellumApi.appActions.dispatch({action_id:'spotify.playlists.link',arguments:{uris}},{source:'ui'});
        if(receipt.status!=='applied')throw new Error(receipt.message || 'Playlist links could not be added.');
        setNotice(receipt.message);setPlaylistLinks('');setLibraryTab('playlists');refreshLibrary();
      }catch(err){setNotice(err.message);}finally{linkGuard.current=false;setLinkBusy(false);}
    };
    const renderEditor=() => <>
      {editor && <section className="music-playlist-editor" aria-label="Edit playlist">
        <form onSubmit={event => {event.preventDefault();editPlaylist({operation:'update_details',playlist_id:detail.source.id,name:editor.name.trim(),description:editor.description});}}>
          <label>Playlist name<input aria-label="Playlist name" maxLength="200" value={editor.name} disabled={editBusy || !!pendingEdit} onChange={event => setEditor({...editor,name:event.target.value})}/></label>
          <label>Description<textarea aria-label="Playlist description" maxLength="300" value={editor.description} disabled={editBusy || !!pendingEdit} onChange={event => setEditor({...editor,description:event.target.value})}/></label>
          <div className="mw-actions"><button className="music-button primary" disabled={editBusy || !!pendingEdit || !editor.name.trim()}>Review changes</button><button className="music-button" type="button" disabled={editBusy || !!pendingEdit} onClick={() => {setEditor(null);setEditResults([]);setEditError('');}}>Close editor</button></div>
        </form>
        <form className="music-add-song" onSubmit={findEditSongs}><label htmlFor="music-add-query">Add songs</label><div><input id="music-add-query" aria-label="Search songs to add" value={editSearch} placeholder="Song title or artist" disabled={editBusy || !!pendingEdit} onChange={event => setEditSearch(event.target.value)}/><button className="music-button" disabled={editBusy || !!pendingEdit || !editSearch.trim()}>Search</button></div></form>
        <div className="music-edit-results">{editResults.map(item => <div className="music-edit-song" key={item.uri}><Artwork item={item}/><span><b>{item.name}</b><small>{artists(item)}</small></span><button className="music-button" aria-label={'Add '+item.name+' to playlist'} disabled={!editableAction || editBusy || !!pendingEdit || !item.playable} onClick={() => editPlaylist({operation:'add_items',playlist_id:detail.source.id,uris:[item.uri]})}>Add</button></div>)}</div>
      </section>}
      {pendingEdit && <section className="music-edit-confirm mw-banner" aria-label="Confirm playlist change"><p>{pendingEdit.receipt.message}</p><div className="mw-actions"><button className="music-button primary" disabled={editBusy} onClick={() => finishEdit(true)}>{pendingEdit.arguments.operation==='remove'?'Remove playlist':'Save change'}</button><button className="music-button" disabled={editBusy} onClick={() => finishEdit(false)}>Cancel change</button></div></section>}
      {editError && <p className="music-error" role="alert">{editError}</p>}
    </>;
    const renderDetail=() => <section className="music-detail" aria-label={detail.source.name+' tracks'}>
      <div className="mw-detail-hero"><Artwork item={detail.source}/><div><button className="mw-text-button music-detail-back" onClick={closeCollection}><Icon name="chevron"/>Back to your collection</button><p className="mw-label">{detail.source.kind==='liked'?'Your library':detail.source.kind}</p><h1>{detail.source.name}</h1><p>{artists(detail.source)}{artists(detail.source) && detail.total!==null?' · ':''}{detail.total!==null?detail.total+(detail.readSource==='public_embed'?' visible songs':' songs'):''}</p></div></div>
      <div className="mw-detail-controls">
        <button className="mw-icon-button primary music-detail-play" aria-label={'Play '+detail.source.name} disabled={!canPlay || busy || detailLoading && !detail.items.length || !detailRestricted && !detail.items.some(item => item.playable)} onClick={() => playDetail()}><Icon name="play"/></button>
        <button className="mw-icon-button" aria-label="Shuffle playlist" disabled={!canPlay || busy} onClick={() => run({action:'set_shuffle',shuffle:!player?.shuffle})}><Icon name="shuffle"/></button>
        <button className="mw-icon-button" aria-label="Favorite playlist" disabled title="Favorites are not available yet"><Icon name="heart"/></button>
        <SortMenu label="Sort playlist songs" value={songOrder} options={songSorts} disabled={detailRestricted || detailLoading || sortLoading || editBusy} onChange={order => chooseSort(order,true)}/>
        <button className="mw-icon-button" aria-label="Refresh playlist songs" disabled={detailLoading || editBusy || sortLoading} onClick={() => {loadDetail(detail.source);loadMetadata(detail.source);}}><Icon name="refresh"/></button>
        <div className="mw-detail-tools">{detail.source.kind==='playlist' && <><button className="music-button" disabled={!editableAction || !detail.source.editable || editBusy || !!pendingEdit} onClick={() => {setEditor({name:detail.source.name,description:detail.source.description || ''});setEditError('');}}>Edit playlist</button><button className="mw-text-button" disabled={!editableAction || editBusy || !!pendingEdit} onClick={() => editPlaylist({operation:'remove',playlist_id:detail.source.id})}>Remove from library</button></>}</div>
      </div>
      <div className="mw-detail-messages">{renderEditor()}{sortLoading && <p role="status" className="music-empty">Loading all songs to sort…</p>}
      {detailError && <p role={detailRestricted?'status':'alert'} className={detailRestricted?'mw-caption':'music-error'}>{detailError}{!detailRestricted && <button className="mw-text-button" onClick={() => loadDetail(detail.source,detail.nextOffset ?? 0)}>Try again</button>}</p>}
      {detailRestricted && <div className="mw-actions"><button className="music-button primary" disabled={busy || !canPlay} onClick={() => playDetail()}>Play in Vellum</button><a className="music-button" href={'https://open.spotify.com/playlist/'+detail.source.id} target="_blank" rel="noopener noreferrer">Open in Spotify</a></div>}</div>
      {detailRestricted && /^spotify:playlist:[A-Za-z0-9]+$/.test(detail.source.uri || '') && <section className="music-playlist-embed" aria-label="Spotify playlist view"><p>Spotify playlist view. Use Play in Vellum above for your connected Vellum player.</p><iframe key={detail.source.uri} title={'Spotify playlist: '+detail.source.name} src={'https://open.spotify.com/embed/playlist/'+detail.source.uri.split(':')[2]+'?theme=0'} width="100%" height="500" decoding="async" allow="encrypted-media; fullscreen; picture-in-picture" sandbox="allow-scripts allow-same-origin allow-forms allow-popups"/></section>}
      {!detailRestricted && <><div className="music-track-head"><span>#</span><span>Title</span><span>Artist</span><span>Album</span><span>Time</span></div><div className="music-track-list">{sorted(detail.items,songOrder).map((item,index) => <div className="music-track-item" key={item.position ?? index}><button className={'music-track-row'+(item.uri && item.uri===track?.uri?' current':'')} aria-label={'Play '+item.name+(artists(item)?' by '+artists(item):'')} data-unavailable={!item.playable?'true':undefined} disabled={!canPlay || busy || !item.playable} onClick={() => playDetail(item)}>
        <span className="music-track-number">{(item.position ?? index)+1}</span><span className="music-track-title"><Artwork item={item}/><b>{item.name}</b></span><span className="music-track-artist">{artists(item) || 'Unavailable'}</span><span className="music-track-album">{item.album || (detail.source.kind==='album'?detail.source.name:'')}</span><span className="music-track-time">{item.duration_ms?time(item.duration_ms):'—'}</span>
      </button>{detail.source.editable && <button className="music-song-remove" aria-label={'Remove '+item.name+' from playlist'} title="Remove all occurrences from playlist" disabled={!editableAction || editBusy || !!pendingEdit || !item.playable} onClick={() => editPlaylist({operation:'remove_items',playlist_id:detail.source.id,uris:[item.uri]})}><Icon name="close"/></button>}</div>)}</div></>}
      {detailLoading && <p className="music-empty" role="status">Loading songs…</p>}{!detailLoading && !detailError && !detail.items.length && <p className="music-empty">No tracks were returned for this collection.</p>}{detail.nextOffset!==null && <button className="music-button music-load-more" disabled={detailLoading || sortLoading} onClick={() => loadDetail(detail.source,detail.nextOffset)}>Load more songs</button>}
    </section>;
    const libraryPanel=() => <section><div className="music-section-heading"><h2>{screen==='playlists'?'Playlists':'Your collection'}</h2><div className="mw-actions"><SortMenu label="Sort music collection" value={collectionOrder} options={collectionSorts} onChange={order => chooseSort(order)} disabled={loading || sortLoading || editBusy}/><button className="mw-icon-button" aria-label="Refresh music collection" disabled={loading || sortLoading} onClick={refreshLibrary}><Icon name="refresh"/></button><button className="mw-icon-button" aria-label={collectionView==='grid'?'List view':'Grid view'} onClick={() => setCollectionView(value => value==='grid'?'list':'grid')}><Icon name={collectionView==='grid'?'list':'grid'}/></button></div></div>
      <div className="music-library-tabs"><button aria-pressed={libraryTab==='playlists'} onClick={() => setLibraryTab('playlists')}>Playlists</button><button aria-pressed={libraryTab==='albums'} onClick={() => setLibraryTab('albums')}>Albums</button></div>
      {libraryError?<p className="music-error" role="alert">{libraryError}</p>:loading && !collection.length?<div className="mw-cover-grid mw-skeletons" role="status" aria-label="Loading music collection">{Array.from({length:5},(_,index)=><div key={index}/>)}</div>:<>
      {coverCards(sorted(collection,collectionOrder))}
      {liked && <button className="mw-liked music-liked-card" onClick={() => openCollection(liked)}><Icon name="heart"/><span><b>Liked Songs</b><small>{liked.total} songs</small></span></button>}
      {!loading && !collection.length && <p className="music-empty">No saved {libraryTab} were returned by Spotify.</p>}{nextOffset!==null && <button className="music-button" disabled={loading || sortLoading} onClick={() => loadLibrary(nextOffset)}>Load more collections</button>}</>}
    </section>;
    const sourcesPanel=() => <div className="mw-content"><header><h1>Sources</h1><p>Connect your music services. Vellum loads your playlists and plays through your own subscription.</p></header>
      <div className="mw-provider-list">{[['spotify','Spotify'],['apple','Apple Music']].map(([id,name]) => <section className="mw-provider-row" key={id}>
        <img className="mw-provider-logo" src={id==='spotify'?'assets/plugins/spotify.svg':asset('apple-music.png')} alt=""/><div><h2>{name}</h2><p>{id==='apple'?'Integration coming later.':connected?'Connected'+(spotify.account_name?' as '+spotify.account_name:'')+' · Your playlists and saved songs':expired?'Sign-in expired.':'Connect your Spotify account.'}</p><small>Playback uses your {name} subscription</small></div>
        <div className="mw-actions">{id==='apple'?<><button className="music-button" onClick={() => chooseProvider('apple')}>View Apple Music</button><span className="mw-source-tag">Coming later</span></>:<>{provider==='spotify' && connected?<span className="mw-source-tag">Active</span>:<button className="music-button" onClick={() => chooseProvider('spotify')}>Switch to Spotify</button>}<button className="music-button" aria-busy={loading} disabled={loading} onClick={() => {onRefreshConnection?.();refreshLibrary();}}>Sync now</button><button className="music-button" onClick={onReconnect}>{connected?'Manage connection':'Connect Spotify'}</button></>}</div>
      </section>)}</div><form className="mw-playlist-links" onSubmit={addPlaylistLinks}><label htmlFor="mw-playlist-links">Add Spotify playlist links</label><div><textarea id="mw-playlist-links" aria-label="Spotify playlist links" value={playlistLinks} onChange={event => setPlaylistLinks(event.target.value)} placeholder="Paste Spotify playlist links, separated by spaces or commas" maxLength="5000"/><button className="music-button" aria-busy={linkBusy} disabled={linkBusy || !playlistLinks.trim() || !local.catalog?.actions?.some(action => action.id==='spotify.playlists.link')}>Add playlists</button></div><small>Saved to this connection. Public song lists are used when Spotify’s API withholds tracks.</small></form><p className="mw-caption">You sign in with the provider. Vellum never sees your password.</p><button className="mw-text-button" onClick={() => chooseProvider('local')}>No streaming service? Switch to Local mode</button><button className="mw-text-button" onClick={() => navigate('transfer')}>Move a playlist to another service</button>
    </div>;
    const settingsPanel=() => <div className="mw-content mw-settings"><header><h1>Settings</h1><p>Playback, appearance and accounts.</p></header>
      <section><h2>Playback</h2><div className="mw-setting-group">
        <div className="mw-setting-row"><div><b>Audio quality</b><p>Managed by your playback source.</p></div><select aria-label="Audio quality" disabled title="Audio-quality control is not available"><option>Normal</option><option>High</option><option>Very high</option></select></div>
        <div className="mw-setting-row"><div><b>Crossfade</b><p>Blend the end of a song into the next.</p></div><input type="range" aria-label="Crossfade" min="0" max="12" value="0" disabled readOnly title="Crossfade is not available yet"/><small>0 s</small></div>
        <div className="mw-setting-row"><div><b>Gapless playback</b><p>Available when the playback source supports it.</p></div><button role="switch" aria-checked="false" aria-label="Gapless playback" className="mw-switch" disabled title="Gapless playback is managed by the source"><span/></button></div>
      </div></section>
      <section><h2>Appearance</h2><div className="mw-setting-group">
        <div className="mw-setting-row"><div><b>Match my service</b><p>Use {isApple?'Apple Music':'Spotify'}’s accent while it is active. Your Vellum background stays the same.</p></div><button role="switch" aria-checked={themeMatch} aria-label="Match my service" className={'mw-switch'+(themeMatch?' on':'')} onClick={() => setThemeMatch(value => !value)}><span/></button></div>
        <div className="mw-setting-row"><div><b>Theme</b><p>Accent used when matching is off. Local mode uses Midnight.</p></div><select aria-label="Music theme" disabled={themeMatch || isLocal} value={themeChoice} onChange={event => setThemeChoice(event.target.value)}>{['Midnight','Daylight','Forest','Ocean','Mono'].map(name => <option key={name}>{name}</option>)}</select></div>
      </div></section>
      <section><h2>Accounts and music</h2><div className="mw-setting-group"><div className="mw-setting-row"><div><b>Sources</b><p>Manage Spotify and Apple Music.</p></div><button className="music-button" onClick={() => navigate('sources')}>Manage</button></div><div className="mw-setting-row"><div><b>Local music folder</b><p>Choose a folder to import your audio files.</p></div><button className="music-button" disabled={local.busy || !local.available('file')} onClick={local.chooseFolder}>Choose folder</button></div></div></section>
    </div>;
    const sidebarCollections=displayCollections.filter(item=>isLocal || item.kind==='playlist');
    const providerPicker=(label='Music provider')=><div className="mw-provider-picker"><window.VellumUI.VSelect className="mw-provider-control" ariaLabel={label} value={provider} onValueChange={chooseProvider} sharedLayout options={[
      {value:'spotify',label:'Spotify',icon:'assets/plugins/spotify.svg'},
      {value:'apple',label:'Apple Music',icon:asset('apple-music.png'),sub:'Coming later'},
      {value:'local',label:'Local files',icon:asset('icons/music.svg')},
    ]}/></div>;

    const queueRows=isLocal?(local.state?.queue || []).slice((local.state?.index || 0)+1).map(id => local.entries.find(item => item.id===id)).filter(Boolean):upcoming;
    return <section className={'music-page mw-workspace'+(!footerVisible?' no-player':'')+(screen==='queue'?' showing-queue':'')+(!sidebarVisible?' sidebar-collapsed':'')} aria-label="Music" data-control-busy={String(controlBusy)} data-playback-available={String(canPlay)} aria-busy={controlBusy} data-ui-reference="music.page" data-variant="inset" data-collapsible="offcanvas" data-sidebar-state={sidebarVisible?'open':'closed'} data-music-theme={theme}>
      <input className="mw-sr-only" ref={local.audioInput} type="file" multiple accept=".mp3,.flac,.m4a,.aac,.ogg,.opus,.wav,.webm" aria-label="Choose local audio files" onChange={local.files}/>
      <input className="mw-sr-only" ref={local.folderInput} type="file" multiple webkitdirectory="" aria-label="Choose local music folder" onChange={local.files}/>
      <input className="mw-sr-only" ref={local.manifestInput} type="file" accept=".json" aria-label="Choose playlist manifest" onChange={local.importManifest}/>
      <aside className="mw-sidebar" id="mw-sidebar" aria-label="Music sidebar" inert={!sidebarVisible?'':undefined} aria-hidden={!sidebarVisible}>
        <div className="mw-sidebar-top"><span className="mw-sidebar-title">Music</span><button ref={sidebarHide} className="mw-icon-button" aria-label="Hide music sidebar" aria-expanded="true" aria-controls="mw-sidebar" onClick={()=>setSidebar(false)}><Icon name="panel"/></button></div>
        <div className="mw-sidebar-source">{providerPicker()}</div>
        <nav className="mw-nav" aria-label="Music navigation"><window.VellumUI.SharedRowBackground className="mw-nav-list" activeSelector='[aria-current="page"]' refreshKey={screen}>
          {[['home','Home','home'],['search','Search','search'],['playlists','Playlists','list']].map(([id,label,icon])=><button type="button" key={id} data-shared-row="" aria-current={screen===id?'page':undefined} onClick={()=>navigate(id)}><Icon name={icon}/><span>{label}</span></button>)}
        </window.VellumUI.SharedRowBackground></nav>
        <section className="mw-sidebar-playlists" aria-label="Music playlists"><div className="mw-sidebar-library-head"><h2>Playlists</h2><span>{sidebarCollections.length}</span></div>
          <window.VellumUI.SharedRowBackground className="mw-sidebar-playlist-list" activeSelector='[aria-current="page"]' refreshKey={screen+':'+(detail?.source.uri || local.selected || '')+':'+sidebarCollections.length}>
            {sidebarCollections.map(item=><button type="button" key={item.id} data-shared-row="" aria-current={(isLocal?local.selected===item.id:detail?.source.uri===item.uri)?'page':undefined} onClick={()=>{if(isLocal){local.setSelected(item.id);setScreen('home');}else openCollection(item);}}><Artwork item={item}/><span>{item.name}</span></button>)}
            {!sidebarCollections.length && <p>{isApple?'Apple Music playlists will appear when connected.':isLocal?'Your playlists will appear here.':connected?'No playlists loaded.':'Connect a service to see your playlists.'}</p>}
          </window.VellumUI.SharedRowBackground>
        </section>
        <nav className="mw-nav mw-sidebar-utilities" aria-label="Music preferences"><window.VellumUI.SharedRowBackground className="mw-nav-list" activeSelector='[aria-current="page"]' refreshKey={screen}>
          {[[isLocal?'add':'sources',isLocal?'Add music':'Sources','sources'],['settings','Settings','settings']].map(([id,label,icon])=><button type="button" key={id} data-shared-row="" aria-current={screen===id?'page':undefined} onClick={()=>navigate(id)}><Icon name={icon}/><span>{label}</span></button>)}
        </window.VellumUI.SharedRowBackground></nav>
      </aside>
      {sidebarVisible && <button type="button" className="mw-sidebar-backdrop" aria-label="Close music sidebar" onClick={()=>setSidebar(false)}/>}
      <main ref={pageRef} className={'mw-main'+(detail && !isLocal && !isApple?' has-detail':'')} tabIndex="-1">
        {!sidebarVisible && <div className="mw-sidebar-reopen"><button ref={sidebarToggle} className="mw-icon-button" aria-label="Show music sidebar" aria-expanded="false" aria-controls="mw-sidebar" title="Show music sidebar" onClick={()=>setSidebar(true)}><Icon name="panel"/></button></div>}
        <div className="mw-mobile-heading"><button className="mw-text-button" aria-label="Back to Vellum" onClick={onCloseMusic}><Icon name="chevron"/>Vellum</button>{providerPicker('Mobile music provider')}</div>
        {isLocal && local.error && <p role="alert" className="music-error mw-status">{local.error}</p>}
        {isLocal && local.notice && <p role="status" className="mw-caption mw-status">{local.notice}</p>}
        {isLocal && local.busy && <p role="status" className="mw-caption mw-status">Updating your library…</p>}
        {provider==='spotify' && (error || notice) && <p className="music-error mw-status" role="alert">{error || notice}</p>}
        {provider==='spotify' && (catalogError || libraryError) && screen!=='settings' && screen!=='sources' && <p className="music-error mw-status" role="alert">{catalogError || libraryError}</p>}
        {!navigator.onLine && <div className="mw-banner mw-status">You’re offline. Imported local files remain available.</div>}
        {screen==='settings'?settingsPanel():screen==='sources'?sourcesPanel():screen==='ask'?<div className="mw-content mw-ask"><header><h1>Ask Vellum</h1><p>Find the right music for what you’re doing.</p></header><div className="mw-chat-prompt"><Icon name="ask"/><h2>What would you like to listen to?</h2><p>Describe a mood, a moment or an artist. Continue with Vellum in your existing chat.</p><div className="mw-actions">{['Something for a late shift','Help me focus','Music for a road trip'].map(text => <button className="music-button" key={text} onClick={() => setAskDraft(text)}>{text}</button>)}</div></div><form onSubmit={event => {event.preventDefault();if(onAskMusic)onAskMusic(askDraft);else{onCloseMusic?.();window.dispatchEvent(new CustomEvent('vellum:music-draft',{detail:{text:askDraft}}));}}}><input aria-label="Ask Vellum about music" value={askDraft} onChange={event => setAskDraft(event.target.value)} placeholder="Ask about your music…"/><button className="music-button primary" disabled={!askDraft.trim() || !(onAskMusic || onCloseMusic)}>Continue in chat</button></form></div>
        :screen==='transfer'?<div className="mw-content"><header><h1>Move a playlist</h1><p>Copy a song list between your streaming services.</p></header><div className="mw-transfer-grid"><section><p>From</p><h2>Spotify</h2><select aria-label="Playlist to transfer" disabled={!collection.length}>{collection.map(item => <option key={item.id}>{item.name}</option>)}</select></section><Icon name="next"/><section><p>To</p><h2>Apple Music</h2><p>Integration coming later.</p></section></div><div className="mw-banner">Playlist transfer will be available after Apple Music is connected. Playback on the destination service requires its subscription.</div><button className="music-button primary" disabled>Move playlist</button><button className="mw-text-button" onClick={() => navigate('sources')}>Back to Sources</button></div>
        :screen==='save-local'?<div className="mw-content"><header><h1>Save playlists to Local</h1><p>Keep your song lists. Match the songs to audio files you own.</p></header><div className="mw-banner"><b>What is saved</b><p>Playlist names, song order, titles, artists, albums and source IDs. Audio is never copied.</p></div>{collection.map(item => <label className="mw-save-row" key={item.id}><input type="checkbox" checked={saveSelection.includes(item.id)} onChange={event => setSaveSelection(rows => event.target.checked?[...rows,item.id]:rows.filter(id => id!==item.id))}/><Artwork item={item}/><b>{item.name}</b></label>)}{nextOffset!==null && <button className="music-button" disabled={loading} onClick={() => loadLibrary(nextOffset)}>Load more collections</button>}<button className="music-button primary" disabled={!saveSelection.length || local.busy || !local.available('playlist')} onClick={savePlaylists}>Save {saveSelection.length} playlists</button>{local.error && <p role="alert" className="music-error">{local.error}</p>}</div>
        :screen==='queue'?<div className="mw-now-playing"><section className="mw-now-main"><button className="mw-icon-button mw-now-close" aria-label="Close now playing" onClick={() => navigate('home')}><Icon name="chevron"/></button><p className="mw-label">Now playing</p><Artwork item={now || {name:'No song selected',kind:'track'}} className="mw-now-cover"/><h1>{now?.name || 'Choose a song'}</h1><p>{now?artists(now):isApple?'Apple Music integration coming later':'Play something from your library'}</p>{seek()}{transport(true)}</section><section className="mw-now-queue"><div className="mw-now-tabs"><button aria-pressed={!queueExpanded} onClick={() => setQueueExpanded(false)}>Queue</button><button aria-pressed={queueExpanded} onClick={() => setQueueExpanded(true)}>Lyrics</button></div>{queueExpanded?<p className="music-empty">Lyrics are not available for this recording.</p>:<><p className="mw-label">Now playing</p><div className="mw-queue-current"><Artwork item={now || {name:'No song selected'}}/><span><b>{now?.name || 'Nothing playing'}</b><small>{now?artists(now):''}</small></span></div><p className="mw-label">Up next</p>{queueRows.map((item,index) => <button className="music-queue-item" key={item.id || item.uri || index} disabled={!canPlay || controlBusy} onClick={() => isLocal?local.play(item,local.entries.filter(row => (local.state?.queue || []).includes(row.id))):run({action:'play',uris:queueRows.slice(index).slice(0,50).map(row => row.uri)})}><Artwork item={{...item,name:item.name || item.title}}/><span><b>{item.name || item.title}</b><small>{item.artist || artists(item)}</small></span><small>{item.duration_ms?time(item.duration_ms):''}</small></button>)}{!queueRows.length && <p className="music-empty">Your queue is empty.</p>}</>}</section></div>
        :isLocal?(screen==='search'?<div className="mw-content">{searchForm()}<h1>Search your music</h1>{localRows.map((item,index) => <button className="mw-local-song" key={item.id} disabled={!item.available || local.busy} onClick={() => local.play(item,localRows)}>{item.artwork_url?<Artwork item={{...item,name:item.title,kind:'track'}}/>:<span className="mw-song-index" aria-hidden="true">{index+1}</span>}<span><b>{item.title}</b><small>{item.artist}</small></span><small>{item.available?'File':'Audio needed'}</small></button>)}{!localRows.length && <p className="music-empty">No local songs match this search.</p>}</div>:<window.VellumUI.LocalMusicContent local={local} view={localView==='playlists'?'home':localView} onNavigate={navigate} Icon={Icon} Artwork={Artwork}/>)
        :lapsed || expired?<div className="mw-content mw-account-state"><Icon name="music"/><h1>{expired?'Sign-in expired':'Your Spotify subscription ended'}</h1><p>{expired?'Sign in again to continue streaming. Your local music is still available.':'Playback is paused. Keep your playlists and match their songs to files you own.'}</p><div className="mw-actions">{expired?<button className="music-button primary" onClick={onReconnect}>Sign in again</button>:<button className="music-button primary" onClick={() => navigate('save-local')}>Save playlists to Local</button>}<a className="music-button" href="https://www.spotify.com/premium/" target="_blank" rel="noopener noreferrer">Resubscribe</a><button className="music-button" onClick={() => navigate('sources')}>Switch service</button><button className="mw-text-button" onClick={() => chooseProvider('local')}>Open Local</button></div><div className="mw-banner">Downloads made inside a streaming app remain tied to its subscription. Vellum cannot unlock them. Local mode plays your own audio files.</div></div>
        :detail && !isApple?renderDetail()
        :screen==='search' || search!==null?<div className="mw-content music-search-results">{searchForm()}<div className="music-library-tabs" aria-label="Search type">{[['track','Songs'],['album','Albums'],['artist','Artists'],['playlist','Playlists']].map(([id,label]) => <button key={id} aria-pressed={searchKind===id} onClick={() => {setSearchKind(id);find(null,id);}}>{label}</button>)}</div><h1>Search</h1>{searching?<p className="music-empty" role="status">Searching Spotify…</p>:searchError?<p className="music-error" role="alert">{searchError}</p>:search?.items.length?<><div className="mw-search-top"><button className="mw-top-result" onClick={() => ['album','playlist','artist'].includes(search.items[0].kind)?openCollection(search.items[0]):playItem(search.items[0],search.items)}><Artwork item={search.items[0]}/><h2>{search.items[0].name}</h2><p>{search.items[0].kind} · {artists(search.items[0])}</p></button><section><h2>{searchKind==='track'?'Songs':'Results'}</h2>{search.items.slice(0,4).map(item => <button className="music-result mw-result-row" key={item.uri || item.id} disabled={busy} onClick={() => ['album','playlist','artist'].includes(item.kind)?openCollection(item):playItem(item,search.items)}><Artwork item={item}/><span><b>{item.name}</b><small>{artists(item)}</small></span><small>{item.duration_ms?time(item.duration_ms):''}</small></button>)}</section></div>{['playlist','album','artist'].includes(searchKind)?coverCards(search.items):search.items.slice(4).map(item => <button className="music-result mw-result-row" key={item.uri} disabled={busy || !item.playable} onClick={() => playItem(item,search.items)}><Artwork item={item}/><span><b>{item.name}</b><small>{artists(item)}</small></span><small>{time(item.duration_ms)}</small></button>)}</>:<p className="music-empty">{search!==null && query.trim()?'No results returned. Try another search.':'Type a song or artist to see suggestions, or press Enter to search.'}</p>}</div>
        :<div className="mw-content mw-home">{searchForm()}<h1>Your music</h1>
          {isApple?<><div className="mw-banner"><b>Apple Music</b><p>Apple Music subscription playback is not connected. The integration will be added later.</p><button className="music-button" onClick={() => chooseProvider('local')}>Open local library</button></div><section><h2>Jump back in</h2><div className="mw-empty-library"><Icon name="album"/><p>Your Apple Music albums and playlists will appear here when the integration is ready.</p></div></section><section><h2>Recently played</h2><p className="music-empty">No Apple Music playback history yet.</p></section></>
          :<>{!connected && <div className="mw-banner"><b>Connect Spotify</b><p>Listen through your subscription, or use your own music in Local mode.</p><button className="music-button primary" onClick={onReconnect}>Connect Spotify</button><button className="mw-text-button" onClick={() => chooseProvider('local')}>Use my own music</button></div>}
          {connected && !playback.ready && <div className="mw-playback-status"><span>{playback.message || 'Enable Spotify playback inside Vellum.'}</span><button className="music-button" onClick={enable}>Enable playback</button></div>}
          {screen==='playlists'?libraryPanel():<><section className="mw-recent-tracks"><h2>Recently played</h2>{recent.length?recent.slice(0,6).map(item => <button className="mw-result-row" key={item.uri} onClick={() => playItem({...item,kind:'track',playable:true})}><Artwork item={item}/><span><b>{item.name}</b><small>{artists(item)}</small></span><small>{time(item.duration_ms)}</small></button>):<p className="music-empty">Songs you play in this session will appear here.</p>}</section><section className="mw-home-playlists"><div className="mw-section-heading"><h2>Your playlists</h2><button className="mw-text-button" onClick={() => {setLibraryTab('playlists');navigate('playlists');}}>Browse library</button></div>{playlists.length?coverCards(playlists,10):<p className="music-empty">{loading?'Loading your playlists…':'Your playlists will appear here.'}</p>}</section>
          <section className="mw-home-albums"><div className="mw-section-heading"><h2>Saved albums</h2><button className="mw-text-button" onClick={() => {setLibraryTab('albums');navigate('playlists');}}>Browse albums</button></div>{albums.length?coverCards(albums,10):<p className="music-empty">Your saved albums will appear here.</p>}</section>
</>}</>}
        </div>}
      </main>
      {footerVisible && <footer className="mw-player" aria-label="Music player">
        <button className="mw-player-info" aria-label="Open now playing" onClick={() => {setScreen('queue');setQueueExpanded(false);}}><Artwork item={now || {name:'No song selected',kind:'track'}}/><span><b>{now?.name || 'Choose a song'}</b><small>{now?artists(now):isApple?'Apple Music · Coming later':isLocal?'Your local library':'Spotify'}</small></span></button><button className="mw-icon-button mw-player-heart" aria-label="Favorite current song" disabled title="Favorites are not available yet"><Icon name="heart"/></button>
        <div className="mw-player-center">{transport()}{seek()}</div><div className="mw-player-right"><button className="mw-icon-button" aria-label="Open music queue" onClick={() => {setScreen('queue');setQueueExpanded(false);}}><Icon name="queue"/></button><button className="mw-icon-button" aria-label={level===0?'Unmute music':'Mute music'} disabled={!canPlay || controlBusy || level==null} onClick={() => {if(isLocal)control('set_volume',{volume:level===0 ? .7 : 0});else volumeToggle();}}><Icon name={level===0?'mute':'volume'}/></button><Range label="Music volume" value={level ?? 0} max={100} disabled={!canPlay || controlBusy || level==null} onCommit={volume_percent => control('set_volume',isLocal?{volume:volume_percent/100}:{volume_percent})}/><output className="mw-sr-only">{level==null?'Unknown volume':level+'%'}</output></div>
      </footer>}
      <nav className="mw-mobile-tabs" aria-label="Mobile music navigation">{[['home','Home','home'],['search','Search','search'],['playlists','Library','list'],[isLocal?'add':'sources','Sources','sources']].map(([id,label,icon]) => <button key={id} aria-current={screen===id?'page':undefined} onClick={() => navigate(id)}><Icon name={icon}/>{label}</button>)}</nav>
    </section>;
  }
  window.VellumUI=window.VellumUI || {};
  window.VellumUI.MusicPage=MusicPage;
})();
