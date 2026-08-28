(function () {
  const {useState, useEffect, useRef, useMemo} = React;
  const titleCase = value => String(value || 'Unavailable').replace(/_/g, ' ').toLowerCase().replace(/^./, char => char.toUpperCase());
  const author = book => (book.authors || []).join(', ') || 'Author unavailable';
  const graphicsBook = book => ({...book, cover_url:window.VellumApi.books.coverUrl(book.cover_url)});

  function Cover({book}) {
    const [failed, setFailed] = useState(false);
    const url = window.VellumApi.books.coverUrl(book.cover_url);
    useEffect(() => setFailed(false), [url]);
    return <div className="bk-cover">{url && !failed
      ? <img src={url} alt={`Cover of ${book.title}`} onError={() => setFailed(true)} referrerPolicy="no-referrer"/>
      : <span>Cover unavailable</span>}</div>;
  }

  function Scene({books, book, selectedId, onSelect, onOpen}) {
    const host = useRef(null), scene = useRef(null), callbacks = useRef({onSelect, onOpen});
    callbacks.current = {onSelect, onOpen};
    const [ready, setReady] = useState(false);
    const signature = JSON.stringify((book ? [book] : books).map(item => [item.id, item.title, item.authors, item.cover_url]));
    useEffect(() => {
      setReady(false);
      let disposed = false;
      const start = () => {
        if (disposed || scene.current || !window.VellumBooksGraphics) return;
        try {
          scene.current = book
            ? window.VellumBooksGraphics.createBook(host.current, {book:graphicsBook(book)})
            : window.VellumBooksGraphics.createShelf(host.current, {
              books:books.map(graphicsBook), selectedId,
              onSelect:id => callbacks.current.onSelect?.(id), onOpen:id => callbacks.current.onOpen?.(id),
            });
          setReady(!!host.current.querySelector('canvas'));
        } catch (_) { setReady(false); }
      };
      window.addEventListener('vellum:books-graphics-ready', start);
      start();
      return () => { disposed = true; window.removeEventListener('vellum:books-graphics-ready', start); scene.current?.dispose(); scene.current = null; };
    }, [signature, !!book]);
    useEffect(() => { scene.current?.select?.(selectedId); }, [selectedId]);
    return <div className={'bk-scene' + (book ? ' bk-book-scene' : '')} data-render-state={ready ? 'ready' : 'fallback'}>
      <div className="bk-canvas" ref={host}/>
      {!ready && (book ? <Cover book={book}/> : <div className="bk-spines">{books.map(item => <button key={item.id} onClick={() => onOpen(item.id)}><span>{author(item)}</span><strong>{item.title}</strong></button>)}</div>)}
    </div>;
  }

  function ImportDialog({version, busy, onImport, onClose, icons}) {
    const [file, setFile] = useState(null), [rights, setRights] = useState(false), [scan, setScan] = useState(false), [localOnly, setLocalOnly] = useState(true);
    const dialog = useRef(null);
    useEffect(() => { dialog.current.showModal(); return () => dialog.current?.close(); }, []);
    const submit = async event => {
      event.preventDefault();
      if (await onImport(file, {rightsAttestationVersion:version, scanApproved:scan, localOnly})) onClose();
    };
    return <dialog ref={dialog} className="bk-dialog" aria-labelledby="bk-import-title" onCancel={event => {if (busy) event.preventDefault(); else onClose();}}>
      <form onSubmit={submit}>
        <header><h2 id="bk-import-title">Import EPUB</h2><button type="button" className="bk-icon" title="Close import" aria-label="Close import" onClick={onClose} disabled={!!busy}><icons.Close size={18}/></button></header>
        <label className="bk-file">Book file<input type="file" accept=".epub,application/epub+zip" onChange={event => setFile(event.target.files[0] || null)} disabled={!!busy}/></label>
        <label><input type="checkbox" checked={rights} onChange={event => setRights(event.target.checked)} disabled={!!busy}/>I have permission to import and process this book.</label>
        <label><input type="checkbox" checked={scan} onChange={event => setScan(event.target.checked)} disabled={!!busy}/>Allow Vellum to run the local malware scan.</label>
        <label><input type="checkbox" checked={localOnly} onChange={event => setLocalOnly(event.target.checked)} disabled={!!busy}/>Local only</label>
        <footer><button type="button" className="bk-button" onClick={onClose} disabled={!!busy}>Cancel</button><button className="bk-button primary" disabled={!file || !rights || !scan || !version || !!busy}><icons.Upload size={15}/>{busy || 'Import EPUB'}</button></footer>
      </form>
    </dialog>;
  }

  function Confirmation({title, onCancel, onConfirm}) {
    const dialog = useRef(null);
    useEffect(() => { dialog.current.showModal(); return () => dialog.current?.close(); }, []);
    return <dialog ref={dialog} className="bk-dialog" aria-labelledby="bk-confirm-title" onCancel={onCancel}>
      <h2 id="bk-confirm-title">{title}</h2>
      <footer><button className="bk-button" autoFocus onClick={onCancel}>Cancel</button><button className="bk-button primary" onClick={onConfirm}>Confirm</button></footer>
    </dialog>;
  }

  function BooksView({agentProps, DefaultAgentView, icons}) {
    const controller = useMemo(() => window.VellumBooks.createController(window.VellumApi.books), []);
    const [state, setState] = useState(controller.getState), [surface, setSurface] = useState('library');
    const [selected, setSelected] = useState(''), [query, setQuery] = useState(''), [importOpen, setImportOpen] = useState(false);
    const [draft, setDraft] = useState(null), [confirmation, setConfirmation] = useState(null);
    useEffect(() => { const unsubscribe = controller.subscribe(setState); controller.load(); return () => {unsubscribe(); controller.destroy();}; }, [controller]);
    const visible = state.items.filter(book => (book.title + ' ' + author(book)).toLowerCase().includes(query.toLowerCase()));
    const selectedBook = visible.find(book => book.id === selected) || visible[0];
    const detail = state.detail;
    const open = id => {setSelected(id); controller.open(id);};
    const attach = book => {
      setDraft({text:`About the book "${book.title}" by ${author(book)}: `});
      setSurface('chat');
    };
    const act = async () => {
      const pending = confirmation;
      setConfirmation(null);
      await controller[pending.action](pending.id);
    };
    const back = () => {controller.close(); setConfirmation(null);};
    return <section className="bk-root" aria-label="Books Agent">
      <header className="bk-header">
        <h1>Books Agent</h1>
        <nav aria-label="Books sections">
          <button className={surface === 'library' ? 'active' : ''} onClick={() => setSurface('library')}>Library</button>
          <button className={surface === 'chat' ? 'active' : ''} onClick={() => setSurface('chat')}>Chat</button>
        </nav>
        <button className="bk-icon" title="Books Agent settings" aria-label="Books Agent settings" onClick={agentProps.onSettings}><icons.Settings size={17}/></button>
      </header>
      <div className="bk-chat" hidden={surface !== 'chat'}><DefaultAgentView {...agentProps} bookDraft={draft} onBookDraftConsumed={() => setDraft(null)}/></div>
      {surface === 'library' && <div className="bk-library">
        <div className="bk-toolbar">
          {detail || state.detailLoading ? <button className="bk-button" onClick={back}><icons.Back size={16}/>All books</button> : <label className="bk-search"><icons.Search size={15}/><input aria-label="Search installed books" placeholder="Search this page" value={query} onChange={event => setQuery(event.target.value)}/></label>}
          <span className="bk-total">{state.total} {state.total === 1 ? 'book' : 'books'}</span>
          <button className="bk-icon" title="Refresh books" aria-label="Refresh books" onClick={() => controller.load()} disabled={state.loading || !!state.busy}><icons.Refresh size={16}/></button>
          <button className="bk-button" onClick={() => setImportOpen(true)} disabled={!!state.busy}><icons.Upload size={16}/>Import EPUB</button>
        </div>
        {state.error && <div className="bk-error" role="alert">{state.error}<button className="bk-button" onClick={() => controller.load()}>Retry refresh</button></div>}
        {state.busy && <div className="bk-status" role="status">{state.busy}</div>}
        {state.detailLoading ? <div className="bk-empty" role="status">Loading book...</div> : detail ? <article className="bk-detail">
          <div className="bk-detail-hero">
            <Scene book={detail}/>
            <div className="bk-detail-copy">
              <p className="bk-status-label">{titleCase(detail.state)}</p><h2>{detail.title}</h2><p className="bk-author">{author(detail)}</p>
              <dl><div><dt>Source policy</dt><dd>{detail.local_only ? 'Local only' : 'Profile policy'}</dd></div><div><dt>Book skill</dt><dd>{titleCase(detail.skill_status)}</dd></div><div><dt>Sections</dt><dd>{detail.section_count ?? 0}</dd></div></dl>
              <div className="bk-actions">
                <button className="bk-button primary" onClick={() => attach(detail)}><icons.Chat size={16}/>Add to Chat</button>
                {detail.can_process && <button className="bk-button" disabled={!!state.busy} onClick={() => setConfirmation({action:'process',id:detail.id,title:'Process this EPUB locally?'})}><icons.Book size={16}/>Process EPUB</button>}
                {detail.can_compile && <button className="bk-button" disabled={!!state.busy} onClick={() => setConfirmation({action:'compile',id:detail.id,title:'Build Book skill knowledge?'})}><icons.Book size={16}/>Build Book skill</button>}
              </div>
            </div>
          </div>
          <section className="bk-sections"><h3>Source sections</h3>{detail.sections?.length ? <ol>{detail.sections.map(section => <li key={section.id}><span>{section.title || 'Untitled section'}</span><small>{section.block_count} blocks</small></li>)}</ol> : <p>No processed sections available.</p>}</section>
        </article> : state.loading && !state.items.length ? <div className="bk-empty" role="status">Loading books...</div> : !visible.length ? <div className="bk-empty"><icons.Book size={38}/><h2>{state.total ? 'No matching books' : 'No installed books'}</h2>{!state.total && <button className="bk-button" onClick={() => setImportOpen(true)}><icons.Upload size={16}/>Import EPUB</button>}</div> : <>
          <div className="bk-shelf"><Scene books={visible} selectedId={selectedBook.id} onSelect={setSelected} onOpen={open}/></div>
          <div className="bk-cover-rail" aria-label="Installed book collection">{visible.map(book => <button key={book.id} className={book.id === selectedBook.id ? 'selected' : ''} onFocus={() => setSelected(book.id)} onClick={() => open(book.id)} aria-label={`Open ${book.title}`}><Cover book={book}/><span><strong>{book.title}</strong><small>{author(book)}</small><small>{titleCase(book.state)}</small></span></button>)}</div>
          <footer className="bk-pagination"><button className="bk-icon" aria-label="Previous books" title="Previous books" disabled={!state.offset || state.loading} onClick={() => controller.load(Math.max(0,state.offset-state.limit))}><icons.Back size={18}/></button><span>{state.offset+1}-{Math.min(state.offset+state.items.length,state.total)} of {state.total}</span><button className="bk-icon" aria-label="Next books" title="Next books" disabled={state.offset+state.items.length>=state.total || state.loading} onClick={() => controller.load(state.offset+state.limit)}><icons.Next size={18}/></button></footer>
        </>}
      </div>}
      {importOpen && <ImportDialog version={state.rightsAttestationVersion} busy={state.busy} onImport={controller.importEpub} onClose={() => setImportOpen(false)} icons={icons}/>}
      {confirmation && <Confirmation title={confirmation.title} onCancel={() => setConfirmation(null)} onConfirm={act}/>}
    </section>;
  }
  window.VellumUI = {...window.VellumUI, BooksView};
})();
