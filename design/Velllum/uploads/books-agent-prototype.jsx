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

var BOOKS_PROTOTYPE_COLORS = ['#b8c777', '#eb5149', '#537da8', '#d69b3c', '#9b6a88', '#5b9a86', '#d8d0bd', '#7468b0'];

var booksPrototypePalette = function booksPrototypePalette(book) {
  const index = Math.max(0, BOOKS_PROTOTYPE_BOOKS.findIndex(item => item.id === book.id));
  const accent = BOOKS_PROTOTYPE_COLORS[index % BOOKS_PROTOTYPE_COLORS.length];
  const backgrounds = ['#1b1715', '#202d46', '#132c2a', '#312417', '#27202d', '#172926', '#2b2925', '#201d35'];
  return {accent, background: backgrounds[index % backgrounds.length]};
};

var BooksPrototypeCover = function BooksPrototypeCover({book, size='md'}) {
  const [failed, setFailed] = React.useState(false);
  const initials = book.title.split(/\s+/).filter(Boolean).slice(0, 3).map(part => part[0]).join('');
  return (
    <div className={'blp-cover ' + size} data-failed={failed ? 'true' : 'false'}>
      {!failed && <img src={book.cover} alt={`Cover of ${book.title}`} loading="eager" onError={() => setFailed(true)}/>}
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
      {surface === 'library' && <div className="blp-header-actions">
        <label className="blp-search">
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

var BooksPrototypeDiscovery = function BooksPrototypeDiscovery() {
  return (
    <main className="blp-discovery">
      <div className="blp-section-head">
        <div><h2>Books worth your attention</h2></div>
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
    </main>
  );
};

var BooksPrototypeWisdom = function BooksPrototypeWisdom({onOpenChat}) {
  const observations = [
    {
      title: 'Agency matters more than approval',
      state: 'Supported pattern',
      body: 'You repeatedly return to the distinction between owning your choices and managing other people\'s reactions.',
      sources: ['The Courage to Be Disliked', 'Meditations'],
    },
    {
      title: 'Meaning works better as a practice',
      state: 'Tentative',
      body: 'You respond more strongly to concrete responsibility than to abstract motivation. This remains a working interpretation.',
      sources: ["Man's Search for Meaning", 'The Almanack of Naval Ravikant'],
    },
    {
      title: 'Understanding is not absolution',
      state: 'Tension to revisit',
      body: 'Your questions often seek the root of harmful behavior while preserving accountability for its consequences.',
      sources: ['The Brothers Karamazov', 'The Stranger'],
    },
  ];
  return (
    <main className="blp-wisdom">
      <div className="blp-section-head">
        <div><h2>What your reading may be teaching Vellum about you</h2></div>
        <p>Interpretations stay qualified, source-linked, and revisable. A book idea is never treated as your belief without supporting behavior or confirmation.</p>
      </div>
      <div className="blp-wisdom-grid">
        {observations.map(item => <article key={item.title} className="blp-wisdom-card">
          <div className="blp-wisdom-meta"><span>{item.state}</span></div>
          <h3>{item.title}</h3>
          <p>{item.body}</p>
          <div className="blp-wisdom-sources">{item.sources.map(source => {
            const book = BOOKS_PROTOTYPE_BOOKS.find(candidate => candidate.title === source);
            return <span key={source}>{book && <BooksPrototypeCover book={book} size="micro"/>}<strong>{source}</strong></span>;
          })}</div>
          <button type="button" className="blp-button secondary" onClick={onOpenChat}><IcChat size={14}/>Discuss with Books Agent</button>
        </article>)}
      </div>
    </main>
  );
};

var BooksPrototypeShelf3D = function BooksPrototypeShelf3D({books, selectedId, onSelect, onOpen}) {
  const mountRef = React.useRef(null);
  const moveRef = React.useRef(null);
  const callbacksRef = React.useRef({onSelect, onOpen});
  const selectedRef = React.useRef(selectedId);
  const [loadState, setLoadState] = React.useState('loading');
  const [activeIndex, setActiveIndex] = React.useState(Math.max(0, books.findIndex(book => book.id === selectedId)));
  callbacksRef.current = {onSelect, onOpen};
  selectedRef.current = selectedId;

  React.useEffect(() => {
    const host = mountRef.current;
    if (!host || !books.length) return undefined;
    let disposed = false;
    let cleanup = () => {};
    setLoadState('loading');
    import('https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.min.js').then(THREE => {
      if (disposed) return;
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x1b1715);
      scene.fog = new THREE.Fog(0x1b1715, 10, 24);
      const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
      camera.position.set(0, 0.05, 9.2);
      const renderer = new THREE.WebGLRenderer({antialias: true, alpha: false, powerPreference: 'high-performance'});
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      renderer.domElement.className = 'bar-webgl';
      renderer.domElement.setAttribute('aria-hidden', 'true');
      host.appendChild(renderer.domElement);

      const ambient = new THREE.HemisphereLight(0xfff5df, 0x251914, 2.1);
      scene.add(ambient);
      const key = new THREE.DirectionalLight(0xffe7c1, 4.8);
      key.position.set(-4, 5, 8);
      key.castShadow = true;
      scene.add(key);
      const rim = new THREE.DirectionalLight(0x9cbfd0, 1.7);
      rim.position.set(7, 2, 1);
      scene.add(rim);

      const shelf = new THREE.Group();
      scene.add(shelf);
      const bookMeshes = [];
      const bookSpacing = 0.78;

      const makeLabelTexture = (book, color) => {
        const canvas = document.createElement('canvas');
        canvas.width = 1200;
        canvas.height = 180;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = color;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = 'rgba(255,255,255,.16)';
        ctx.fillRect(0, 0, 10, canvas.height);
        ctx.fillStyle = '#fffaf0';
        ctx.textBaseline = 'middle';
        ctx.font = book.author.length > 22 ? '500 20px Arial' : '500 25px Arial';
        ctx.fillText(book.author.toUpperCase(), 44, 90);
        ctx.font = book.title.length > 26 ? '600 30px Georgia' : '600 36px Georgia';
        ctx.fillText(book.title, 420, 90);
        ctx.textAlign = 'right';
        ctx.font = '500 25px Arial';
        ctx.fillText(book.year, 1150, 90);
        const texture = new THREE.CanvasTexture(canvas);
        texture.colorSpace = THREE.SRGBColorSpace;
        return texture;
      };

      books.forEach((book, index) => {
        const color = BOOKS_PROTOTYPE_COLORS[index % BOOKS_PROTOTYPE_COLORS.length];
        const spineTexture = makeLabelTexture(book, color);
        const edge = new THREE.MeshStandardMaterial({color: 0xe6dfd1, roughness: 0.82});
        const cloth = new THREE.MeshPhysicalMaterial({color, roughness: 0.68, clearcoat: 0.12});
        const spine = new THREE.MeshPhysicalMaterial({map: spineTexture, roughness: 0.58, clearcoat: 0.16});
        const width = 5.1 + (index % 3) * 0.42;
        const geometry = new THREE.BoxGeometry(width, 0.54, 1.24, 5, 1, 2);
        const mesh = new THREE.Mesh(geometry, [cloth, cloth, edge, edge, spine, cloth]);
        mesh.position.set((index % 2 ? -1 : 1) * 0.18, -index * bookSpacing, 0);
        mesh.rotation.z = (index % 2 ? -1 : 1) * 0.012;
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        mesh.userData = {bookId: book.id, index, baseX: mesh.position.x, baseZ: mesh.position.z, baseRotation: mesh.rotation.z};
        shelf.add(mesh);
        bookMeshes.push(mesh);
      });
      const backdrop = new THREE.Mesh(
        new THREE.PlaneGeometry(28, 11),
        new THREE.MeshStandardMaterial({color: 0x1b1715, roughness: 1})
      );
      backdrop.position.set(0, 0, -2.4);
      scene.add(backdrop);

      const raycaster = new THREE.Raycaster();
      const pointer = new THREE.Vector2(3, 3);
      const maxIndex = Math.max(0, books.length - 1);
      let current = Math.max(0, books.findIndex(book => book.id === selectedRef.current));
      let targetOffset = current * bookSpacing;
      let offset = targetOffset;
      let hovered = -1;
      let pointerDown = null;
      let frame = 0;

      const moveTo = value => {
        current = Math.max(0, Math.min(maxIndex, value));
        targetOffset = current * bookSpacing;
        setActiveIndex(current);
        callbacksRef.current.onSelect(books[current].id);
      };
      moveRef.current = moveTo;

      const resize = () => {
        const width = Math.max(1, host.clientWidth);
        const height = Math.max(1, host.clientHeight);
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
      };
      const updatePointer = event => {
        const rect = renderer.domElement.getBoundingClientRect();
        pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      };
      const pick = event => {
        updatePointer(event);
        raycaster.setFromCamera(pointer, camera);
        const hit = raycaster.intersectObjects(bookMeshes, false)[0];
        return hit ? hit.object.userData.index : -1;
      };
      const onMove = event => {
        if (pointerDown) {
          const dy = event.clientY - pointerDown.y;
          pointerDown.moved = Math.max(pointerDown.moved, Math.abs(dy));
          targetOffset = Math.max(0, Math.min(maxIndex * bookSpacing, pointerDown.offset - dy * 0.012));
          return;
        }
        hovered = pick(event);
        renderer.domElement.style.cursor = hovered >= 0 ? 'pointer' : 'grab';
      };
      const onDown = event => {
        pointerDown = {y: event.clientY, offset: targetOffset, moved: 0};
        renderer.domElement.setPointerCapture?.(event.pointerId);
        renderer.domElement.style.cursor = 'grabbing';
      };
      const onUp = event => {
        if (!pointerDown) return;
        const drag = pointerDown;
        pointerDown = null;
        const picked = pick(event);
        if (drag.moved < 6 && picked >= 0) {
          moveTo(picked);
          callbacksRef.current.onOpen(books[picked].id);
        } else moveTo(Math.round(targetOffset / bookSpacing));
      };
      const onWheel = event => {
        event.preventDefault();
        const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
        targetOffset = Math.max(0, Math.min(maxIndex * bookSpacing, targetOffset + delta * 0.005));
        current = Math.round(targetOffset / bookSpacing);
        setActiveIndex(current);
        callbacksRef.current.onSelect(books[current].id);
      };
      renderer.domElement.addEventListener('pointermove', onMove);
      renderer.domElement.addEventListener('pointerdown', onDown);
      renderer.domElement.addEventListener('pointerup', onUp);
      renderer.domElement.addEventListener('pointercancel', onUp);
      renderer.domElement.addEventListener('wheel', onWheel, {passive: false});
      const observer = new ResizeObserver(resize);
      observer.observe(host);
      resize();

      const clock = new THREE.Clock();
      const animate = () => {
        if (disposed) return;
        const delta = Math.min(clock.getDelta(), 0.05);
        offset = THREE.MathUtils.damp(offset, targetOffset, 5.5, delta);
        shelf.position.y = offset;
        bookMeshes.forEach((mesh, index) => {
          const active = index === hovered || index === current;
          mesh.position.x = THREE.MathUtils.damp(mesh.position.x, mesh.userData.baseX + (active ? 0.34 : 0), 8, delta);
          mesh.position.z = THREE.MathUtils.damp(mesh.position.z, mesh.userData.baseZ + (index === hovered ? 0.52 : index === current ? 0.18 : 0), 8, delta);
          mesh.rotation.z = THREE.MathUtils.damp(mesh.rotation.z, mesh.userData.baseRotation + (index === hovered ? -0.025 : 0), 8, delta);
          mesh.rotation.y = THREE.MathUtils.damp(mesh.rotation.y, index === hovered ? -0.08 : 0, 8, delta);
        });
        camera.position.x = THREE.MathUtils.damp(camera.position.x, 0, 5, delta);
        renderer.render(scene, camera);
        frame = requestAnimationFrame(animate);
      };
      animate();
      setLoadState('ready');
      cleanup = () => {
        cancelAnimationFrame(frame);
        observer.disconnect();
        renderer.domElement.removeEventListener('pointermove', onMove);
        renderer.domElement.removeEventListener('pointerdown', onDown);
        renderer.domElement.removeEventListener('pointerup', onUp);
        renderer.domElement.removeEventListener('pointercancel', onUp);
        renderer.domElement.removeEventListener('wheel', onWheel);
        bookMeshes.forEach(mesh => {
          mesh.geometry.dispose();
          mesh.material.forEach(material => { material.map?.dispose(); material.dispose(); });
        });
        backdrop.geometry.dispose();
        backdrop.material.dispose();
        renderer.dispose();
        renderer.domElement.remove();
      };
    }).catch(() => { if (!disposed) setLoadState('fallback'); });
    return () => { disposed = true; cleanup(); };
  }, [books.map(book => book.id).join('|')]);

  const move = direction => moveRef.current?.(activeIndex + direction);
  return (
    <div className="bar-shelf-stage" ref={mountRef} data-render-state={loadState}>
      <div className="bar-shelf-wash" aria-hidden="true"/>
      <div className={'bar-shelf-fallback ' + (loadState === 'ready' ? 'webgl-ready' : '')}>{books.map((book, index) => <button type="button" key={book.id} style={{'--spine': BOOKS_PROTOTYPE_COLORS[index % BOOKS_PROTOTYPE_COLORS.length]}} aria-label={`Open ${book.title}`} onClick={() => {moveRef.current?.(index); onOpen(book.id);}}><span>{book.author}</span><strong>{book.title}</strong><small>{book.year}</small></button>)}</div>
      <div className="bar-shelf-controls">
        <BooksPrototypeIconButton label="Previous book" onClick={() => move(-1)}><span aria-hidden="true">&larr;</span></BooksPrototypeIconButton>
        <span><strong>{String(activeIndex + 1).padStart(2, '0')}</strong> / {String(books.length).padStart(2, '0')}</span>
        <BooksPrototypeIconButton label="Next book" onClick={() => move(1)}><span aria-hidden="true">&rarr;</span></BooksPrototypeIconButton>
      </div>
      <div className="bar-shelf-access" aria-label="Books on shelf">{books.map((book, index) => <button type="button" key={book.id} className={index === activeIndex ? 'active' : ''} onFocus={() => moveRef.current?.(index)} onClick={() => onOpen(book.id)}><span>{String(index + 1).padStart(2, '0')}</span><strong>{book.title}</strong></button>)}</div>
    </div>
  );
};

var BooksPrototypeBookModel3D = function BooksPrototypeBookModel3D({book}) {
  const hostRef = React.useRef(null);
  const [state, setState] = React.useState('loading');
  React.useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    let disposed = false;
    let cleanup = () => {};
    import('https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.min.js').then(THREE => {
      if (disposed) return;
      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
      camera.position.set(0, 0.05, 7.2);
      const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true, powerPreference: 'high-performance'});
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.shadowMap.enabled = true;
      renderer.domElement.className = 'bpd-book-canvas';
      renderer.domElement.setAttribute('aria-hidden', 'true');
      host.appendChild(renderer.domElement);
      scene.add(new THREE.HemisphereLight(0xfff5e6, 0x1d1720, 3));
      const key = new THREE.DirectionalLight(0xffffff, 4.2);
      key.position.set(-3, 5, 6);
      key.castShadow = true;
      scene.add(key);
      const group = new THREE.Group();
      scene.add(group);
      const edge = new THREE.MeshStandardMaterial({color: 0xf2eadc, roughness: 0.76});
      const palette = booksPrototypePalette(book);
      const cloth = new THREE.MeshPhysicalMaterial({color: palette.accent, roughness: 0.62, clearcoat: 0.16});
      const coverCanvas = document.createElement('canvas');
      coverCanvas.width = 768;
      coverCanvas.height = 1152;
      const ctx = coverCanvas.getContext('2d');
      ctx.fillStyle = palette.accent;
      ctx.fillRect(0, 0, 768, 1152);
      ctx.strokeStyle = 'rgba(255,255,255,.42)';
      ctx.lineWidth = 5;
      ctx.strokeRect(48, 48, 672, 1056);
      ctx.fillStyle = '#fff9ec';
      ctx.textAlign = 'center';
      ctx.font = '600 58px Georgia';
      const words = book.title.split(' ');
      let line = '';
      let y = 430;
      words.forEach(word => {
        const next = `${line} ${word}`.trim();
        if (ctx.measureText(next).width > 600 && line) { ctx.fillText(line, 384, y); line = word; y += 72; } else line = next;
      });
      ctx.fillText(line, 384, y);
      ctx.font = '28px Arial';
      ctx.fillText(book.author.toUpperCase(), 384, 930);
      const fallback = new THREE.CanvasTexture(coverCanvas);
      fallback.colorSpace = THREE.SRGBColorSpace;
      const front = new THREE.MeshBasicMaterial({map: fallback});
      const geometry = new THREE.BoxGeometry(2.5, 3.8, 0.34, 2, 3, 1);
      const model = new THREE.Mesh(geometry, [cloth, cloth, edge, edge, front, cloth]);
      model.castShadow = true;
      model.rotation.set(-0.1, -0.9, -0.06);
      group.add(model);
      const textureLoader = new THREE.TextureLoader();
      textureLoader.setCrossOrigin('anonymous');
      if (book.cover) textureLoader.load(book.cover, texture => {
        if (disposed) { texture.dispose(); return; }
        texture.colorSpace = THREE.SRGBColorSpace;
        front.map = texture;
        front.needsUpdate = true;
        fallback.dispose();
        setState('ready');
      }, undefined, () => { if (!disposed) setState('ready'); });
      else setState('ready');
      let targetX = -0.1;
      let targetY = 0.12;
      let dragging = null;
      const down = event => { dragging = {x: event.clientX, y: event.clientY, rx: targetX, ry: targetY}; renderer.domElement.setPointerCapture?.(event.pointerId); };
      const move = event => {
        if (!dragging) return;
        targetY = dragging.ry + (event.clientX - dragging.x) * 0.012;
        targetX = Math.max(-0.55, Math.min(0.45, dragging.rx + (event.clientY - dragging.y) * 0.008));
      };
      const up = event => { dragging = null; renderer.domElement.releasePointerCapture?.(event.pointerId); };
      renderer.domElement.addEventListener('pointerdown', down);
      renderer.domElement.addEventListener('pointermove', move);
      renderer.domElement.addEventListener('pointerup', up);
      renderer.domElement.addEventListener('pointercancel', up);
      const resize = () => {
        const width = Math.max(1, host.clientWidth);
        const height = Math.max(1, host.clientHeight);
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
      };
      const observer = new ResizeObserver(resize);
      observer.observe(host);
      resize();
      const clock = new THREE.Clock();
      let frame = 0;
      const animate = () => {
        if (disposed) return;
        const delta = Math.min(clock.getDelta(), 0.05);
        model.rotation.x = THREE.MathUtils.damp(model.rotation.x, targetX, 4.5, delta);
        model.rotation.y = THREE.MathUtils.damp(model.rotation.y, targetY, 4.5, delta);
        model.position.y = Math.sin(clock.elapsedTime * 0.8) * 0.055;
        renderer.render(scene, camera);
        frame = requestAnimationFrame(animate);
      };
      animate();
      cleanup = () => {
        cancelAnimationFrame(frame);
        observer.disconnect();
        renderer.domElement.removeEventListener('pointerdown', down);
        renderer.domElement.removeEventListener('pointermove', move);
        renderer.domElement.removeEventListener('pointerup', up);
        renderer.domElement.removeEventListener('pointercancel', up);
        geometry.dispose();
        [cloth, edge, front].forEach(material => { material.map?.dispose(); material.dispose(); });
        renderer.dispose();
        renderer.domElement.remove();
      };
    }).catch(() => { if (!disposed) setState('fallback'); });
    return () => { disposed = true; cleanup(); };
  }, [book.id]);
  return <div className="bpd-book-model" ref={hostRef} data-render-state={state}><div className="bpd-book-fallback"><BooksPrototypeCover book={book} size="xl"/></div><span>Drag to rotate</span></div>;
};

var BooksPrototypePage = function BooksPrototypePage({page, side}) {
  return (
    <article className={'bar-page ' + side}>
      <span className="bar-page-kicker">{page.kicker}</span>
      <h3>{page.title}</h3>
      <p>{page.body}</p>
      {page.note && <blockquote>{page.note}</blockquote>}
      <footer><span>Vellum Books Agent</span><strong>{page.number}</strong></footer>
    </article>
  );
};

var BooksPrototypeReaderSpread = function BooksPrototypeReaderSpread({pages, index}) {
  const left = pages[index] || pages[0];
  const right = pages[index + 1] || pages[index] || pages[0];
  return <div className="bar-spread"><BooksPrototypePage page={left} side="left"/><BooksPrototypePage page={right} side="right"/></div>;
};

var BooksPrototypeOpenReader = function BooksPrototypeOpenReader({book, onClose, onAttach, onSkill, attached, skillState}) {
  const pages = React.useMemo(() => [
    {number: 1, kicker: book.collection, title: book.title, body: book.excerpt, note: `${book.author} / ${book.location}`},
    {number: 2, kicker: 'Idea map', title: book.tags.join(', '), body: `Books Agent indexes this section around ${book.tags.join(', ')}. These labels support retrieval; they are not treated as a complete interpretation of the author.`},
    {number: 3, kicker: 'Personal thread', title: 'Why this returned now', body: book.relevance, note: 'This connection remains revisable and separate from a confirmed user belief.'},
    {number: 4, kicker: 'Evidence boundary', title: book.location, body: 'The production reader will preserve EPUB locations, chapter structure, and bounded evidence so a Books Agent answer can point back to the exact passage it used.'},
    {number: 5, kicker: 'Books Agent', title: 'A question to carry forward', body: `Where does ${book.tags[0]} help you act more clearly, and where could it become an excuse to stop examining the situation?`},
    {number: 6, kicker: 'Reading record', title: book.progress ? `${book.progress}% complete` : 'Not started', body: 'Progress, annotations, and your response to the book remain private user intelligence. The text itself stays separate from what Vellum learns about you.'},
  ], [book.id]);
  const stageRef = React.useRef(null);
  const dragRef = React.useRef(null);
  const [spreadIndex, setSpreadIndex] = React.useState(0);
  const [turn, setTurn] = React.useState({dir: 'next', progress: 0, active: false});
  const [zoom, setZoom] = React.useState(1);
  const [size, setSize] = React.useState({width: 1, height: 1});
  const maxIndex = Math.max(0, pages.length - 2);
  const canPrev = spreadIndex > 0;
  const canNext = spreadIndex < maxIndex;

  React.useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return undefined;
    const update = () => {
      const rect = stage.getBoundingClientRect();
      const next = {width: rect.width, height: rect.height};
      setSize(next);
    };
    const observer = new ResizeObserver(update);
    observer.observe(stage);
    update();
    return () => observer.disconnect();
  }, []);

  const beginTurn = (event, dir) => {
    if ((dir === 'next' && !canNext) || (dir === 'prev' && !canPrev)) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = {x: event.clientX, dir, width: Math.max(260, stageRef.current?.clientWidth || 600), moved: 0};
    setTurn({dir, progress: 0.01, active: true});
  };
  const moveTurn = event => {
    const drag = dragRef.current;
    if (!drag) return;
    const dx = event.clientX - drag.x;
    drag.moved = Math.max(drag.moved, Math.abs(dx));
    const raw = drag.dir === 'next' ? -dx : dx;
    setTurn({dir: drag.dir, progress: Math.max(0.01, Math.min(1, raw / (drag.width * 0.42))), active: true});
  };
  const finishTurn = () => {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    const shouldCommit = drag.moved < 6 || turn.progress > 0.22;
    if (!shouldCommit) { setTurn({dir: drag.dir, progress: 0, active: false}); return; }
    setTurn({dir: drag.dir, progress: 1, active: true});
    window.setTimeout(() => {
      setSpreadIndex(index => Math.max(0, Math.min(maxIndex, index + (drag.dir === 'next' ? 2 : -2))));
      setTurn({dir: drag.dir, progress: 0, active: false});
    }, 310);
  };
  const turnWithButton = dir => {
    if ((dir === 'next' && !canNext) || (dir === 'prev' && !canPrev)) return;
    dragRef.current = {dir, moved: 0, width: size.width, x: 0};
    setTurn({dir, progress: 1, active: true});
    window.setTimeout(() => {
      setSpreadIndex(index => Math.max(0, Math.min(maxIndex, index + (dir === 'next' ? 2 : -2))));
      setTurn({dir, progress: 0, active: false});
      dragRef.current = null;
    }, 310);
  };
  return (
    <section className="bar-reader" aria-label={`Reading ${book.title}`}>
      <div className="bar-reader-top">
        <button type="button" className="bar-back" onClick={onClose}><span aria-hidden="true">&larr;</span>Back to shelf</button>
        <div className="bar-reader-title"><span>{book.author}</span><strong>{book.title}</strong></div>
        <div className="bar-reader-tools" role="toolbar" aria-label="Reader tools">
          <BooksPrototypeIconButton label="Zoom out" onClick={() => setZoom(value => Math.max(.88, +(value - .1).toFixed(2)))}><span aria-hidden="true">-</span></BooksPrototypeIconButton>
          <span>{Math.round(zoom * 100)}%</span>
          <BooksPrototypeIconButton label="Zoom in" onClick={() => setZoom(value => Math.min(1.28, +(value + .1).toFixed(2)))}><span aria-hidden="true">+</span></BooksPrototypeIconButton>
        </div>
      </div>
      <div className="bar-reader-stage" ref={stageRef}>
        <div className="bar-book-shadow" aria-hidden="true"/>
        <div className="bar-book-zoom" style={{transform: `translate(-50%,-50%) scale(${zoom})`}}>
          <BooksPrototypeReaderSpread pages={pages} index={spreadIndex}/>
          {turn.active && <div className={'bar-turning-sheet ' + turn.dir} aria-hidden="true">{Array.from({length: 14}, (_, strip) => {
            const local = Math.max(0, Math.min(1, turn.progress * 1.16 - strip * .012));
            const angle = (turn.dir === 'next' ? -1 : 1) * local * 180;
            const lift = Math.sin(local * Math.PI) * 22;
            return <i key={strip} style={{'--strip': strip, transform: `rotateY(${angle}deg) translateZ(${lift}px)`}}/>;
          })}</div>}
          <button type="button" className="bar-page-hit prev" aria-label="Drag or tap for previous pages" disabled={!canPrev} onPointerDown={event => beginTurn(event, 'prev')} onPointerMove={moveTurn} onPointerUp={finishTurn} onPointerCancel={finishTurn}/>
          <button type="button" className="bar-page-hit next" aria-label="Drag or tap for next pages" disabled={!canNext} onPointerDown={event => beginTurn(event, 'next')} onPointerMove={moveTurn} onPointerUp={finishTurn} onPointerCancel={finishTurn}/>
        </div>
        <button type="button" className="bar-reader-arrow prev" aria-label="Previous pages" disabled={!canPrev} onClick={() => turnWithButton('prev')}>&larr;</button>
        <button type="button" className="bar-reader-arrow next" aria-label="Next pages" disabled={!canNext} onClick={() => turnWithButton('next')}>&rarr;</button>
      </div>
      <div className="bar-reader-bottom">
        <span>Drag a page edge to turn</span>
        <strong>Pages {spreadIndex + 1}-{Math.min(spreadIndex + 2, pages.length)} of {pages.length}</strong>
        <div className="bar-reader-actions"><button type="button" onClick={onAttach}>{attached ? 'Added to chat' : 'Add to chat'}</button><button type="button" onClick={onSkill}>{skillState === 'Ready' ? 'Open skill' : 'Create skill'}</button></div>
      </div>
    </section>
  );
};

var BooksPrototypeDetail = function BooksPrototypeDetail({book, books, selectBook, onBack, onRead, onAttach, onSkill, attached, skillState}) {
  const palette = booksPrototypePalette(book);
  const detailRef = React.useRef(null);
  const chooseBook = id => {
    selectBook(id);
    detailRef.current?.scrollTo({top: 0, behavior: 'smooth'});
  };
  return (
    <main className="bpd-detail" ref={detailRef} style={{'--book-accent': palette.accent, '--book-bg': palette.background}}>
      <button type="button" className="bpd-back" onClick={onBack}><span aria-hidden="true">&larr;</span>Return to shelf</button>
      <aside className="bpd-rail" aria-label="Books in your collection">
        {books.map((candidate, index) => <button type="button" key={candidate.id} className={candidate.id === book.id ? 'active' : ''} onClick={() => chooseBook(candidate.id)} aria-label={`View ${candidate.title}`}><span>{String(index + 1).padStart(2, '0')}</span><i style={{background: booksPrototypePalette(candidate).accent}}/><strong>{candidate.title}</strong></button>)}
      </aside>
      <section className="bpd-hero">
        <BooksPrototypeBookModel3D book={book}/>
        <div className="bpd-intro">
          <span>{book.collection} / {book.year}</span>
          <h2>{book.title}</h2>
          <p className="bpd-author">{book.author}</p>
          <p>{book.excerpt}</p>
          <BooksPrototypeActions book={book} attached={attached} skillState={skillState} onRead={onRead} onAttach={onAttach} onSkill={onSkill}/>
        </div>
        <div className="bpd-scroll-cue"><span>Scroll to explore</span><i/></div>
      </section>
      <section className="bpd-story">
        <div><span>Published</span><strong>{book.year}</strong></div>
        <article><span>About the author</span><h3>{book.author}</h3><p>{book.author} approaches {book.tags.slice(0, 2).join(' and ')} through a voice shaped by the book's time, form, and central argument. Books Agent keeps that authorial perspective separate from your own beliefs.</p></article>
        <article><span>Why it is here</span><h3>A thread in your reading</h3><p>{book.relevance}</p></article>
      </section>
      <section className="bpd-summary">
        <div><span>About the book</span><h3>{book.location}</h3></div>
        <p>{book.excerpt} This edition is indexed by chapter and location so answers can return to bounded evidence instead of relying on an untraceable summary.</p>
      </section>
      <section className="bpd-quotes">
        <span>Ideas to revisit</span>
        <div>{book.tags.map((tag, index) => <blockquote key={tag}><strong>&ldquo;</strong><p>{index === 0 ? book.relevance : `How does ${tag} change when it moves from an idea into a daily practice?`}</p><cite>{book.title}</cite></blockquote>)}</div>
      </section>
      <section className="bpd-next">
        <span>Continue through your collection</span>
        <div>{books.filter(candidate => candidate.id !== book.id).slice(0, 5).map(candidate => <button type="button" key={candidate.id} onClick={() => chooseBook(candidate.id)}><BooksPrototypeCover book={candidate} size="md"/><strong>{candidate.title}</strong><small>{candidate.author}</small></button>)}</div>
      </section>
    </main>
  );
};

var BooksPrototypeLibrary = function BooksPrototypeLibrary(props) {
  const {books, selected, selectBook, query, collection, setCollection} = props;
  const [mode, setMode] = React.useState('shelf');
  const filtered = books.filter(book => {
    if (collection === 'Reading') return book.progress > 0 && book.progress < 100;
    if (collection === 'Skills ready') return book.skill === 'Ready';
    if (!['All books', 'Reading', 'Skills ready'].includes(collection)) return book.collection === collection;
    return true;
  });
  const visibleBooks = filtered.length ? filtered : books;
  React.useEffect(() => {
    if (visibleBooks.length && !visibleBooks.some(book => book.id === selected.id)) selectBook(visibleBooks[0].id);
  }, [query, collection, visibleBooks.map(book => book.id).join('|')]);
  if (mode === 'reader') return <BooksPrototypeOpenReader book={selected} onClose={() => setMode('detail')} onAttach={props.onAttach} onSkill={props.onSkill} attached={props.attached} skillState={props.skillState}/>;
  if (mode === 'detail') return <BooksPrototypeDetail {...props} books={visibleBooks} book={selected} onBack={() => setMode('shelf')} onRead={() => setMode('reader')}/>;
  return (
    <main className="bar-library">
      <div className="bar-library-copy">
        <h2>Your books, in motion.</h2>
        <p>{query ? `${filtered.length} books match your search.` : 'Move vertically through the shelf. Hover to bring a spine forward, then open it.'}</p>
      </div>
      <div className="bar-collections" role="toolbar" aria-label="Filter book collection">{['All books', 'Reading', 'Skills ready', 'Philosophy', 'Fiction', 'Psychology'].map(name => <button type="button" key={name} className={collection === name ? 'active' : ''} onClick={() => setCollection(name)}>{name}</button>)}</div>
      <BooksPrototypeShelf3D books={visibleBooks} selectedId={selected.id} onSelect={selectBook} onOpen={id => {selectBook(id); setMode('detail');}}/>
      <div className="bar-selected">
        <div><span>{selected.collection} / {selected.progress ? `${selected.progress}% read` : props.skillState}</span><h3>{selected.title}</h3><p>{selected.author}</p></div>
        <p>{selected.relevance}</p>
        <button type="button" onClick={() => setMode('detail')}>Explore book<IcChevR size={15}/></button>
      </div>
    </main>
  );
};

var BooksPrototypeView = function BooksPrototypeView({agentProps, DefaultAgentView}) {
  const params = new URLSearchParams(window.location.search);
  const requestedSurface = params.get('section');
  const initialSurface = ['chat', 'library', 'discovery', 'wisdom'].includes(requestedSurface) ? requestedSurface : 'library';
  const [surface, setSurfaceState] = React.useState(initialSurface);
  const [query, setQuery] = React.useState('');
  const [collection, setCollection] = React.useState('All books');
  const [selectedId, setSelectedId] = React.useState('meditations');
  const [addedBooks, setAddedBooks] = React.useState([]);
  const [attached, setAttached] = React.useState([]);
  const [skillStates, setSkillStates] = React.useState(() => Object.fromEntries(BOOKS_PROTOTYPE_BOOKS.map(book => [book.id, book.skill])));
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

  const updateUrl = nextSurface => {
    const next = new URL(window.location.href);
    next.searchParams.set('view', 'agent');
    next.searchParams.set('agent', 'books');
    next.searchParams.set('booksPrototype', '1');
    next.searchParams.set('section', nextSurface);
    next.searchParams.delete('variant');
    next.searchParams.delete('scale');
    window.history.replaceState({}, '', next);
  };
  const setSurface = value => { setSurfaceState(value); updateUrl(value); setAnnouncement(`${value} section opened`); };
  const selectBook = id => { setSelectedId(id); setAnnouncement(`${allBooks.find(book => book.id === id)?.title || 'Book'} selected`); };
  const attach = () => { setAttached(items => items.includes(selected.id) ? items : [...items, selected.id]); setAnnouncement(`${selected.title} added to the next chat`); };
  const createSkill = () => {
    if (selectedSkill === 'Ready') { setAnnouncement(`${selected.title} skill opened`); return; }
    setSkillStates(states => ({...states, [selected.id]: 'Compiling'}));
    setAnnouncement(`Creating a Book skill for ${selected.title}`);
    window.setTimeout(() => { setSkillStates(states => ({...states, [selected.id]: 'Ready'})); setAnnouncement(`${selected.title} skill is ready`); }, 1400);
  };
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
  const shared = {
    books,
    selected,
    selectBook,
    collection,
    setCollection,
    attached: attached.includes(selected.id),
    skillState: selectedSkill,
    onRead: () => setAnnouncement(`Reading ${selected.title}`),
    onAttach: attach,
    onSkill: createSkill,
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
        {surface === 'library' && <BooksPrototypeLibrary {...shared} query={query}/>}
      </div>
    </div>
  );
};
