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

  function ReferenceShelf({books, loading, rightsVersion, onImportFile, onImportUrl, onProgress, onRemove, onTheme, onRefresh, onClose, onSelect, openBookId}) {
    const host = useRef(null), mounted = useRef(null);
    const props = {books:books.map(graphicsBook), loading, rightsVersion, onImportFile, onImportUrl, onProgress, onRemove, onTheme, onRefresh, onClose, onSelect, openBookId};
    const latest = useRef(props); latest.current = props;
    const [ready, setReady] = useState(!!window.VellumBookshelf);
    useEffect(() => {
      const mount = () => {
        if (!mounted.current && window.VellumBookshelf) {mounted.current = window.VellumBookshelf.mount(host.current, latest.current); setReady(true);}
      };
      window.addEventListener('vellum:bookshelf-ready', mount); mount();
      return () => {window.removeEventListener('vellum:bookshelf-ready', mount); mounted.current?.unmount(); mounted.current=null;};
    }, []);
    useEffect(() => {mounted.current?.update(props);});
    return <><div ref={host} className="bk-reference-host"/>{!ready && <p role="status">Loading bookshelf…</p>}</>;
  }

  function BookUpload({value, onChange, onError, disabled}) {
    const host = useRef(null), mounted = useRef(null);
    const props = {
      value, onValueChange:items => {
        if (disabled) return;
        const valid = items.filter(item => /\.epub$/i.test(item.name.trim()));
        if (valid.length !== items.length) onError('Choose an EPUB file (.epub).');
        else onError('');
        onChange(valid);
      },
      accept:'.epub,application/epub+zip', multiple:false, maxFiles:1,
      maxFileSize:64 * 1024 * 1024, disabled,
      onFilesRejected:(_files, reason) => onError(reason === 'too-large' ? 'The EPUB exceeds the 64 MB import limit.' : 'Import one EPUB at a time.'),
    };
    const latest = useRef(props);
    latest.current = props;
    const [ready, setReady] = useState(!!window.VellumBookUpload);
    useEffect(() => {
      const mount = () => {
        if (!mounted.current && window.VellumBookUpload) {
          mounted.current = window.VellumBookUpload.mount(host.current, latest.current);
          setReady(true);
        }
      };
      window.addEventListener('vellum:book-upload-ready', mount);
      mount();
      return () => {window.removeEventListener('vellum:book-upload-ready', mount); mounted.current?.unmount(); mounted.current = null;};
    }, []);
    useEffect(() => {mounted.current?.update(props);});
    return <><div className="bk-upload" ref={host} inert={disabled ? '' : undefined}/>{!ready && <p role="status">Loading file upload...</p>}</>;
  }

  function ImportDialog({version, busy, error='', onImport, onClose, icons, initialFile=null}) {
    const [files, setFiles] = useState(() => initialFile ? [{id:'initial', name:initialFile.name, size:initialFile.size, kind:'file', file:initialFile}] : []);
    const [uploadError, setUploadError] = useState(''), [submitting, setSubmitting] = useState(false);
    const rights = true, scan = true;
    const [localOnly, setLocalOnly] = useState(true);
    const file = files[0]?.file;
    const dialog = useRef(null);
    useEffect(() => { dialog.current.showModal(); return () => dialog.current?.close(); }, []);
    const submit = async event => {
      event.preventDefault();
      if (!file || !rights || !scan || !version || busy || submitting) return;
      setSubmitting(true);
      setFiles(current => current.map(item => ({...item, status:'uploading'})));
      try {
        if (await onImport(file, {rightsAttestationVersion:version, scanApproved:scan, localOnly})) onClose();
        else setFiles(current => current.map(item => ({...item, status:'failed'})));
      } catch (_) {
        setUploadError('The EPUB could not be imported. Try again.');
        setFiles(current => current.map(item => ({...item, status:'failed'})));
      } finally {setSubmitting(false);}
    };
    return <dialog ref={dialog} className="bk-dialog" aria-labelledby="bk-import-title" onCancel={event => {if (busy) event.preventDefault(); else onClose();}}>
      <form onSubmit={submit}>
        <header><h2 id="bk-import-title">Import EPUB</h2><button type="button" className="bk-icon" title="Close import" aria-label="Close import" onClick={onClose} disabled={!!busy}><icons.Close size={18}/></button></header>
        <BookUpload value={files} onChange={setFiles} onError={setUploadError} disabled={!!busy || submitting}/>
        <p className="bk-upload-help">Choose an EPUB up to 64 MB. Select Import EPUB below to scan and process it.</p>
        {uploadError && <div className="bk-error" role="alert">{uploadError}</div>}
        {error && <div className="bk-error" role="alert">{error}</div>}
        <label><input type="checkbox" checked={localOnly} onChange={event => setLocalOnly(event.target.checked)} disabled={!!busy}/>Local only</label>
        <footer><button type="button" className="bk-button" onClick={onClose} disabled={!!busy}>Cancel</button><button className="bk-button primary" disabled={!file || !rights || !scan || !version || !!busy}><icons.Upload size={15}/>{busy || 'Import EPUB'}</button></footer>
      </form>
    </dialog>;
  }

  function Confirmation({title, description, confirmLabel='Confirm', onCancel, onConfirm}) {
    const dialog = useRef(null);
    useEffect(() => { dialog.current.showModal(); return () => dialog.current?.close(); }, []);
    return <dialog ref={dialog} className="bk-dialog" aria-labelledby="bk-confirm-title" onCancel={onCancel}>
      <h2 id="bk-confirm-title">{title}</h2>
      {description && <p>{description}</p>}
      <footer><button className="bk-button" autoFocus onClick={onCancel}>Cancel</button><button className="bk-button primary" onClick={onConfirm}>{confirmLabel}</button></footer>
    </dialog>;
  }

  function BooksView({agentProps, DefaultAgentView, icons}) {
    const actionHandlers = useRef({onAction:agentProps.onKnowledgeAction, onReceipt:agentProps.onAppActionReceipt});
    actionHandlers.current = {onAction:agentProps.onKnowledgeAction, onReceipt:agentProps.onAppActionReceipt};
    const controller = useMemo(() => window.VellumBooks.createController(window.VellumApi.books, {
      onAction: (...args) => actionHandlers.current.onAction && actionHandlers.current.onAction(...args),
      onReceipt: receipt => actionHandlers.current.onReceipt && actionHandlers.current.onReceipt(receipt),
    }), []);
    const [state, setState] = useState(controller.getState), [surface, setSurface] = useState('library');
    const [selected, setSelected] = useState(''), [query, setQuery] = useState(''), [importOpen, setImportOpen] = useState(false);
    const [draft, setDraft] = useState(null), [confirmation, setConfirmation] = useState(null), [readRequest, setReadRequest] = useState('');
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
      const applied = await controller[pending.action](pending.id);
      if (applied && pending.action === 'remove') {setSelected('');setReadRequest('');}
    };
    const back = () => {controller.close(); setConfirmation(null);};
    return <section className="bk-root" aria-label="Books Agent">
      <header className="bk-header">
        <h1>Books Agent</h1>
        <nav aria-label="Books sections">
          <button className={surface === 'library' ? 'active' : ''} onClick={() => setSurface('library')}>Library</button>
          <button className={surface === 'chat' ? 'active' : ''} onClick={() => setSurface('chat')}>Chat</button>
        </nav>
      </header>
      <div className="bk-chat" hidden={surface !== 'chat'}><DefaultAgentView {...agentProps} bookDraft={draft} onBookDraftConsumed={() => setDraft(null)}/></div>
      {surface === 'library' && <div className="bk-library">
        <div className="bk-toolbar">
          {detail || state.detailLoading ? <button className="bk-button" onClick={back}><icons.Back size={16}/>All books</button> : <label className="bk-search"><icons.Search size={15}/><input aria-label="Search installed books" placeholder="Search this page" value={query} onChange={event => setQuery(event.target.value)}/></label>}
          <span className="bk-total">{state.total} {state.total === 1 ? 'book' : 'books'}</span>
          <button className="bk-icon" title="Refresh books" aria-label="Refresh books" onClick={() => controller.load()} disabled={state.loading || !!state.busy}><icons.Refresh size={16}/></button>

        </div>
        {state.error && <div className="bk-error" role="alert">{state.error}<button className="bk-button" onClick={() => controller.load()}>Retry refresh</button></div>}
        {state.busy && <div className="bk-status" role="status">{state.busy}</div>}
        {state.detailLoading ? <div className="bk-empty" role="status">Loading book...</div> : detail ? <article className="bk-detail">
          <div className="bk-detail-hero">
            <Cover book={detail}/>
            <div className="bk-detail-copy">
              <p className="bk-status-label">{titleCase(detail.state)}</p><h2>{detail.title}</h2><p className="bk-author">{author(detail)}</p>
              <dl><div><dt>Source policy</dt><dd>{detail.local_only ? 'Local only' : 'Profile policy'}</dd></div><div><dt>Book skill</dt><dd>{titleCase(detail.skill_status)}</dd></div><div><dt>Sections</dt><dd>{detail.section_count ?? 0}</dd></div></dl>
              {detail.quality_outcome === 'OCR_REQUIRED' && <p role="status">Imported. Image-only pages require local OCR before this Book skill can be verified.</p>}
              {detail.quality_outcome && detail.quality_outcome !== 'PASS' && detail.quality_outcome !== 'OCR_REQUIRED' && <p role="status">Book skill quality checks: {titleCase(detail.quality_outcome)}. {detail.quality_findings?.map(titleCase).join('; ')}{detail.can_process ? '. Process EPUB to reassess this book.' : ''}</p>}
              <div className="bk-actions">
                {detail.can_read && <button className="bk-button primary" onClick={() => {setReadRequest(detail.id); controller.close();}}>Read EPUB</button>}
                <button className="bk-button primary" disabled={detail.quality_outcome === 'OCR_REQUIRED'} title={detail.quality_outcome === 'OCR_REQUIRED' ? 'Image-only pages need validated OCR before this Book can be used in chat.' : undefined} onClick={() => attach(detail)}><icons.Chat size={16}/>Add to Chat</button>
                {detail.can_process && <button className="bk-button" disabled={!!state.busy} onClick={() => setConfirmation({action:'process',id:detail.id,title:'Process this EPUB locally?'})}><icons.Book size={16}/>Process EPUB</button>}
                {detail.can_compile && <button className="bk-button" disabled={!!state.busy} onClick={() => setConfirmation({action:'compile',id:detail.id,title:'Build Book skill knowledge?'})}><icons.Book size={16}/>Build Book skill</button>}
                <button className="bk-button" disabled={!!state.busy} onClick={() => setConfirmation({action:'remove',id:detail.id,title:`Remove “${detail.title}” from your shelf?`,description:'The local source and reading progress stay saved. Import this book again to add it back.'})}>Remove from shelf</button>
              </div>
            </div>
          </div>
          <section className="bk-sections"><h3>Source sections</h3>{detail.sections?.length ? <ol>{detail.sections.map(section => <li key={section.id}><span>{section.title || 'Untitled section'}</span><small>{section.block_count} blocks</small></li>)}</ol> : <p>No processed sections available.</p>}</section>
        </article> : <>
          <ReferenceShelf books={visible} loading={state.loading} rightsVersion={state.rightsAttestationVersion} onSelect={setSelected} openBookId={readRequest} onClose={() => setReadRequest('')} onTheme={agentProps.onTheme} onRefresh={() => controller.load(0)} onProgress={controller.saveProgress}
            onRemove={async id => {if(!await controller.remove(id)) throw new Error(controller.getState().error || 'The book could not be removed.');setSelected('');setReadRequest('');}}
            onImportFile={async (file,title,author,cover,consent) => {if(!await controller.importFile(file,{...consent,title,author,cover})) throw new Error(controller.getState().error || 'Import failed.');return {title:controller.getState().lastBookResult?.book?.title || title || file.name,alreadyPresent:!!controller.getState().lastBookResult?.already_present};}}
            onImportUrl={async (url,consent) => {if(!await controller.importUrl(url,consent)) throw new Error(controller.getState().error || 'Import failed.');return {title:controller.getState().lastBookResult?.book?.title || 'Imported book'};}}/>
          <footer className="bk-pagination"><button className="bk-icon" aria-label="Previous books" title="Previous books" disabled={!state.offset || state.loading} onClick={() => controller.load(Math.max(0,state.offset-state.limit))}><icons.Back size={18}/></button><span>{state.total ? state.offset+1 : 0}-{Math.min(state.offset+state.items.length,state.total)} of {state.total}</span><button className="bk-icon" aria-label="Next books" title="Next books" disabled={state.offset+state.items.length>=state.total || state.loading} onClick={() => controller.load(state.offset+state.limit)}><icons.Next size={18}/></button></footer>
        </>}
      </div>}
      {importOpen && <ImportDialog version={state.rightsAttestationVersion} busy={state.busy} error={state.error} onImport={controller.importEpub} onClose={() => setImportOpen(false)} icons={icons}/>}
      {confirmation && <Confirmation title={confirmation.title} description={confirmation.description} confirmLabel={confirmation.action === 'remove' ? 'Remove from shelf' : 'Confirm'} onCancel={() => setConfirmation(null)} onConfirm={act}/>}
    </section>;
  }
  window.VellumUI = {...window.VellumUI, BooksView, BooksImportDialog:ImportDialog};
})();
