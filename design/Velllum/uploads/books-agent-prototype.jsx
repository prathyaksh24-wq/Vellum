/*
 * THROWAWAY PROTOTYPE: three collection layouts inside the Books Agent.
 * Enable with ?view=agent&agent=books&booksPrototype=1&variant=A.
 */

var BOOKS_PROTOTYPE_BOOKS = [
  {
    id: 'meditations',
    title: 'Meditations',
    author: 'Marcus Aurelius',
    cover: 'https://covers.openlibrary.org/b/isbn/9780140449334-L.jpg',
    year: 'c. 180',
    progress: 62,
    availability: 'Reading available',
    skill: 'Ready',
    collection: 'Philosophy',
    tags: ['attention', 'judgment', 'resilience'],
    location: 'Book IV, paragraph 3',
    excerpt: 'A reflection on separating the mind\'s judgments from events outside its control, and returning attention to the work immediately at hand.',
    relevance: 'You returned to this section three times while thinking about attention and reacting less quickly.',
  },
  {
    id: 'naval',
    title: 'The Almanack of Naval Ravikant',
    author: 'Eric Jorgenson',
    cover: 'https://covers.openlibrary.org/b/isbn/9781544514215-L.jpg',
    year: '2020',
    progress: 100,
    availability: 'Knowledge available',
    skill: 'Ready',
    collection: 'Philosophy',
    tags: ['wealth', 'leverage', 'happiness'],
    location: 'Happiness is learned',
    excerpt: 'The chapter treats happiness as a skill shaped by habits, interpretation, and the reduction of unnecessary desire.',
    relevance: 'This book has influenced several of your questions about work, independence, and peace of mind.',
  },
  {
    id: 'mans-search',
    title: "Man's Search for Meaning",
    author: 'Viktor E. Frankl',
    cover: 'https://covers.openlibrary.org/b/isbn/9780807014271-L.jpg',
    year: '1946',
    progress: 34,
    availability: 'Reading available',
    skill: 'Compiling',
    collection: 'Psychology',
    tags: ['meaning', 'suffering', 'responsibility'],
    location: 'Part II, Logotherapy',
    excerpt: 'Frankl presents meaning as situational and practical: found through work, relationship, or the stance taken toward unavoidable suffering.',
    relevance: 'Potentially relevant to your recent distinction between motivation and having a reason to continue.',
  },
  {
    id: 'stranger',
    title: 'The Stranger',
    author: 'Albert Camus',
    cover: 'https://covers.openlibrary.org/b/isbn/9780679720201-L.jpg',
    year: '1942',
    progress: 0,
    availability: 'Reading available',
    skill: 'Not created',
    collection: 'Fiction',
    tags: ['absurdity', 'alienation', 'judgment'],
    location: 'Part I',
    excerpt: 'The novel follows a detached narrator whose emotional distance becomes as consequential as the acts for which he is judged.',
    relevance: 'Added after your interest in how social expectations shape moral judgment.',
  },
  {
    id: 'brothers',
    title: 'The Brothers Karamazov',
    author: 'Fyodor Dostoevsky',
    cover: 'https://covers.openlibrary.org/b/isbn/9780374528379-L.jpg',
    year: '1880',
    progress: 18,
    availability: 'Reading available',
    skill: 'Compiling',
    collection: 'Fiction',
    tags: ['faith', 'freedom', 'family'],
    location: 'Book V',
    excerpt: 'Competing moral visions are tested through family conflict, responsibility, belief, and the consequences of radical freedom.',
    relevance: 'This sits near your questions about whether understanding a person changes moral responsibility.',
  },
  {
    id: 'courage',
    title: 'The Courage to Be Disliked',
    author: 'Ichiro Kishimi and Fumitake Koga',
    cover: 'https://covers.openlibrary.org/b/isbn/9781501197277-L.jpg',
    year: '2013',
    progress: 0,
    availability: 'Knowledge available',
    skill: 'Ready',
    collection: 'Psychology',
    tags: ['agency', 'relationships', 'approval'],
    location: 'The separation of tasks',
    excerpt: 'The dialogue argues that many interpersonal conflicts come from taking responsibility for outcomes that belong to someone else.',
    relevance: 'Useful counterweight to your tendency to take ownership of how other people respond.',
  },
  {
    id: 'creative-act',
    title: 'The Creative Act',
    author: 'Rick Rubin',
    cover: 'https://covers.openlibrary.org/b/isbn/9780593652886-L.jpg',
    year: '2023',
    progress: 8,
    availability: 'Reading available',
    skill: 'Not created',
    collection: 'Creativity',
    tags: ['craft', 'attention', 'taste'],
    location: 'Awareness',
    excerpt: 'Creativity begins with receptive attention, followed by choices that shape raw perception into a work.',
    relevance: 'Connected to your preference for building from a strong point of view rather than copying surface details.',
  },
  {
    id: 'sapiens',
    title: 'Sapiens',
    author: 'Yuval Noah Harari',
    cover: 'https://covers.openlibrary.org/b/isbn/9780062316097-L.jpg',
    year: '2011',
    progress: 0,
    availability: 'Knowledge available',
    skill: 'Ready',
    collection: 'History',
    tags: ['history', 'institutions', 'narratives'],
    location: 'The Cognitive Revolution',
    excerpt: 'A broad account of how shared narratives enabled unusually large groups of humans to coordinate.',
    relevance: 'Relevant to your interest in why groups preserve ideas even when individual incentives change.',
  },
];

var BOOKS_PROTOTYPE_DISCOVERY = [
  {
    id: 'discovery-antifragile',
    title: 'Antifragile',
    author: 'Nassim Nicholas Taleb',
    cover: 'https://covers.openlibrary.org/b/isbn/9780812979688-L.jpg',
    source: 'https://openlibrary.org/isbn/9780812979688',
    reason: 'Extends your questions about resilience beyond recovery toward systems that improve under stress.',
    relation: 'From Meditations and your systems notes',
  },
  {
    id: 'discovery-art-living',
    title: 'The Art of Living',
    author: 'Epictetus, interpreted by Sharon Lebell',
    cover: 'https://covers.openlibrary.org/b/isbn/9780061286056-L.jpg',
    source: 'https://openlibrary.org/isbn/9780061286056',
    reason: 'A practical Stoic counterpoint with a more instructional voice than Marcus Aurelius.',
    relation: 'Author and idea adjacency',
  },
  {
    id: 'discovery-denial-death',
    title: 'The Denial of Death',
    author: 'Ernest Becker',
    cover: 'https://covers.openlibrary.org/b/isbn/9780684832401-L.jpg',
    source: 'https://openlibrary.org/isbn/9780684832401',
    reason: 'Offers a deeper psychological account of meaning, identity, and defensive behavior.',
    relation: "From Man's Search for Meaning",
  },
  {
    id: 'discovery-master-margarita',
    title: 'The Master and Margarita',
    author: 'Mikhail Bulgakov',
    cover: 'https://covers.openlibrary.org/b/isbn/9780141180144-L.jpg',
    source: 'https://openlibrary.org/isbn/9780141180144',
    reason: 'Adds satire and surrealism to the moral and institutional questions in your fiction shelf.',
    relation: 'Fiction shelf gap',
  },
];

var BOOKS_PROTOTYPE_VARIANTS = {
  A: 'Personal shelf',
  B: 'Reading desk',
  C: 'Collection index',
};

var BooksPrototypeCover = function BooksPrototypeCover({book, size='md'}) {
  const [failed, setFailed] = React.useState(false);
  const initials = book.title.split(/\s+/).filter(Boolean).slice(0, 3).map(part => part[0]).join('');
  return (
    <div className={'blp-cover ' + size} data-failed={failed ? 'true' : 'false'}>
      {!failed && <img src={book.cover} alt={`Cover of ${book.title}`} loading="lazy" onError={() => setFailed(true)}/>}
      {failed && <span aria-hidden="true">{initials}</span>}
    </div>
  );
};

var BooksPrototypeIconButton = function BooksPrototypeIconButton({label, children, onClick, pressed=false}) {
  return <button type="button" className="blp-icon-button" aria-label={label} title={label} aria-pressed={pressed || undefined} onClick={onClick}>{children}</button>;
};

var BooksPrototypeHeader = function BooksPrototypeHeader({surface, setSurface, query, setQuery, onImport}) {
  return (
    <header className="blp-header">
      <div className="blp-heading">
        <span className="blp-kicker">Personal intelligence</span>
        <h1>Books Agent</h1>
        <p>Read, question, and connect the books that shape your thinking.</p>
      </div>
      {(surface === 'library' || surface === 'discovery') && <div className="blp-header-actions">
        <label className="blp-search">
          <IcSearch size={15}/>
          <span className="sr-only">Search books</span>
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search title, author, idea"/>
        </label>
        <button type="button" className="blp-button secondary" onClick={onImport}><IcUpload size={15}/>Import EPUB</button>
      </div>}
      <nav className="blp-surface-tabs" aria-label="Books sections">
        <button type="button" className={surface === 'chat' ? 'active' : ''} onClick={() => setSurface('chat')}>Chat</button>
        <button type="button" className={surface === 'library' ? 'active' : ''} onClick={() => setSurface('library')}>Library</button>
        <button type="button" className={surface === 'discovery' ? 'active' : ''} onClick={() => setSurface('discovery')}>Discovery</button>
        <button type="button" className={surface === 'wisdom' ? 'active' : ''} onClick={() => setSurface('wisdom')}>Wisdom</button>
      </nav>
    </header>
  );
};

var BooksPrototypeActions = function BooksPrototypeActions({book, attached, skillState, onRead, onAttach, onSkill}) {
  return (
    <div className="blp-actions" aria-label={`Actions for ${book.title}`}>
      <button type="button" className="blp-button primary" onClick={onRead}><IcBook size={15}/>Read</button>
      <button type="button" className="blp-button secondary" onClick={onAttach}><IcChat size={15}/>{attached ? 'Added to chat' : 'Add to chat'}</button>
      <button type="button" className="blp-button secondary" onClick={onSkill}><IcSkills size={15}/>{skillState === 'Ready' ? 'Open skill' : skillState === 'Compiling' ? 'Compiling' : 'Create skill'}</button>
    </div>
  );
};

var BooksPrototypeInspector = function BooksPrototypeInspector({book, attached, skillState, onRead, onAttach, onSkill, compact=false}) {
  return (
    <aside className={'blp-inspector' + (compact ? ' compact' : '')} aria-label={`Book details for ${book.title}`}>
      <div className="blp-inspector-top">
        <BooksPrototypeCover book={book} size={compact ? 'md' : 'lg'}/>
        <div>
          <span className="blp-overline">{book.collection} / {book.year}</span>
          <h2>{book.title}</h2>
          <p>{book.author}</p>
        </div>
      </div>
      <BooksPrototypeActions book={book} attached={attached} skillState={skillState} onRead={onRead} onAttach={onAttach} onSkill={onSkill}/>
      <dl className="blp-facts">
        <div><dt>Available</dt><dd>{book.availability}</dd></div>
        <div><dt>Book skill</dt><dd>{skillState}</dd></div>
        <div><dt>Progress</dt><dd>{book.progress ? `${book.progress}%` : 'Not started'}</dd></div>
      </dl>
      <section className="blp-inspector-section">
        <span className="blp-overline">Why it is here</span>
        <p>{book.relevance}</p>
      </section>
      <section className="blp-inspector-section">
        <span className="blp-overline">Ideas</span>
        <div className="blp-tags">{book.tags.map(tag => <span key={tag}>{tag}</span>)}</div>
      </section>
    </aside>
  );
};

var BooksPrototypeDiscovery = function BooksPrototypeDiscovery() {
  return (
    <div className="blp-discovery">
      <div className="blp-section-head">
        <div><span className="blp-overline">Discovery</span><h2>Books worth your attention</h2></div>
        <p>Suggested from authors, ideas, and gaps in your Library. A suggestion is not evidence of your preference.</p>
      </div>
      <div className="blp-discovery-list">
        {BOOKS_PROTOTYPE_DISCOVERY.map(book => (
            <article className="blp-discovery-item" key={book.id}>
              <BooksPrototypeCover book={book} size="sm"/>
              <div className="blp-discovery-copy">
                <span className="blp-overline">{book.relation}</span>
                <h3>{book.title}</h3>
                <p className="blp-author">{book.author}</p>
                <p>{book.reason}</p>
              </div>
              <a className="blp-button secondary" href={book.source} target="_blank" rel="noreferrer">View source<IcChevR size={14}/></a>
            </article>
        ))}
      </div>
    </div>
  );
};

var BooksPrototypeWisdom = function BooksPrototypeWisdom({onOpenChat}) {
  const observations = [
    {
      title: 'Agency matters more than approval',
      state: 'Supported pattern',
      evidence: '4 books / 9 conversations',
      body: 'You repeatedly return to the distinction between owning your choices and managing other people\'s reactions.',
      sources: ['The Courage to Be Disliked', 'Meditations'],
    },
    {
      title: 'Meaning works better as a practice',
      state: 'Tentative',
      evidence: '2 books / 3 conversations',
      body: 'You respond more strongly to concrete responsibility than to abstract motivation. This remains a working interpretation.',
      sources: ["Man's Search for Meaning", 'The Almanack of Naval Ravikant'],
    },
    {
      title: 'Understanding is not absolution',
      state: 'Tension to revisit',
      evidence: '3 books / 5 conversations',
      body: 'Your questions often seek the root of harmful behavior while preserving accountability for its consequences.',
      sources: ['The Brothers Karamazov', 'The Stranger'],
    },
  ];
  return (
    <main className="blp-wisdom">
      <div className="blp-section-head">
        <div><span className="blp-overline">Wisdom</span><h2>What your reading may be teaching Vellum about you</h2></div>
        <p>Interpretations stay qualified, source-linked, and revisable. A book idea is never treated as your belief without supporting behavior or confirmation.</p>
      </div>
      <div className="blp-wisdom-grid">
        {observations.map(item => <article key={item.title} className="blp-wisdom-card">
          <div className="blp-wisdom-meta"><span>{item.state}</span><small>{item.evidence}</small></div>
          <h3>{item.title}</h3>
          <p>{item.body}</p>
          <div className="blp-wisdom-sources">{item.sources.map(source => <span key={source}><IcBook size={12}/>{source}</span>)}</div>
          <button type="button" className="blp-button secondary" onClick={onOpenChat}><IcChat size={14}/>Discuss with Books Agent</button>
        </article>)}
      </div>
    </main>
  );
};

var BooksPrototypeVariantA = function BooksPrototypeVariantA(props) {
  const {books, selected, selectBook, query, collection, setCollection} = props;
  const groups = [
    {name: 'Recently added', items: books.filter(book => book.imported)},
    {name: 'Continue reading', items: books.filter(book => book.progress > 0 && book.progress < 100)},
    {name: 'Knowledge ready', items: books.filter(book => book.skill === 'Ready')},
    {name: 'Fiction', items: books.filter(book => book.collection === 'Fiction')},
  ];
  return (
    <div className="blp-a">
      <aside className="blp-collections" aria-label="Library collections">
        <span className="blp-overline">Collections</span>
        {['All books', 'Reading', 'Skills ready', 'Philosophy', 'Fiction', 'Psychology'].map(name => (
          <button type="button" key={name} className={collection === name ? 'active' : ''} onClick={() => setCollection(name)}>
            <span>{name}</span><strong>{name === 'All books' ? books.length : name === 'Reading' ? books.filter(book => book.progress > 0 && book.progress < 100).length : name === 'Skills ready' ? books.filter(book => book.skill === 'Ready').length : books.filter(book => book.collection === name).length}</strong>
          </button>
        ))}
        <div className="blp-collection-rule"/>
        <span className="blp-overline">Library state</span>
        <p>{books.filter(book => book.skill === 'Ready').length} skills ready</p>
        <p>{books.filter(book => book.progress > 0 && book.progress < 100).length} in progress</p>
      </aside>
      <main className="blp-shelves">
        {query && <div className="blp-result-line">{books.length} results for <strong>{query}</strong></div>}
        {groups.map(group => {
          let items = group.items;
          if (collection === 'Reading') items = items.filter(book => book.progress > 0 && book.progress < 100);
          if (collection === 'Skills ready') items = items.filter(book => book.skill === 'Ready');
          if (!['All books', 'Reading', 'Skills ready'].includes(collection)) items = items.filter(book => book.collection === collection);
          if (!items.length) return null;
          return (
            <section className="blp-shelf" key={group.name}>
              <div className="blp-shelf-head"><h2>{group.name}</h2><span>{items.length}</span></div>
              <div className="blp-book-row">
                {items.map(book => (
                  <button type="button" key={book.id} className={'blp-book-tile' + (selected.id === book.id ? ' selected' : '')} onClick={() => selectBook(book.id)}>
                    <BooksPrototypeCover book={book}/>
                    <span className="blp-book-title">{book.title}</span>
                    <span className="blp-book-author">{book.author}</span>
                    {book.progress > 0 && book.progress < 100 && <span className="blp-progress"><i style={{width: `${book.progress}%`}}/></span>}
                  </button>
                ))}
              </div>
            </section>
          );
        })}
      </main>
      <BooksPrototypeInspector {...props} book={selected}/>
    </div>
  );
};

var BooksPrototypeVariantB = function BooksPrototypeVariantB(props) {
  const {books, selected, selectBook, reading, setReading, ask, setAsk, answer, onAsk} = props;
  return (
    <div className="blp-b">
      <aside className="blp-spine-rail" aria-label="Books">
        <div className="blp-spine-title"><span className="blp-overline">On your desk</span><strong>{books.length} books</strong></div>
        <div className="blp-spines">
          {books.map(book => (
            <button type="button" key={book.id} className={selected.id === book.id ? 'active' : ''} aria-label={`Open ${book.title}`} onClick={() => {selectBook(book.id); setReading(false);}}>
              <BooksPrototypeCover book={book} size="xs"/>
              <span><strong>{book.title}</strong><small>{book.author}</small></span>
              {book.progress > 0 && <i>{book.progress}%</i>}
            </button>
          ))}
        </div>
      </aside>
      <main className="blp-reader">
        <div className="blp-reader-head">
          <div><span className="blp-overline">{reading ? selected.location : selected.collection}</span><h2>{selected.title}</h2><p>{selected.author}</p></div>
          <div className="blp-reader-mode" role="group" aria-label="Book mode">
            <button type="button" className={!reading ? 'active' : ''} onClick={() => setReading(false)}>Inspect</button>
            <button type="button" className={reading ? 'active' : ''} onClick={() => setReading(true)}>Read</button>
          </div>
        </div>
        {reading ? (
          <article className="blp-page-preview">
            <span className="blp-overline">{selected.location}</span>
            <p>{selected.excerpt}</p>
            <p className="blp-reading-copy">The reading surface keeps the edition and source location visible while leaving enough room for uninterrupted text. Selecting a passage would make it available to BooksAgent without leaving the page.</p>
            <footer><span>{selected.progress || 1}%</span><div className="blp-page-progress"><i style={{width: `${Math.max(selected.progress, 3)}%`}}/></div></footer>
          </article>
        ) : (
          <div className="blp-desk-overview">
            <BooksPrototypeCover book={selected} size="xl"/>
            <div className="blp-desk-copy">
              <span className="blp-overline">Current thread</span>
              <p className="blp-desk-lead">{selected.relevance}</p>
              <div className="blp-desk-note"><strong>{selected.location}</strong><p>{selected.excerpt}</p></div>
              <BooksPrototypeActions {...props} book={selected}/>
            </div>
          </div>
        )}
      </main>
      <aside className="blp-margin" aria-label="BooksAgent context">
        <div className="blp-margin-head"><IcBook size={16}/><div><strong>BooksAgent</strong><span>Grounded in this edition</span></div></div>
        <div className="blp-context-block"><span className="blp-overline">Relevant to you</span><p>{selected.relevance}</p></div>
        <form className="blp-ask" onSubmit={event => {event.preventDefault(); onAsk();}}>
          <label htmlFor="blp-ask-input">Ask about this book</label>
          <textarea id="blp-ask-input" value={ask} onChange={event => setAsk(event.target.value)} placeholder="What is the core argument here?"/>
          <button type="submit" className="blp-button primary" disabled={!ask.trim()}><IcArrowUp size={14}/>Ask</button>
        </form>
        {answer && <div className="blp-answer" aria-live="polite"><span className="blp-overline">Supported synthesis</span><p>{answer}</p><button type="button">{selected.location}<IcChevR size={12}/></button></div>}
      </aside>
    </div>
  );
};

var BooksPrototypeVariantC = function BooksPrototypeVariantC(props) {
  const {books, selected, selectBook, scale} = props;
  const rows = React.useMemo(() => {
    if (scale !== 'large') return books;
    return Array.from({length: 1024}, (_, index) => {
      const base = books[index % books.length];
      return index < books.length ? base : {...base, id: `${base.id}-${index}`, title: `${base.title} ${String(index + 1).padStart(4, '0')}`, progress: index % 7 === 0 ? (index * 13) % 100 : 0};
    });
  }, [books, scale]);
  const visible = rows.slice(0, scale === 'large' ? 80 : rows.length);
  return (
    <div className="blp-c">
      <div className="blp-index-toolbar">
        <div><span className="blp-overline">Collection index</span><strong>{rows.length.toLocaleString()} books</strong></div>
        <div className="blp-index-stats"><span>{rows.filter(book => book.skill === 'Ready').length} skills ready</span><span>{rows.filter(book => book.progress > 0 && book.progress < 100).length} reading</span><span>4 collections</span></div>
      </div>
      <div className="blp-index-layout">
        <section className="blp-index-table" aria-label="Book index">
          <div className="blp-index-head"><span>Book</span><span>Collection</span><span>Knowledge</span><span>Progress</span></div>
          <div className="blp-index-scroll">
            {visible.map(book => (
              <button type="button" className={'blp-index-row' + (selected.id === book.id ? ' active' : '')} key={book.id} onClick={() => selectBook(book.id)}>
                <span className="blp-index-book"><BooksPrototypeCover book={book} size="micro"/><span><strong>{book.title}</strong><small>{book.author}</small></span></span>
                <span>{book.collection}</span>
                <span className={'blp-state ' + book.skill.toLowerCase().replace(' ', '-')}>{book.skill}</span>
                <span>{book.progress ? `${book.progress}%` : '-'}</span>
              </button>
            ))}
            {rows.length > visible.length && <div className="blp-index-more">Showing {visible.length} of {rows.length.toLocaleString()} indexed books</div>}
          </div>
        </section>
        <BooksPrototypeInspector {...props} compact book={selected}/>
      </div>
    </div>
  );
};

var BooksPrototypeSwitcher = function BooksPrototypeSwitcher({variant, setVariant, scale, setScale, state}) {
  const keys = Object.keys(BOOKS_PROTOTYPE_VARIANTS);
  const cycle = direction => {
    const index = keys.indexOf(variant);
    setVariant(keys[(index + direction + keys.length) % keys.length]);
  };
  React.useEffect(() => {
    const onKey = event => {
      const target = event.target;
      if (target && (target.matches('input, textarea, [contenteditable="true"]'))) return;
      if (event.key === 'ArrowLeft') cycle(-1);
      if (event.key === 'ArrowRight') cycle(1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [variant]);
  return (
    <div className="blp-switcher" role="toolbar" aria-label="Books agent prototype variants">
      <BooksPrototypeIconButton label="Previous variant" onClick={() => cycle(-1)}><span aria-hidden="true">&larr;</span></BooksPrototypeIconButton>
      <div className="blp-switch-label"><strong>{variant}</strong><span>{BOOKS_PROTOTYPE_VARIANTS[variant]}</span><small>{state}</small></div>
      <BooksPrototypeIconButton label="Next variant" onClick={() => cycle(1)}><span aria-hidden="true">&rarr;</span></BooksPrototypeIconButton>
      <div className="blp-switch-rule"/>
      <button type="button" className={scale === 'small' ? 'active' : ''} onClick={() => setScale('small')}>8</button>
      <button type="button" className={scale === 'large' ? 'active' : ''} onClick={() => setScale('large')}>1,024</button>
    </div>
  );
};

var BooksPrototypeView = function BooksPrototypeView({agentProps, DefaultAgentView}) {
  const params = new URLSearchParams(window.location.search);
  const initialVariant = BOOKS_PROTOTYPE_VARIANTS[params.get('variant')] ? params.get('variant') : 'A';
  const requestedSurface = params.get('section');
  const initialSurface = ['chat', 'library', 'discovery', 'wisdom'].includes(requestedSurface) ? requestedSurface : 'library';
  const [variant, setVariantState] = React.useState(initialVariant);
  const [scale, setScaleState] = React.useState(params.get('scale') === 'large' ? 'large' : 'small');
  const [surface, setSurfaceState] = React.useState(initialSurface);
  const [query, setQuery] = React.useState('');
  const [collection, setCollection] = React.useState('All books');
  const [selectedId, setSelectedId] = React.useState('meditations');
  const [addedBooks, setAddedBooks] = React.useState([]);
  const [attached, setAttached] = React.useState([]);
  const [skillStates, setSkillStates] = React.useState(() => Object.fromEntries(BOOKS_PROTOTYPE_BOOKS.map(book => [book.id, book.skill])));
  const [reading, setReading] = React.useState(false);
  const [ask, setAsk] = React.useState('');
  const [answer, setAnswer] = React.useState('');
  const [announcement, setAnnouncement] = React.useState('Prototype ready');
  const fileRef = React.useRef(null);

  const books = [...addedBooks, ...BOOKS_PROTOTYPE_BOOKS].filter(book => {
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    return [book.title, book.author, book.collection, ...(book.tags || [])].join(' ').toLowerCase().includes(needle);
  });
  const allBooks = [...addedBooks, ...BOOKS_PROTOTYPE_BOOKS];
  const selected = allBooks.find(book => book.id === selectedId) || books[0] || BOOKS_PROTOTYPE_BOOKS[0];
  const selectedSkill = skillStates[selected.id] || selected.skill || 'Not created';

  const updateUrl = (nextVariant, nextScale, nextSurface=surface) => {
    const next = new URL(window.location.href);
    next.searchParams.set('view', 'agent');
    next.searchParams.set('agent', 'books');
    next.searchParams.set('booksPrototype', '1');
    next.searchParams.set('variant', nextVariant);
    next.searchParams.set('scale', nextScale);
    next.searchParams.set('section', nextSurface);
    window.history.replaceState({}, '', next);
  };
  const setVariant = value => { setVariantState(value); updateUrl(value, scale); setAnnouncement(`Variant ${value}: ${BOOKS_PROTOTYPE_VARIANTS[value]}`); };
  const setScale = value => { setScaleState(value); updateUrl(variant, value); setAnnouncement(value === 'large' ? 'Large collection state loaded' : 'Personal collection state loaded'); };
  const setSurface = value => { setSurfaceState(value); updateUrl(variant, scale, value); setAnnouncement(`${value} section opened`); };
  const selectBook = id => { setSelectedId(id); setAnswer(''); setAnnouncement(`${allBooks.find(book => book.id === id)?.title || 'Book'} selected`); };
  const attach = () => { setAttached(items => items.includes(selected.id) ? items : [...items, selected.id]); setAnnouncement(`${selected.title} added to the next chat`); };
  const createSkill = () => {
    if (selectedSkill === 'Ready') { setAnnouncement(`${selected.title} skill opened`); return; }
    setSkillStates(states => ({...states, [selected.id]: 'Compiling'}));
    setAnnouncement(`Creating a Book skill for ${selected.title}`);
    window.setTimeout(() => { setSkillStates(states => ({...states, [selected.id]: 'Ready'})); setAnnouncement(`${selected.title} skill is ready`); }, 1400);
  };
  const read = () => { setReading(true); if (variant !== 'B') setVariant('B'); setAnnouncement(`Reading ${selected.title}`); };
  const importEpub = file => {
    if (!file) return;
    const title = file.name.replace(/\.epub$/i, '').replace(/[-_]+/g, ' ');
    const importedBook = {id: `import-${Date.now()}`, title, author: 'Imported EPUB', year: 'Local', progress: 0, availability: 'Processing', skill: 'Compiling', collection: 'Imported', tags: ['new'], location: 'Preparing chapters', excerpt: 'Vellum is preparing the EPUB structure.', relevance: 'Imported explicitly by you.', imported: true};
    setAddedBooks(items => [importedBook, ...items]);
    setSkillStates(states => ({...states, [importedBook.id]: 'Compiling'}));
    setSelectedId(importedBook.id);
    setSurface('library');
    setAnnouncement(`${title} imported for processing`);
  };
  const onAsk = () => {
    setAnswer(`${selected.title} frames this as a problem of ${selected.tags.slice(0, 2).join(' and ')}. The selected section supports that reading, but it should remain an interpretation rather than an attributed quotation.`);
    setAnnouncement('BooksAgent returned a supported synthesis');
  };

  const shared = {
    books,
    selected,
    selectBook,
    collection,
    setCollection,
    attached: attached.includes(selected.id),
    skillState: selectedSkill,
    onRead: read,
    onAttach: attach,
    onSkill: createSkill,
    reading,
    setReading,
    ask,
    setAsk,
    answer,
    onAsk,
    scale,
  };

  return (
    <div className="blp-root">
      <BooksPrototypeHeader surface={surface} setSurface={setSurface} query={query} setQuery={setQuery} onImport={() => fileRef.current?.click()}/>
      <input ref={fileRef} type="file" accept=".epub,application/epub+zip" hidden onChange={event => {importEpub(event.target.files?.[0]); event.target.value = '';}}/>
      <div className="blp-live sr-only" aria-live="polite">{announcement}</div>
      <div className={'blp-content blp-content-' + surface}>
        {surface === 'chat' && <div className="blp-agent-chat"><DefaultAgentView {...agentProps}/></div>}
        {surface === 'discovery' && <BooksPrototypeDiscovery/>}
        {surface === 'wisdom' && <BooksPrototypeWisdom onOpenChat={() => setSurface('chat')}/>}
        {surface === 'library' && (variant === 'A'
          ? <BooksPrototypeVariantA {...shared} query={query}/>
          : variant === 'B'
            ? <BooksPrototypeVariantB {...shared}/>
            : <BooksPrototypeVariantC {...shared}/>)}
      </div>
      <BooksPrototypeSwitcher variant={variant} setVariant={setVariant} scale={scale} setScale={setScale} state={`${surface} / ${selected.title}`}/>
    </div>
  );
};
