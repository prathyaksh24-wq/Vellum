import * as THREE from 'three';

const MAX_BOOKS = 40;
const CHARCOAL = 0x141618;
const SPINE_COLORS = [
  0xc8665f,
  0x4d8789,
  0xc3a04e,
  0x5977a5,
  0x866d9b,
  0x6d8c68,
  0xd17d55,
  0x668b9f,
];

const noop = () => {};

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function getBooks(books) {
  return Array.isArray(books) ? books.slice(0, MAX_BOOKS) : [];
}

function getAuthors(book) {
  return Array.isArray(book?.authors) ? book.authors.filter(Boolean).join(', ') : '';
}

function getPublishedLabel(book) {
  const value = book?.published_at == null ? '' : String(book.published_at);
  const year = value.match(/\d{4}/)?.[0];
  return year || value;
}

function prefersReducedMotion() {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function fitText(ctx, value, maxWidth, family, weight, maxSize, minSize) {
  const text = String(value || '');
  if (!text) return '';
  for (let size = maxSize; size >= minSize; size -= 1) {
    ctx.font = `${weight} ${size}px ${family}`;
    if (ctx.measureText(text).width <= maxWidth) return text;
  }
  ctx.font = `${weight} ${minSize}px ${family}`;
  let shortened = text;
  while (shortened.length > 1 && ctx.measureText(`${shortened}...`).width > maxWidth) {
    shortened = shortened.slice(0, -1);
  }
  return shortened === text ? shortened : `${shortened.trimEnd()}...`;
}

function makeSpineTexture(book, color) {
  const canvas = document.createElement('canvas');
  canvas.width = 1200;
  canvas.height = 180;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  ctx.fillStyle = `#${color.toString(16).padStart(6, '0')}`;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = 'rgba(255,255,255,.14)';
  ctx.fillRect(0, 0, 10, canvas.height);
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'left';

  const author = fitText(ctx, getAuthors(book).toUpperCase(), 238, 'Arial', 500, 25, 11);
  ctx.fillStyle = '#f4f5f2';
  ctx.fillText(author, 42, 90, 238);

  const title = fitText(ctx, book?.title || '', 650, 'Georgia', 600, 36, 12);
  ctx.fillText(title, 330, 90, 650);

  const published = fitText(ctx, getPublishedLabel(book), 92, 'Arial', 500, 25, 11);
  ctx.textAlign = 'right';
  ctx.fillText(published, 1158, 90, 92);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function disposeMaterial(material) {
  if (!material) return;
  material.map?.dispose();
  material.dispose();
}

function disposeMesh(mesh) {
  mesh.geometry?.dispose();
  const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
  materials.forEach(disposeMaterial);
}

function addResizeHandling(host, resize) {
  const ResizeObserverClass = typeof ResizeObserver !== 'undefined' ? ResizeObserver : null;
  if (ResizeObserverClass) {
    const observer = new ResizeObserverClass(resize);
    observer.observe(host);
    return () => observer.disconnect();
  }
  window.addEventListener('resize', resize);
  return () => window.removeEventListener('resize', resize);
}

function fitCamera(camera, width, height, horizontalSpan, verticalSpan, minimumZ) {
  const aspect = width / Math.max(1, height);
  const fov = THREE.MathUtils.degToRad(camera.fov);
  const zForHeight = verticalSpan / (2 * Math.tan(fov / 2));
  const zForWidth = horizontalSpan / (2 * Math.tan(fov / 2) * Math.max(0.1, aspect));
  camera.position.z = Math.max(minimumZ, zForHeight, zForWidth);
  camera.aspect = aspect;
  camera.updateProjectionMatrix();
}

function emptyHandle() {
  return {dispose: noop, select: () => false};
}

export function createShelf(host, options = {}) {
  const books = getBooks(options.books);
  const onSelect = typeof options.onSelect === 'function' ? options.onSelect : noop;
  const onOpen = typeof options.onOpen === 'function' ? options.onOpen : noop;
  if (!host?.appendChild || typeof document === 'undefined' || !books.length) return emptyHandle();

  const selectedIndex = books.findIndex(book => book?.id === options.selectedId);
  const bookSpacing = 0.78;
  const initialIndex = selectedIndex >= 0 ? selectedIndex : 0;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(CHARCOAL);
  scene.fog = new THREE.Fog(CHARCOAL, 12, 42);
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
  camera.position.set(0, 0.05, 9.2);

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({antialias: true, alpha: false, powerPreference: 'high-performance'});
  } catch {
    host.dataset.renderState = 'fallback';
    return emptyHandle();
  }

  let disposed = false;
  let frame = 0;
  let observerCleanup = noop;
  const reducedMotion = prefersReducedMotion();
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.setAttribute('aria-hidden', 'true');
  renderer.domElement.style.display = 'block';
  renderer.domElement.style.width = '100%';
  renderer.domElement.style.height = '100%';
  renderer.domElement.style.touchAction = 'none';
  renderer.domElement.style.cursor = 'grab';
  host.appendChild(renderer.domElement);
  host.dataset.renderState = 'ready';

  scene.add(new THREE.HemisphereLight(0xf5f5ef, 0x25282b, 2.2));
  const key = new THREE.DirectionalLight(0xf6f2e8, 4.2);
  key.position.set(-4, 5, 8);
  key.castShadow = true;
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x9ab7c1, 1.6);
  rim.position.set(7, 2, 1);
  scene.add(rim);

  const shelf = new THREE.Group();
  scene.add(shelf);
  const bookMeshes = [];
  books.forEach((book, index) => {
    const color = SPINE_COLORS[index % SPINE_COLORS.length];
    const spineTexture = makeSpineTexture(book, color);
    const edge = new THREE.MeshStandardMaterial({color: 0xd8dcda, roughness: 0.82});
    const cloth = new THREE.MeshPhysicalMaterial({color, roughness: 0.68, clearcoat: 0.12});
    const spine = new THREE.MeshPhysicalMaterial({
      color: 0xffffff,
      map: spineTexture,
      roughness: 0.58,
      clearcoat: 0.16,
    });
    const width = 5.1 + (index % 3) * 0.42;
    const geometry = new THREE.BoxGeometry(width, 0.54, 1.24, 5, 1, 2);
    const mesh = new THREE.Mesh(geometry, [cloth, cloth, edge, edge, spine, cloth]);
    mesh.position.set((index % 2 ? -1 : 1) * 0.18, -index * bookSpacing, 0);
    mesh.rotation.z = (index % 2 ? -1 : 1) * 0.012;
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData = {
      bookId: book?.id,
      index,
      baseX: mesh.position.x,
      baseZ: mesh.position.z,
      baseRotation: mesh.rotation.z,
    };
    shelf.add(mesh);
    bookMeshes.push(mesh);
  });

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2(3, 3);
  const maxIndex = books.length - 1;
  let current = initialIndex;
  let targetOffset = current * bookSpacing;
  let offset = targetOffset;
  let hovered = -1;
  let pointerDown = null;

  const resize = () => {
    if (disposed) return;
    const width = Math.max(1, host.clientWidth || 1);
    const height = Math.max(1, host.clientHeight || 1);
    renderer.setSize(width, height, false);
    fitCamera(camera, width, height, 7.2, 4.4, 7.5);
    renderer.render(scene, camera);
  };

  const updatePointer = event => {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / Math.max(1, rect.height)) * 2 + 1;
  };

  const pick = event => {
    updatePointer(event);
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(bookMeshes, false)[0];
    return hit ? hit.object.userData.index : -1;
  };

  const notifySelection = index => {
    if (books[index]) onSelect(books[index].id);
  };

  const moveTo = (value, notify = true) => {
    current = clamp(Math.round(value), 0, maxIndex);
    targetOffset = current * bookSpacing;
    if (notify) notifySelection(current);
  };

  const select = id => {
    const index = books.findIndex(book => book?.id === id);
    if (index < 0) return false;
    moveTo(index);
    return true;
  };

  const onMove = event => {
    if (pointerDown) {
      const dy = event.clientY - pointerDown.y;
      pointerDown.moved = Math.max(pointerDown.moved, Math.abs(dy));
      targetOffset = clamp(pointerDown.offset - dy * 0.012, 0, maxIndex * bookSpacing);
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
    renderer.domElement.releasePointerCapture?.(event.pointerId);
    const picked = pick(event);
    if (drag.moved < 6 && picked >= 0) {
      moveTo(picked);
      onOpen(books[picked].id);
    } else {
      moveTo(targetOffset / bookSpacing);
    }
    renderer.domElement.style.cursor = hovered >= 0 ? 'pointer' : 'grab';
  };

  const onCancel = event => {
    if (pointerDown) {
      pointerDown = null;
      moveTo(targetOffset / bookSpacing);
    }
    renderer.domElement.releasePointerCapture?.(event.pointerId);
    renderer.domElement.style.cursor = 'grab';
  };

  const onLeave = () => {
    if (!pointerDown) {
      hovered = -1;
      renderer.domElement.style.cursor = 'grab';
    }
  };

  const onWheel = event => {
    event.preventDefault();
    const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
    targetOffset = clamp(targetOffset + delta * 0.005, 0, maxIndex * bookSpacing);
    current = clamp(Math.round(targetOffset / bookSpacing), 0, maxIndex);
    notifySelection(current);
  };

  renderer.domElement.addEventListener('pointermove', onMove);
  renderer.domElement.addEventListener('pointerdown', onDown);
  renderer.domElement.addEventListener('pointerup', onUp);
  renderer.domElement.addEventListener('pointercancel', onCancel);
  renderer.domElement.addEventListener('pointerleave', onLeave);
  renderer.domElement.addEventListener('wheel', onWheel, {passive: false});
  observerCleanup = addResizeHandling(host, resize);
  resize();

  const clock = new THREE.Clock();
  const animate = () => {
    if (disposed) return;
    const delta = Math.min(clock.getDelta(), 0.05);
    const settle = reducedMotion ? 1 : 8;
    let changed = Math.abs(offset - targetOffset) > 0.0001;
    offset = reducedMotion
      ? targetOffset
      : THREE.MathUtils.damp(offset, targetOffset, 5.5, delta);
    shelf.position.y = offset;
    bookMeshes.forEach((mesh, index) => {
      const active = index === hovered || index === current;
      const lift = reducedMotion ? 0 : active ? 0.34 : 0;
      const depth = reducedMotion ? 0 : index === hovered ? 0.52 : index === current ? 0.18 : 0;
      const rotation = reducedMotion ? 0 : index === hovered ? -0.025 : 0;
      changed ||= Math.abs(mesh.position.x - mesh.userData.baseX - lift) > 0.0001
        || Math.abs(mesh.position.z - mesh.userData.baseZ - depth) > 0.0001
        || Math.abs(mesh.rotation.z - mesh.userData.baseRotation - rotation) > 0.0001
        || Math.abs(mesh.rotation.y - (index === hovered ? -0.08 : 0)) > 0.0001;
      mesh.position.x = reducedMotion
        ? mesh.userData.baseX
        : THREE.MathUtils.damp(mesh.position.x, mesh.userData.baseX + lift, settle, delta);
      mesh.position.z = reducedMotion
        ? mesh.userData.baseZ
        : THREE.MathUtils.damp(mesh.position.z, mesh.userData.baseZ + depth, settle, delta);
      mesh.rotation.z = reducedMotion
        ? mesh.userData.baseRotation
        : THREE.MathUtils.damp(mesh.rotation.z, mesh.userData.baseRotation + rotation, settle, delta);
      mesh.rotation.y = reducedMotion ? 0 : THREE.MathUtils.damp(mesh.rotation.y, index === hovered ? -0.08 : 0, settle, delta);
    });
    if (changed) renderer.render(scene, camera);
    frame = requestAnimationFrame(animate);
  };
  animate();

  const dispose = () => {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    observerCleanup();
    renderer.domElement.removeEventListener('pointermove', onMove);
    renderer.domElement.removeEventListener('pointerdown', onDown);
    renderer.domElement.removeEventListener('pointerup', onUp);
    renderer.domElement.removeEventListener('pointercancel', onCancel);
    renderer.domElement.removeEventListener('pointerleave', onLeave);
    renderer.domElement.removeEventListener('wheel', onWheel);
    bookMeshes.forEach(disposeMesh);
    renderer.dispose();
    renderer.forceContextLoss?.();
    renderer.domElement.remove();
  };

  return {dispose, select};
}

export function createBook(host, options = {}) {
  const book = options.book;
  if (!host?.appendChild || typeof document === 'undefined' || !book) return emptyHandle();

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(CHARCOAL);
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
  camera.position.set(0, 0.05, 7.2);

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({antialias: true, alpha: false, powerPreference: 'high-performance'});
  } catch {
    host.dataset.renderState = 'fallback';
    return emptyHandle();
  }

  let disposed = false;
  let frame = 0;
  let observerCleanup = noop;
  let loadedTexture = null;
  const reducedMotion = prefersReducedMotion();
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.setAttribute('aria-hidden', 'true');
  renderer.domElement.style.display = 'block';
  renderer.domElement.style.width = '100%';
  renderer.domElement.style.height = '100%';
  renderer.domElement.style.touchAction = 'none';
  renderer.domElement.style.cursor = 'grab';
  host.appendChild(renderer.domElement);
  host.dataset.renderState = 'loading';

  scene.add(new THREE.HemisphereLight(0xf4f5ef, 0x25282b, 2.8));
  const key = new THREE.DirectionalLight(0xf8f6ef, 4.2);
  key.position.set(-3, 5, 6);
  key.castShadow = true;
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x9ab7c1, 1.4);
  rim.position.set(4, 2, 2);
  scene.add(rim);

  const group = new THREE.Group();
  scene.add(group);
  const paletteColor = SPINE_COLORS[0];
  const edge = new THREE.MeshStandardMaterial({color: 0xd8dcda, roughness: 0.76});
  const cloth = new THREE.MeshPhysicalMaterial({color: paletteColor, roughness: 0.62, clearcoat: 0.16});
  const front = new THREE.MeshStandardMaterial({color: 0x70777b, roughness: 0.86});
  const geometry = new THREE.BoxGeometry(2.5, 3.8, 0.34, 2, 3, 1);
  const model = new THREE.Mesh(geometry, [cloth, cloth, edge, edge, front, cloth]);
  model.castShadow = true;
  model.rotation.set(-0.1, -0.9, -0.06);
  group.add(model);

  const resize = () => {
    if (disposed) return;
    const width = Math.max(1, host.clientWidth || 1);
    const height = Math.max(1, host.clientHeight || 1);
    renderer.setSize(width, height, false);
    fitCamera(camera, width, height, 3.6, 4.7, 6.4);
    renderer.render(scene, camera);
  };

  const textureLoader = new THREE.TextureLoader();
  textureLoader.setCrossOrigin('anonymous');
  if (book.cover_url) {
    textureLoader.load(book.cover_url, texture => {
      if (disposed) {
        texture.dispose();
        return;
      }
      loadedTexture = texture;
      texture.colorSpace = THREE.SRGBColorSpace;
      front.color.set(0xffffff);
      front.map = texture;
      front.needsUpdate = true;
      host.dataset.renderState = 'ready';
      renderer.render(scene, camera);
    }, undefined, () => {
      if (!disposed) host.dataset.renderState = 'ready';
    });
  } else {
    host.dataset.renderState = 'ready';
  }

  let targetX = -0.1;
  let targetY = 0.12;
  let dragging = null;
  const down = event => {
    dragging = {x: event.clientX, y: event.clientY, rx: targetX, ry: targetY};
    renderer.domElement.setPointerCapture?.(event.pointerId);
    renderer.domElement.style.cursor = 'grabbing';
  };
  const move = event => {
    if (!dragging) return;
    targetY = dragging.ry + (event.clientX - dragging.x) * 0.012;
    targetX = clamp(dragging.rx + (event.clientY - dragging.y) * 0.008, -0.55, 0.45);
  };
  const up = event => {
    dragging = null;
    renderer.domElement.releasePointerCapture?.(event.pointerId);
    renderer.domElement.style.cursor = 'grab';
  };
  renderer.domElement.addEventListener('pointerdown', down);
  renderer.domElement.addEventListener('pointermove', move);
  renderer.domElement.addEventListener('pointerup', up);
  renderer.domElement.addEventListener('pointercancel', up);
  observerCleanup = addResizeHandling(host, resize);
  resize();

  const clock = new THREE.Clock();
  const animate = () => {
    if (disposed) return;
    const delta = Math.min(clock.getDelta(), 0.05);
    const changed = Math.abs(model.rotation.x - targetX) > 0.0001 || Math.abs(model.rotation.y - targetY) > 0.0001;
    model.rotation.x = reducedMotion ? targetX : THREE.MathUtils.damp(model.rotation.x, targetX, 4.5, delta);
    model.rotation.y = reducedMotion ? targetY : THREE.MathUtils.damp(model.rotation.y, targetY, 4.5, delta);
    if (changed) renderer.render(scene, camera);
    frame = requestAnimationFrame(animate);
  };
  animate();

  const select = id => {
    if (id !== book.id) return false;
    targetX = -0.1;
    targetY = 0.12;
    return true;
  };

  const dispose = () => {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    observerCleanup();
    renderer.domElement.removeEventListener('pointerdown', down);
    renderer.domElement.removeEventListener('pointermove', move);
    renderer.domElement.removeEventListener('pointerup', up);
    renderer.domElement.removeEventListener('pointercancel', up);
    loadedTexture?.dispose();
    disposeMesh(model);
    renderer.dispose();
    renderer.forceContextLoss?.();
    renderer.domElement.remove();
  };

  return {dispose, select};
}
