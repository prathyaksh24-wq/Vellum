/* Memory: what Vellum has learned about you, and how that changes over time.
   Reads come from /api/memory/*; every write goes through onMemoryAction (App
   Actions), except the conversational "Ask or update" and selection-based
   "Don't mention this again", whose routes plan the edits and dispatch the same
   App Actions on the backend. */
(function () {
  const {useState, useEffect, useLayoutEffect, useRef, useCallback} = React;
  const api = () => window.VellumApi.settings;

  const paths = {
    book: 'M12 6.5C9.5 4.8 6.5 4.3 3 5v13c3.5-.7 6.5-.2 9 1.5 2.5-1.7 5.5-2.2 9-1.5V5c-3.5-.7-6.5-.2-9 1.5Z M12 6.5V19.5',
    gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z',
    send: 'M12 19V5 M5 12l7-7 7 7',
    back: 'M15 6l-6 6 6 6',
    close: 'M6 6l12 12 M18 6 6 18',
    copy: 'M9 9h11v11H9Z M5 15H4V4h11v1',
    info: 'M12 8h.01 M11 12h1v5h1 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
    refresh: 'M20 7v5h-5 M4 17v-5h5 M6 7a7 7 0 0 1 12 1 M18 17A7 7 0 0 1 6 16',
    download: 'M12 4v12 M7 11l5 5 5-5 M4 20h16',
    trash: 'M4 7h16 M10 11v6 M14 11v6 M6 7l1 13h10l1-13 M9 7V4h6v3',
  };
  const Icon = ({name, size=16}) => <svg className="mp-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {name === 'more' ? [5, 12, 19].map(x => <circle key={x} cx={x} cy="12" r="1.6" fill="currentColor" stroke="none"/>) : <path d={paths[name]}/>}
  </svg>;

  const ORIGINS = {stated:'Stated', inferred:'Inferred', imported:'Imported'};
  const DROP_REASONS = {
    duplicate:'already in memory', sensitive:'sensitive details', instruction_like:'read like instructions to an AI',
    unparsed:'could not be read', links_removed:'had links removed (the rest was kept)',
  };

  function parseTime(value) {
    if (!value) return null;
    const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) || !/T/.test(value) ? value : value + 'Z');
    return Number.isNaN(date.getTime()) ? null : date;
  }
  function relativeTime(value, now = Date.now()) {
    const date = parseTime(value);
    if (!date) return '';
    const minutes = Math.round((now - date.getTime()) / 60000);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return minutes + 'm ago';
    const hours = Math.round(minutes / 60);
    if (hours < 24) return hours + 'h ago';
    const days = Math.round(hours / 24);
    if (days < 30) return days + 'd ago';
    return date.toLocaleDateString(undefined, {month:'short', day:'numeric', year:'numeric'});
  }
  function shortDate(value) {
    const date = parseTime(value);
    return date ? date.toLocaleDateString(undefined, {month:'short', day:'numeric'}) : '';
  }

  // The model streams Markdown: "### Title" sections, then "Dive Deeper" bullets.
  function parseSummaryMarkdown(text) {
    const sections = [], dive = [];
    let current = null;
    for (const raw of String(text || '').split(/\r?\n/)) {
      const line = raw.trim();
      const heading = line.match(/^#{1,4}\s+(.+)$/);
      if (heading) {
        current = {title: heading[1].replace(/\*+/g, '').trim(), body: ''};
        sections.push(current);
        continue;
      }
      if (!line) continue;
      if (current && /^dive deeper$/i.test(current.title)) {
        const item = line.replace(/^([-*•]|↳|\d+\.)\s*/, '').trim();
        if (item) dive.push(item);
        continue;
      }
      if (!current) { current = {title: '', body: ''}; sections.push(current); }
      current.body += (current.body ? ' ' : '') + line;
    }
    return {sections: sections.filter(section => !/^dive deeper$/i.test(section.title)), dive_deeper: dive};
  }

  async function downloadExport() {
    const {blob, filename} = await api().memoryExport();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = filename;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function useDismiss(open, onClose, ref) {
    useEffect(() => {
      if (!open) return;
      const down = event => { if (ref.current && !ref.current.contains(event.target)) onClose(); };
      const key = event => { if (event.key === 'Escape') onClose(); };
      document.addEventListener('mousedown', down);
      document.addEventListener('keydown', key);
      return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key); };
    }, [open, onClose, ref]);
  }

  function Menu({label, icon, items}) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const close = useCallback(() => setOpen(false), []);
    useDismiss(open, close, ref);
    return <div className="mp-menu" ref={ref}>
      <button type="button" className="mp-icon-button" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}><Icon name={icon}/></button>
      {open && <div className="mp-menu-list" role="menu">
        {items.filter(Boolean).map(item => <button key={item.label} type="button" role="menuitem" className={'mp-menu-item' + (item.danger ? ' is-danger' : '')}
          onClick={() => { setOpen(false); item.onSelect(); }}>{item.icon && <Icon name={item.icon}/>}{item.label}</button>)}
      </div>}
    </div>;
  }

  function Dialog({title, onClose, children, footer, wide}) {
    const ref = useRef(null);
    useDismiss(true, onClose, ref);
    return <div className="mp-dialog-scrim">
      <div className={'mp-dialog' + (wide ? ' is-wide' : '')} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="mp-dialog-head"><h2>{title}</h2><button type="button" className="mp-icon-button" aria-label="Close" onClick={onClose}><Icon name="close"/></button></div>
        <div className="mp-dialog-body">{children}</div>
        {footer && <div className="mp-dialog-foot">{footer}</div>}
      </div>
    </div>;
  }

  // "Ask or update" / "Tell Vellum what to change": one conversational edit box.
  function AskBar({placeholder, onMemoryAction, onChanged}) {
    const [text, setText] = useState('');
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState('');
    const submit = async event => {
      event.preventDefault();
      const value = text.trim();
      if (!value || busy) return;
      setBusy(true); setError('');
      try {
        const reply = await api().memoryAsk(value);
        setResult(reply); setText('');
        if (reply.applied && reply.applied.length) onChanged();
      } catch (err) {
        setError(err.message || 'Vellum could not update memory. Try again.');
      } finally { setBusy(false); }
    };
    const confirmDelete = async item => {
      const receipt = await onMemoryAction('memory.entry.delete', {memory_id:item.memory_id});
      if (receipt && ['applied', 'confirmation_required'].includes(receipt.status)) {
        setResult(current => current && {...current, needs_confirmation:current.needs_confirmation.filter(entry => entry.memory_id !== item.memory_id)});
      }
    };
    const verb = {add:'Added', update:'Updated', suppress:'Stopped using'};
    return <div className="mp-ask">
      {(result || error) && <div className="mp-ask-result" role="status">
        {error && <p className="mp-error">{error}</p>}
        {result && result.reply && <p>{result.reply}</p>}
        {result && (result.applied || []).map((entry, index) => <p key={index} className="mp-ask-applied"><b>{verb[entry.op] || 'Changed'}</b> {entry.memory && (entry.memory.title || entry.memory.text)}</p>)}
        {result && (result.needs_confirmation || []).map(item => <div key={item.memory_id} className="mp-ask-confirm">
          <span>Delete “{item.text}”?</span>
          <button type="button" className="btn" onClick={() => confirmDelete(item)}>Delete</button>
        </div>)}
        <button type="button" className="mp-text-button" onClick={() => { setResult(null); setError(''); }}>Dismiss</button>
      </div>}
      <form className="mp-ask-form" onSubmit={submit}>
        <input aria-label={placeholder} placeholder={placeholder} value={text} disabled={busy} onChange={event => setText(event.target.value)}/>
        <button type="submit" className="mp-send" aria-label="Send" disabled={busy || !text.trim()}><Icon name="send"/></button>
      </form>
    </div>;
  }

  function Generating() {
    return <div className="mp-generating" role="status"><Icon name="book" size={28}/><span className="mp-shimmer">Generating</span></div>;
  }

  function SummaryBody({summary, onOpenChat}) {
    return <React.Fragment>
      {(summary.sections || []).map((section, index) => <section key={index} className="mp-summary-section">
        {section.title && <h3>{section.title}</h3>}
        {section.body && <p>{section.body}</p>}
      </section>)}
      {(summary.dive_deeper || []).length > 0 && <section className="mp-dive">
        <h3>Dive deeper</h3>
        {summary.dive_deeper.map(prompt => <button key={prompt} type="button" className="mp-dive-link" onClick={() => onOpenChat && onOpenChat(prompt)}><span aria-hidden="true">↳</span><span>{prompt}</span></button>)}
      </section>}
    </React.Fragment>;
  }

  function AboutYou({onMemoryAction, onOpenChat, onDeleteAll}) {
    const [phase, setPhase] = useState('loading');
    const [summary, setSummary] = useState(null);
    const [draft, setDraft] = useState('');
    const [error, setError] = useState('');
    const [chip, setChip] = useState(null);
    const [notice, setNotice] = useState('');
    const [aboutOpen, setAboutOpen] = useState(false);
    const [, tick] = useState(0);
    const controller = useRef(null), article = useRef(null), chipRef = useRef(null);

    const load = useCallback(async force => {
      if (controller.current) controller.current.abort();
      const abort = new AbortController();
      controller.current = abort;
      setError(''); setDraft(''); setPhase(force ? 'generating' : 'loading');
      try {
        const final = await api().memoryAboutYouStream({force, signal:abort.signal, onEvent:(name, data) => {
          if (abort.signal.aborted) return;
          if (name === 'status') setPhase('generating');
          else if (name === 'delta') setDraft(current => current + (data.text || ''));
          else if (name === 'error') setError(data.message || 'The summary could not be generated.');
        }});
        if (abort.signal.aborted) return;
        if (final) { setSummary(final); setPhase('ready'); }
        else setPhase('error');
      } catch (err) {
        if (abort.signal.aborted) return;
        setError(err.message || 'The summary could not be loaded.');
        setPhase('error');
      }
    }, []);
    useEffect(() => { load(false); return () => controller.current && controller.current.abort(); }, [load]);
    useEffect(() => { const timer = setInterval(() => tick(n => n + 1), 60000); return () => clearInterval(timer); }, []);

    const closeChip = useCallback(() => setChip(null), []);
    useDismiss(!!chip, closeChip, chipRef);
    // Keep the chip inside the summary column, whatever its current width.
    useLayoutEffect(() => {
      if (!chip || !chipRef.current || !article.current) return;
      const room = article.current.clientWidth - chipRef.current.offsetWidth;
      chipRef.current.style.left = Math.max(0, Math.min(chip.left, room)) + 'px';
    });
    const select = () => {
      const selection = window.getSelection && window.getSelection();
      const text = selection ? selection.toString().trim() : '';
      if (!text || !article.current || !selection.rangeCount || !article.current.contains(selection.anchorNode)) return;
      const range = selection.getRangeAt(0).getBoundingClientRect(), box = article.current.getBoundingClientRect();
      setChip({text: text.slice(0, 500), mode:'menu', draft:'', busy:false,
        top: Math.max(0, range.top - box.top - 44), left: Math.max(0, range.left - box.left)});
    };
    const afterChange = message => { setChip(null); setNotice(message); window.getSelection && window.getSelection().removeAllRanges(); load(false); };
    const correct = async event => {
      event.preventDefault();
      if (!chip.draft.trim()) return;
      setChip({...chip, busy:true});
      const receipt = await onMemoryAction('memory.correction.create', {correction:chip.draft.trim(), selection:chip.text});
      // The App Action receipt already shows its own confirmation toast.
      if (receipt && receipt.status === 'applied') afterChange('');
      else setChip(current => current && {...current, busy:false});
    };
    const suppress = async () => {
      setChip({...chip, busy:true});
      try {
        await api().memorySuppress({selection:chip.text});
        afterChange('Vellum won’t bring that up again.');
      } catch (err) { setChip(null); setNotice(err.message || 'That could not be changed.'); }
    };

    const showing = phase === 'ready' && summary ? summary : draft ? parseSummaryMarkdown(draft) : null;
    return <div className="mp-about">
      <header className="mp-about-head">
        <div><h2>About you</h2>{summary && summary.updated_at && phase === 'ready' && <span className="mp-updated">Updated {relativeTime(summary.updated_at)}</span>}</div>
        <Menu label="Summary options" icon="more" items={[
          {label:'About memory', icon:'info', onSelect:() => setAboutOpen(true)},
          {label:'Refresh', icon:'refresh', onSelect:() => load(true)},
          {label:'Export', icon:'download', onSelect:() => downloadExport().catch(err => setNotice(err.message))},
          {label:'Delete and turn off memory', icon:'trash', danger:true, onSelect:onDeleteAll},
        ]}/>
      </header>
      {notice && <p className="mp-notice" role="status">{notice}</p>}
      <article className="mp-summary" ref={article} onMouseUp={select}>
        {showing ? <SummaryBody summary={showing} onOpenChat={onOpenChat}/> : phase === 'error' ? null : <Generating/>}
        {phase === 'error' && <div className="mp-error-block"><p className="mp-error">{error || 'The summary could not be loaded.'}</p><button type="button" className="btn" onClick={() => load(false)}>Try again</button></div>}
        {phase === 'ready' && summary && summary.generated_by === 'fallback' && <p className="mp-footnote">Written without the local model, which was unavailable. Refresh to try again.</p>}
        {chip && <div className="mp-chip" ref={chipRef} style={{top:chip.top, left:chip.left}}>
          {chip.mode === 'menu' && <React.Fragment>
            <span className="mp-chip-label">Make a correction</span>
            <button type="button" disabled={chip.busy} onClick={() => setChip({...chip, mode:'correct'})}>Correct</button>
            <button type="button" disabled={chip.busy} onClick={suppress}>Don’t mention this again</button>
          </React.Fragment>}
          {chip.mode === 'correct' && <form className="mp-chip-form" onSubmit={correct}>
            <input autoFocus aria-label="Correction" placeholder="What should it say instead?" value={chip.draft} disabled={chip.busy} onChange={event => setChip({...chip, draft:event.target.value})}/>
            <button type="submit" disabled={chip.busy || !chip.draft.trim()}>Save</button>
          </form>}
        </div>}
      </article>
      <AskBar placeholder="Ask or update" onMemoryAction={onMemoryAction} onChanged={() => load(false)}/>
      {aboutOpen && <Dialog title="About memory" onClose={() => setAboutOpen(false)}>
        <p>Vellum writes this summary from what you’ve told it, what it has inferred from your chats, and what you’ve imported. It stays on this device and is written by your local model.</p>
        <p>Select any text to correct it or tell Vellum not to bring it up again. Things you tell Vellum directly are kept; guesses are archived after 30 days and removed after 90 if automatic management is on.</p>
      </Dialog>}
    </div>;
  }

  function TopicItem({item, onMemoryAction}) {
    const [editing, setEditing] = useState(null);
    const archived = item.status === 'archived';
    const run = (actionId, args) => onMemoryAction(actionId, args);
    const save = async event => {
      event.preventDefault();
      if (!editing.trim() || editing.trim() === item.text) { setEditing(null); return; }
      const receipt = await onMemoryAction('memory.entry.update', {memory_id:item.id, text:editing.trim()});
      if (receipt && receipt.status === 'applied') setEditing(null);
    };
    return <li className={'mp-item' + (item.suppressed || archived ? ' is-dim' : '') + (item.kind === 'correction' ? ' is-correction' : '')}>
      {editing === null ? <p className="mp-item-text">{item.text}</p>
        : <form className="mp-item-edit" onSubmit={save}><textarea aria-label="Edit memory" value={editing} onChange={event => setEditing(event.target.value)}/><div><button type="submit" className="btn">Save</button><button type="button" className="mp-text-button" onClick={() => setEditing(null)}>Cancel</button></div></form>}
      <div className="mp-item-meta">
        <span>{ORIGINS[item.origin] || 'Inferred'}</span>
        {item.kind === 'correction' && <span>Correction</span>}
        {item.created_at && <span>{shortDate(item.created_at)}</span>}
        {!!item.pinned && <span>Pinned</span>}
        {!!item.suppressed && <span className="mp-flag">Not used</span>}
        {archived && <span className="mp-flag">Archived</span>}
      </div>
      {editing === null && <div className="mp-item-actions">
        <button type="button" className="mp-text-button" onClick={() => setEditing(item.text)}>Edit</button>
        <button type="button" className="mp-text-button" onClick={() => run('memory.entry.pin', {memory_id:item.id, pinned:!item.pinned})}>{item.pinned ? 'Unpin' : 'Pin'}</button>
        <button type="button" className="mp-text-button" onClick={() => run('memory.entry.suppress', {memory_id:item.id, suppressed:!item.suppressed})}>{item.suppressed ? 'Use again' : 'Stop using'}</button>
        {!archived && <button type="button" className="mp-text-button" onClick={() => run('memory.entry.archive', {memory_id:item.id})}>Archive</button>}
        <button type="button" className="mp-text-button is-danger" onClick={() => run('memory.entry.delete', {memory_id:item.id})}>Delete</button>
      </div>}
    </li>;
  }

  function Topics({onMemoryAction, revision, onChanged}) {
    const [topics, setTopics] = useState(null);
    const [error, setError] = useState('');
    const [open, setOpen] = useState('');
    const [adding, setAdding] = useState('');
    useEffect(() => {
      let live = true;
      api().memoryTopics().then(body => { if (live) { setTopics(body.topics || []); setError(''); } })
        .catch(err => { if (live) setError(err.message || 'Topics could not be loaded.'); });
      return () => { live = false; };
    }, [revision]);
    const add = async event => {
      event.preventDefault();
      if (!adding.trim()) return;
      const receipt = await onMemoryAction('memory.entry.create', {text:adding.trim(), kind:'manual', scope:'global'});
      if (receipt && receipt.status === 'applied') setAdding('');
    };
    const topic = open && topics && topics.find(card => card.topic === open);
    return <div className="mp-topics">
      {error && <p className="mp-error">{error}</p>}
      {!topics && !error && <p className="mp-muted" role="status">Loading topics…</p>}
      {topic ? <section className="mp-topic-detail">
        <button type="button" className="mp-text-button mp-back" onClick={() => setOpen('')}><Icon name="back"/>All topics</button>
        <h2>{topic.topic}</h2>
        <ul className="mp-items">{topic.items.map(item => <TopicItem key={item.id} item={item} onMemoryAction={onMemoryAction}/>)}</ul>
        <form className="mp-add" onSubmit={add}>
          <input aria-label="Add a memory" placeholder="Add something Vellum should remember" value={adding} onChange={event => setAdding(event.target.value)}/>
          <button type="submit" className="btn" disabled={!adding.trim()}>Add</button>
        </form>
      </section>
      : topics && (topics.length ? <div className="mp-topic-grid">{topics.map(card => <button key={card.topic} type="button" className="mp-topic-card" onClick={() => setOpen(card.topic)}>
          <b>{card.topic}</b>
          <span className="mp-topic-count">{card.count} {card.count === 1 ? 'memory' : 'memories'}{card.last_learned ? ' · learned ' + shortDate(card.last_learned) : ''}</span>
          <span className="mp-origins">{Object.keys(card.origins || {}).map(origin => <span key={origin} className="mp-origin">{ORIGINS[origin] || origin} {card.origins[origin]}</span>)}</span>
        </button>)}</div>
        : <p className="mp-empty">No topics yet. As you chat, what Vellum learns is grouped here.</p>)}
      <AskBar placeholder="Tell Vellum what to change" onMemoryAction={onMemoryAction} onChanged={onChanged}/>
    </div>;
  }

  function Sparkline({series}) {
    const values = series.map(point => point.known);
    if (values.length < 2) return null;
    const max = Math.max(1, ...values), width = 300, height = 64;
    const points = values.map((value, index) => [index / (values.length - 1) * width, height - 4 - value / max * (height - 8)]);
    return <figure className="mp-spark">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={`Known facts rose from ${values[0]} to ${values[values.length - 1]}`}>
        <polyline points={points.map(point => point.join(',')).join(' ')} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke"/>
      </svg>
      <figcaption><span>{shortDate(series[0].day)}</span><span>{shortDate(series[series.length - 1].day)}</span></figcaption>
    </figure>;
  }

  function Growth({revision}) {
    const [growth, setGrowth] = useState(null);
    const [error, setError] = useState('');
    useEffect(() => {
      let live = true;
      api().memoryGrowth().then(body => { if (live) { setGrowth(body); setError(''); } })
        .catch(err => { if (live) setError(err.message || 'Growth could not be loaded.'); });
      return () => { live = false; };
    }, [revision]);
    if (error) return <p className="mp-error">{error}</p>;
    if (!growth) return <p className="mp-muted" role="status">Loading…</p>;
    if (!growth.day_number) return <div className="mp-empty-state"><h2>Vellum is just getting to know you.</h2><p>As you chat, what it learns shows up here day by day: what you’ve told it, what it has picked up, and what you’ve corrected.</p></div>;
    const counts = growth.counts || {};
    return <div className="mp-growth">
      <header><h2>Day {growth.day_number}</h2><span className="mp-updated">Since {shortDate(growth.first_day)}</span></header>
      <dl className="mp-stats">
        <div><dt>Known</dt><dd>{counts.known || 0}</dd></div>
        <div><dt>Topics</dt><dd>{(counts.topics || []).length}</dd></div>
        <div><dt>Recalled</dt><dd>{counts.recalls || 0}</dd></div>
      </dl>
      <Sparkline series={growth.series || []}/>
      <section>
        <h3>Milestones</h3>
        {(growth.milestones || []).length ? <ol className="mp-milestones">{growth.milestones.map((milestone, index) => <li key={index}><span className="mp-day">Day {milestone.day_number}</span><span>{milestone.text}</span></li>)}</ol>
          : <p className="mp-muted">Milestones appear as Vellum learns more.</p>}
      </section>
    </div>;
  }

  function MemoryPage({onMemoryAction, onOpenChat, onOpenSettings}) {
    const [tab, setTab] = useState('about');
    const [revision, setRevision] = useState(0);
    const [deleting, setDeleting] = useState(null);
    const refresh = useCallback(() => setRevision(n => n + 1), []);
    useEffect(() => {
      window.addEventListener('vellum:memory-changed', refresh);
      return () => window.removeEventListener('vellum:memory-changed', refresh);
    }, [refresh]);
    const act = useCallback(async (actionId, args, options) => {
      if (!onMemoryAction) return null;
      const receipt = await onMemoryAction(actionId, args, options);
      if (receipt && receipt.status === 'applied') refresh();
      return receipt;
    }, [onMemoryAction, refresh]);
    const startDeleteAll = async () => {
      try {
        const body = await api().memoryTopics();
        const ids = (body.topics || []).flatMap(card => card.items.map(item => item.id));
        setDeleting({ids, busy:false, error:''});
      } catch (err) { setDeleting({ids:[], busy:false, error:err.message}); }
    };
    const deleteAll = async () => {
      setDeleting(current => ({...current, busy:true, error:''}));
      const off = await act('memory.settings.update', {patch:{memory_enabled:false}}, {confirmedFromUi:true});
      if (!off || off.status !== 'applied') { setDeleting(current => ({...current, busy:false, error:'Memory could not be turned off.'})); return; }
      for (const id of deleting.ids) await act('memory.entry.delete', {memory_id:id}, {confirmedFromUi:true});
      setDeleting(null); refresh();
    };
    const tabs = [['about', 'About you'], ['topics', 'Topics'], ['growth', 'Growth']];
    return <section className="mp-page" aria-label="Memory">
      <header className="mp-head">
        <h1>Memory</h1>
        <nav className="mp-tabs" role="tablist" aria-label="Memory views">{tabs.map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}</button>)}</nav>
        <Menu label="Memory settings" icon="gear" items={[
          onOpenSettings && {label:'Memory settings', onSelect:onOpenSettings},
          {label:'Consolidate memories now', onSelect:() => act('memory.dreaming.run', {})},
          {label:'Index past chats for search', onSelect:() => act('memory.conversations.import', {})},
        ]}/>
      </header>
      <div className="mp-body">
        {tab === 'about' && <AboutYou onMemoryAction={act} onOpenChat={onOpenChat} onDeleteAll={startDeleteAll}/>}
        {tab === 'topics' && <Topics onMemoryAction={act} revision={revision} onChanged={refresh}/>}
        {tab === 'growth' && <Growth revision={revision}/>}
      </div>
      {deleting && <Dialog title="Delete and turn off memory" onClose={() => !deleting.busy && setDeleting(null)} footer={<React.Fragment>
        <button type="button" className="btn" disabled={deleting.busy} onClick={() => setDeleting(null)}>Cancel</button>
        <button type="button" className="btn mp-danger" disabled={deleting.busy} onClick={deleteAll}>{deleting.busy ? 'Deleting…' : 'Delete and turn off'}</button>
      </React.Fragment>}>
        <p>This turns memory off and permanently deletes {deleting.ids.length} saved {deleting.ids.length === 1 ? 'memory' : 'memories'}. It can’t be undone.</p>
        {deleting.error && <p className="mp-error">{deleting.error}</p>}
      </Dialog>}
    </section>;
  }

  // -- Settings → Personalization → Memory -----------------------------------
  const SETTING_ROWS = [
    ['memory_enabled', 'Enable memory', 'Let Vellum personalize answers from your chats, files and connected apps.', 'When this is off, Vellum neither recalls nor saves memories. What it already knows stays until you delete it.', true],
    ['reference_history_enabled', 'Reference chat history', 'Let Vellum search your past chats when they help with a question.', 'Past chats are searched on this device only, and a turn that uses them shows “Searched past chats”.', true],
    ['save_new_memories', 'Generate memory from chats', 'Let Vellum save what it learns about you as you chat.', 'Things you state directly are saved right away and show “Saved to memory” with an Undo link. Guesses are marked Inferred.', true],
    ['include_sensitive', 'Include sensitive topics', 'Like health conditions or religious beliefs.', 'When off, sensitive details are skipped when Vellum saves or imports memories.', false],
    ['auto_archive_enabled', 'Automatically manage memory', 'Archives guesses after 30 days, removes them after 90; keeps what you told Vellum.', 'Before removing, Vellum distils what still matters into a short digest. Pinned memories and corrections are never removed.', true],
  ];

  function SettingRow({title, description, more, children}) {
    const [open, setOpen] = useState(false);
    return <div className="set-row mp-set-row">
      <div className="mp-set-copy">{title}
        <span className="sr-sub">{description} {more && <button type="button" className="mp-learn" aria-expanded={open} onClick={() => setOpen(!open)}>Learn more</button>}</span>
        {open && <span className="sr-sub mp-set-more">{more}</span>}
      </div>
      <span className="sr-end">{children}</span>
    </div>;
  }

  function MemorySettings({settings, onMemorySettings, onMemoryAction, onOpenMemory}) {
    const values = settings || {};
    const [importing, setImporting] = useState(false);
    const [exportError, setExportError] = useState('');
    const toggle = (key, next) => onMemorySettings && onMemorySettings({[key]: next});
    return <div className="mp-settings">
      {SETTING_ROWS.map(([key, title, description, more, fallback]) => {
        const on = values[key] !== undefined ? !!values[key] : fallback;
        return <SettingRow key={key} title={title} description={description} more={more}>
          <div className={'sw' + (on ? ' on' : '')} role="switch" tabIndex="0" aria-label={title} aria-checked={on}
            onClick={() => toggle(key, !on)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(key, !on); } }}/>
        </SettingRow>;
      })}
      <SettingRow title="Your memory" description="See, correct, or delete what Vellum knows about you.">
        <button type="button" className="btn" onClick={onOpenMemory}>Open</button>
      </SettingRow>
      <SettingRow title="Import memory from other AI providers" description="Bring what another assistant knows about you into Vellum.">
        <button type="button" className="btn" onClick={() => setImporting(true)}>Start import</button>
      </SettingRow>
      <SettingRow title="Export memory" description={exportError || 'Download your memory as a .zip of Markdown files.'}>
        <button type="button" className="btn" onClick={() => { setExportError(''); downloadExport().catch(err => setExportError(err.message)); }}>Export</button>
      </SettingRow>
      {importing && <ImportDialog onMemoryAction={onMemoryAction} onClose={() => setImporting(false)}/>}
    </div>;
  }

  function ImportDialog({onMemoryAction, onClose}) {
    const [prompt, setPrompt] = useState('');
    const [text, setText] = useState('');
    const [copied, setCopied] = useState(false);
    const [plan, setPlan] = useState(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [saved, setSaved] = useState(null);
    useEffect(() => {
      api().memoryImportPrompt().then(body => setPrompt(body.prompt || '')).catch(err => setError(err.message || 'The prompt could not be loaded.'));
    }, []);
    const copy = async () => {
      try { await navigator.clipboard.writeText(prompt); setCopied(true); setTimeout(() => setCopied(false), 1600); }
      catch (_) { setError('Copy failed. Select the prompt and copy it manually.'); }
    };
    const review = async () => {
      setBusy(true); setError('');
      try { setPlan(await api().memoryImportPlan(text)); }
      catch (err) { setError(err.message || 'That text could not be read.'); }
      finally { setBusy(false); }
    };
    const apply = async () => {
      setBusy(true); setError('');
      const receipt = onMemoryAction ? await onMemoryAction('memory.import.apply', {items:plan.items}, {confirmedFromUi:true}) : null;
      setBusy(false);
      if (receipt && receipt.status === 'applied') setSaved((receipt.result && receipt.result.saved) ?? plan.count);
      else setError((receipt && receipt.message) || 'The import could not be applied.');
    };
    const skipped = plan ? Object.entries(plan.dropped || {}).filter(([, count]) => count > 0) : [];
    const footer = saved !== null ? <button type="button" className="btn" onClick={onClose}>Done</button>
      : plan ? <React.Fragment>
        <button type="button" className="btn" disabled={busy} onClick={() => setPlan(null)}>Back</button>
        <button type="button" className="btn mp-strong" disabled={busy || !plan.count} onClick={apply}>{busy ? 'Adding…' : `Add ${plan.count} to memory`}</button>
      </React.Fragment>
      : <React.Fragment>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn mp-strong" disabled={busy || !text.trim()} onClick={review}>{busy ? 'Reading…' : 'Add to memory'}</button>
      </React.Fragment>;
    return <Dialog title="Import memory to Vellum" onClose={onClose} footer={footer} wide>
      {saved !== null ? <p role="status">Added {saved} {saved === 1 ? 'memory' : 'memories'}. They’re marked Imported in Topics.</p>
      : plan ? <div className="mp-import-review">
        <p><b>{plan.count}</b> {plan.count === 1 ? 'memory' : 'memories'} will be added.</p>
        {plan.items.length > 0 && <ul className="mp-import-items">{plan.items.slice(0, 12).map((item, index) => <li key={index}><span className="mp-origin">{item.category}</span>{item.text}</li>)}{plan.items.length > 12 && <li className="mp-muted">and {plan.items.length - 12} more</li>}</ul>}
        {skipped.length > 0 && <div className="mp-import-skipped"><p>Skipped</p><ul>{skipped.map(([reason, count]) => <li key={reason}>{count} {DROP_REASONS[reason] || reason}</li>)}</ul></div>}
        {plan.truncated && <p className="mp-muted">Only the first 64 KB were read.</p>}
      </div>
      : <ol className="mp-import-steps">
        <li><p>Copy this prompt into a chat with your other AI provider</p>
          <div className="mp-prompt"><pre>{prompt || 'Loading…'}</pre><button type="button" className="btn" disabled={!prompt} onClick={copy}><Icon name="copy"/>{copied ? 'Copied' : 'Copy'}</button></div></li>
        <li><p>Paste the results below to add them to Vellum’s memory</p>
          <textarea aria-label="Paste your memory details" placeholder="Paste your memory details here" value={text} onChange={event => setText(event.target.value)}/></li>
      </ol>}
      {error && <p className="mp-error">{error}</p>}
    </Dialog>;
  }

  window.VellumUI = window.VellumUI || {};
  Object.assign(window.VellumUI, {MemoryPage, MemorySettings, parseSummaryMarkdown, relativeTime});
})();
