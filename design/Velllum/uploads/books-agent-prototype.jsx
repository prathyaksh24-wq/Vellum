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
  A: 'Press shelf',
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

var BOOKS_PROTOTYPE_COLORS = ['#7c2f2c', '#1f4b43', '#c36e2d', '#243d68', '#8a6a36', '#75455f', '#2d665d', '#6f382b'];

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
      scene.background = new THREE.Color(0xe4e5e2);
      scene.fog = new THREE.Fog(0xe4e5e2, 10, 22);
      const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
      camera.position.set(0, 0.25, 7.4);
      const renderer = new THREE.WebGLRenderer({antialias: true, alpha: false, powerPreference: 'high-performance'});
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      renderer.domElement.className = 'bar-webgl';
      renderer.domElement.setAttribute('aria-hidden', 'true');
      host.appendChild(renderer.domElement);

      const ambient = new THREE.HemisphereLight(0xfffbef, 0x59483b, 2.4);
      scene.add(ambient);
      const key = new THREE.DirectionalLight(0xfff2da, 4.4);
      key.position.set(-3, 6, 7);
      key.castShadow = true;
      scene.add(key);
      const rim = new THREE.DirectionalLight(0xb8d1dc, 2.1);
      rim.position.set(7, 2, 1);
      scene.add(rim);

      const shelf = new THREE.Group();
      scene.add(shelf);
      const bookMeshes = [];
      const textureLoader = new THREE.TextureLoader();
      textureLoader.setCrossOrigin('anonymous');
      const bookSpacing = 1.32;
      const baseX = -1.45;

      const makeLabelTexture = (book, color) => {
        const canvas = document.createElement('canvas');
        canvas.width = 512;
        canvas.height = 768;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = color;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.strokeStyle = 'rgba(255,255,255,.5)';
        ctx.lineWidth = 4;
        ctx.strokeRect(32, 32, canvas.width - 64, canvas.height - 64);
        ctx.fillStyle = '#fffaf0';
        ctx.textAlign = 'center';
        ctx.font = '600 42px Georgia';
        const words = book.title.split(' ');
        let line = '';
        let y = 270;
        words.forEach(word => {
          const next = `${line} ${word}`.trim();
          if (ctx.measureText(next).width > 390 && line) {
            ctx.fillText(line, 256, y);
            line = word;
            y += 54;
          } else line = next;
        });
        ctx.fillText(line, 256, y);
        ctx.font = '22px Arial';
        ctx.fillText(book.author.toUpperCase(), 256, 650);
        const texture = new THREE.CanvasTexture(canvas);
        texture.colorSpace = THREE.SRGBColorSpace;
        return texture;
      };

      const coverGeometry = new THREE.BoxGeometry(1.02, 1.58, 0.2, 2, 3, 1);
      books.forEach((book, index) => {
        const color = BOOKS_PROTOTYPE_COLORS[index % BOOKS_PROTOTYPE_COLORS.length];
        const fallbackTexture = makeLabelTexture(book, color);
        const edge = new THREE.MeshStandardMaterial({color: 0xe8dcc6, roughness: 0.82});
        const cloth = new THREE.MeshPhysicalMaterial({color, roughness: 0.72, clearcoat: 0.08});
        const front = new THREE.MeshPhysicalMaterial({map: fallbackTexture, roughness: 0.62, clearcoat: 0.12});
        const mesh = new THREE.Mesh(coverGeometry, [cloth, cloth, edge, edge, front, cloth]);
        mesh.position.set(baseX + index * bookSpacing, -0.05 + (index % 3) * 0.018, 0);
        mesh.rotation.y = (index % 2 ? -1 : 1) * 0.035;
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        mesh.userData = {bookId: book.id, index, baseY: mesh.position.y, baseRotation: mesh.rotation.y, material: front};
        shelf.add(mesh);
        bookMeshes.push(mesh);
        if (book.cover) {
          textureLoader.load(book.cover, texture => {
            if (disposed) { texture.dispose(); return; }
            texture.colorSpace = THREE.SRGBColorSpace;
            texture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
            front.map = texture;
            front.needsUpdate = true;
            fallbackTexture.dispose();
          }, undefined, () => {});
        }
      });

      const board = new THREE.Mesh(
        new THREE.BoxGeometry(Math.max(11, books.length * bookSpacing + 2.8), 0.24, 2.15),
        new THREE.MeshStandardMaterial({color: 0x5b3825, roughness: 0.7})
      );
      board.position.set(baseX + ((books.length - 1) * bookSpacing) / 2, -1.03, -0.08);
      board.receiveShadow = true;
      shelf.add(board);
      const backdrop = new THREE.Mesh(
        new THREE.PlaneGeometry(28, 11),
        new THREE.MeshStandardMaterial({color: 0xe4e5e2, roughness: 1})
      );
      backdrop.position.set(2, 0, -2.1);
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
          const dx = event.clientX - pointerDown.x;
          pointerDown.moved = Math.max(pointerDown.moved, Math.abs(dx));
          targetOffset = Math.max(0, Math.min(maxIndex * bookSpacing, pointerDown.offset - dx * 0.012));
          return;
        }
        hovered = pick(event);
        renderer.domElement.style.cursor = hovered >= 0 ? 'pointer' : 'grab';
      };
      const onDown = event => {
        pointerDown = {x: event.clientX, offset: targetOffset, moved: 0};
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
        shelf.position.x = -offset;
        bookMeshes.forEach((mesh, index) => {
          const raised = index === hovered ? 0.24 : index === current ? 0.1 : 0;
          mesh.position.y = THREE.MathUtils.damp(mesh.position.y, mesh.userData.baseY + raised, 8, delta);
          mesh.position.z = THREE.MathUtils.damp(mesh.position.z, index === hovered ? 0.35 : index === current ? 0.14 : 0, 8, delta);
          mesh.rotation.y = THREE.MathUtils.damp(mesh.rotation.y, mesh.userData.baseRotation + (index === hovered ? -0.16 : 0), 8, delta);
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
        board.geometry.dispose();
        board.material.dispose();
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
      <div className={'bar-shelf-fallback ' + (loadState === 'ready' ? 'webgl-ready' : '')}>{books.map((book, index) => <button type="button" key={book.id} aria-label={`Open ${book.title}`} onClick={() => {moveRef.current?.(index); onOpen(book.id);}}><BooksPrototypeCover book={book} size="lg"/></button>)}</div>
      <div className="bar-shelf-controls">
        <BooksPrototypeIconButton label="Previous book" onClick={() => move(-1)}><span aria-hidden="true">&larr;</span></BooksPrototypeIconButton>
        <span><strong>{String(activeIndex + 1).padStart(2, '0')}</strong> / {String(books.length).padStart(2, '0')}</span>
        <BooksPrototypeIconButton label="Next book" onClick={() => move(1)}><span aria-hidden="true">&rarr;</span></BooksPrototypeIconButton>
      </div>
      <div className="bar-shelf-access" aria-label="Books on shelf">{books.map((book, index) => <button type="button" key={book.id} className={index === activeIndex ? 'active' : ''} onFocus={() => moveRef.current?.(index)} onClick={() => onOpen(book.id)}>{book.title}</button>)}</div>
    </div>
  );
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
  const [loupeOn, setLoupeOn] = React.useState(true);
  const [loupe, setLoupe] = React.useState({x: 0, y: 0, placed: false});
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
      setLoupe(current => current.placed ? current : {x: rect.width * 0.69, y: rect.height * 0.5, placed: true});
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
    setLoupe(current => ({...current, x: drag.dir === 'next' ? size.width * 0.28 : size.width * 0.72}));
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
  const moveLoupe = event => {
    if (!event.currentTarget.hasPointerCapture?.(event.pointerId)) return;
    const rect = stageRef.current.getBoundingClientRect();
    setLoupe({x: Math.max(74, Math.min(rect.width - 74, event.clientX - rect.left)), y: Math.max(74, Math.min(rect.height - 74, event.clientY - rect.top)), placed: true});
  };
  const lensRadius = 86;
  const lensMagnification = 1.9;

  return (
    <section className="bar-reader" aria-label={`Reading ${book.title}`}>
      <div className="bar-reader-top">
        <button type="button" className="bar-back" onClick={onClose}><span aria-hidden="true">&larr;</span>Back to shelf</button>
        <div className="bar-reader-title"><span>{book.author}</span><strong>{book.title}</strong></div>
        <div className="bar-reader-tools" role="toolbar" aria-label="Reader tools">
          <BooksPrototypeIconButton label="Zoom out" onClick={() => setZoom(value => Math.max(.88, +(value - .1).toFixed(2)))}><span aria-hidden="true">-</span></BooksPrototypeIconButton>
          <span>{Math.round(zoom * 100)}%</span>
          <BooksPrototypeIconButton label="Zoom in" onClick={() => setZoom(value => Math.min(1.28, +(value + .1).toFixed(2)))}><span aria-hidden="true">+</span></BooksPrototypeIconButton>
          <BooksPrototypeIconButton label="Toggle magnifier" pressed={loupeOn} onClick={() => setLoupeOn(value => !value)}><IcSearch size={15}/></BooksPrototypeIconButton>
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
        {loupeOn && <div className="bar-loupe" style={{left: loupe.x - lensRadius, top: loupe.y - lensRadius}} onPointerDown={event => {event.preventDefault(); event.stopPropagation(); event.currentTarget.setPointerCapture?.(event.pointerId);}} onPointerMove={moveLoupe} onPointerUp={event => event.currentTarget.releasePointerCapture?.(event.pointerId)}>
          <div className="bar-lens">
            <div className="bar-lens-scene" style={{width: size.width, height: size.height, transform: `translate(${lensRadius - loupe.x * lensMagnification}px,${lensRadius - loupe.y * lensMagnification}px) scale(${lensMagnification})`}}>
              <div className="bar-book-zoom lens-copy" style={{transform: `translate(-50%,-50%) scale(${zoom})`}}><BooksPrototypeReaderSpread pages={pages} index={spreadIndex}/></div>
            </div>
          </div>
          <span className="bar-loupe-handle" aria-hidden="true"/>
        </div>}
        <button type="button" className="bar-reader-arrow prev" aria-label="Previous pages" disabled={!canPrev} onClick={() => turnWithButton('prev')}>&larr;</button>
        <button type="button" className="bar-reader-arrow next" aria-label="Next pages" disabled={!canNext} onClick={() => turnWithButton('next')}>&rarr;</button>
      </div>
      <div className="bar-reader-bottom">
        <span>Drag a page edge to turn / drag the glass to inspect</span>
        <strong>Pages {spreadIndex + 1}-{Math.min(spreadIndex + 2, pages.length)} of {pages.length}</strong>
        <div className="bar-reader-actions"><button type="button" onClick={onAttach}>{attached ? 'Added to chat' : 'Add to chat'}</button><button type="button" onClick={onSkill}>{skillState === 'Ready' ? 'Open skill' : 'Create skill'}</button></div>
      </div>
    </section>
  );
};

var BooksPrototypeVariantA = function BooksPrototypeVariantA(props) {
  const {books, selected, selectBook, query, collection, setCollection} = props;
  const [openId, setOpenId] = React.useState(null);
  const filtered = books.filter(book => {
    if (collection === 'Reading') return book.progress > 0 && book.progress < 100;
    if (collection === 'Skills ready') return book.skill === 'Ready';
    if (!['All books', 'Reading', 'Skills ready'].includes(collection)) return book.collection === collection;
    return true;
  });
  const opened = books.find(book => book.id === openId) || selected;
  if (openId) {
    return <BooksPrototypeOpenReader book={opened} onClose={() => setOpenId(null)} onAttach={props.onAttach} onSkill={props.onSkill} attached={props.attached} skillState={props.skillState}/>;
  }
  return (
    <main className="bar-library">
      <div className="bar-library-copy">
        <span className="blp-overline">Your collection</span>
        <h2>A shelf that remembers why each book matters.</h2>
        <p>{query ? `${filtered.length} books match your search.` : 'Scroll horizontally, drag the shelf, or select a cover. Open any volume to read and turn its pages.'}</p>
      </div>
      <div className="bar-collections" role="toolbar" aria-label="Filter book collection">{['All books', 'Reading', 'Skills ready', 'Philosophy', 'Fiction', 'Psychology'].map(name => <button type="button" key={name} className={collection === name ? 'active' : ''} onClick={() => setCollection(name)}>{name}</button>)}</div>
      <BooksPrototypeShelf3D books={filtered.length ? filtered : books} selectedId={selected.id} onSelect={selectBook} onOpen={id => {selectBook(id); setOpenId(id);}}/>
      <div className="bar-selected">
        <div><span>{selected.collection} / {selected.progress ? `${selected.progress}% read` : selected.skill}</span><h3>{selected.title}</h3><p>{selected.author}</p></div>
        <p>{selected.relevance}</p>
        <button type="button" onClick={() => setOpenId(selected.id)}>Open book<IcChevR size={15}/></button>
      </div>
    </main>
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
