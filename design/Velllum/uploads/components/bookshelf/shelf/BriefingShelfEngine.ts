import {
  ACESFilmicToneMapping,
  AdditiveBlending,
  BoxGeometry,
  Box3,
  CanvasTexture,
  Color,
  CylinderGeometry,
  DirectionalLight,
  Fog,
  Group,
  HemisphereLight,
  LinearMipmapLinearFilter,
  MathUtils,
  Mesh,
  MeshBasicMaterial,
  MeshPhysicalMaterial,
  MeshStandardMaterial,
  PCFShadowMap,
  PerspectiveCamera,
  PlaneGeometry,
  PointLight,
  Raycaster,
  SRGBColorSpace,
  Scene,
  ShaderMaterial,
  ShadowMaterial,
  Texture,
  TextureLoader,
  Vector2,
  Vector3,
  WebGLRenderer,
} from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import {
  focusOriginPose,
  focusedBookOpenPose,
  openTransitionPhases,
  spreadCoverAngle,
  type PageScreenRect,
} from "./book-open-motion";
import {
  bookFootprintsOverlap,
  browseMotionPose,
  browsePhaseDuration,
  createMotionLayout,
  peekToPresentedPose,
  presentedBookPose,
  scrollLiftPose,
  scrollProximityLift,
  shelvedBookPose,
  type BookFootprint,
  type BookPose,
  type BrowseMotionPhase,
  type MotionLayout,
} from "./book-motion";
import {
  createBackCover,
  createFrontCover,
  createPlaceholderFront,
  createPlaceholderSpine,
  createSpineCover,
} from "./brief-cover-art";
import type { ShelfBriefBook } from "./types";
import { buildWeekBuckets, type WeekBucket } from "./week-layout";

export type ShelfMode = "browse" | "focusing" | "open" | "returning";

export type BookOpenTransition = {
  progress: number;
  spread: number;
  expand: number;
  /** Screen rect of the open page — overlay content is placed here. */
  readerRect: PageScreenRect | null;
  pageColor: string;
  viewport: { width: number; height: number };
};

type ShelfCallbacks = {
  onActiveIndex: (index: number) => void;
  onMode: (mode: ShelfMode, selectedIndex: number | null) => void;
  onReady: () => void;
  onTransition?: (transition: BookOpenTransition) => void;
};

export type ShelfEngineBootOptions = {
  /** Volume to present (and optionally open) on first paint. */
  initialIndex?: number;
  /** Today's book — stronger living shimmer + warm light. */
  spotlightIndex?: number | null;
  /** Skip open animation and land in reader mode. */
  openImmediate?: boolean;
  /** After first close, paint the cover then shelve onto the row. */
  ceremonyOnReturn?: boolean;
  /** Start on the dark scene palette (room lights switch live via setTheme). */
  dark?: boolean;
};

type RuntimeBook = {
  data: ShelfBriefBook;
  index: number;
  slot: InstanceType<typeof Group>;
  content: InstanceType<typeof Group>;
  inspectionIdle: InstanceType<typeof Group>;
  physical: InstanceType<typeof Group>;
  frontSurface: InstanceType<typeof Mesh> & {
    material: InstanceType<typeof MeshPhysicalMaterial>;
  };
  spineSurface: InstanceType<typeof Mesh> & {
    material: InstanceType<typeof MeshPhysicalMaterial>;
  };
  backSurface: InstanceType<typeof Mesh> & {
    material: InstanceType<typeof MeshStandardMaterial>;
  };
  boardMaterial: InstanceType<typeof MeshPhysicalMaterial>;
  headbandMaterial: InstanceType<typeof MeshPhysicalMaterial>;
  coverHinge: InstanceType<typeof Group>;
  openPage: InstanceType<typeof Mesh>;
  pageBlock: InstanceType<typeof Mesh>;
  spineBoard: InstanceType<typeof Mesh>;
  backBoard: InstanceType<typeof Mesh>;
  headbandTop: InstanceType<typeof Mesh>;
  headbandBottom: InstanceType<typeof Mesh>;
  rightHinge: InstanceType<typeof Group>;
  leftPage: InstanceType<typeof Mesh>;
  rightPage: InstanceType<typeof Mesh>;
  pickProxy: InstanceType<typeof Mesh>;
  livingMaterial?: InstanceType<typeof ShaderMaterial>;
  x: number;
  width: number;
  weekIndex: number;
  pose: BookPose;
  hover: number;
  targetHover: number;
  idleAmount: number;
  textures: InstanceType<typeof Texture>[];
};

const PAPER = "#f2eee6";
const shelfTop = 0.34;
const shelfRowPitch = 2.55;
const browseCamera = new Vector3(0, 1.42, 6.65);
const browseTarget = new Vector3(0, 1.28, 0.15);
const pageColor = new Color("#e9dfca");
const shelfColor = new Color("#5a4132");

/**
 * Scene palette per app theme. The light values are the reference design,
 * untouched; the dark variant keeps the same warm wood + candle-lit mood
 * on a near-black paper so the shelf stays cozy rather than washed out.
 */
const SCENE_THEMES = {
  light: {
    paper: "#f2eee6",
    ground: "#e7dfd0",
    hemisphereSky: "#fff8ea",
    hemisphereGround: "#6e5848",
    hemisphereIntensity: 2.4,
    keyColor: "#fff6e7",
    keyIntensity: 4.6,
    rimColor: "#c8d5e5",
    rimIntensity: 2.1,
    bounceColor: "#d79b72",
    bounceIntensity: 1.2,
    exposure: 1.03,
  },
  dark: {
    paper: "#161210",
    ground: "#1e1815",
    hemisphereSky: "#554a40",
    hemisphereGround: "#26201a",
    hemisphereIntensity: 2.0,
    keyColor: "#ffe9c9",
    keyIntensity: 3.6,
    rimColor: "#5d6a7c",
    rimIntensity: 1.75,
    bounceColor: "#c9885c",
    bounceIntensity: 1.5,
    exposure: 1.02,
  },
} as const;

export type SceneThemeName = keyof typeof SCENE_THEMES;
const clamp = MathUtils.clamp;
/** Mint uses 0.46 / 0.34; slightly longer here for cover-spread + reader overlay. */
const focusInDuration = 0.58;
const focusOutDuration = 0.42;
const inspectionIdleLift = 0.014;
const inspectionIdlePitch = MathUtils.degToRad(0.28);
const inspectionIdleYaw = MathUtils.degToRad(0.48);
const inspectionIdleRoll = MathUtils.degToRad(0.22);
const scrollSettleMs = 180;
const scrollLiftRadius = 0.92;
const scrollIndexSnapMs = 100;
const scrollMomentumFriction = 6.2;
const scrollMomentumMin = 0.022;
const wheelScrollGain = 0.0039;
const wheelMomentumGain = 9.5;

function damp(current: number, target: number, lambda: number, delta: number) {
  return MathUtils.damp(current, target, lambda, delta);
}

function easeOutCubic(value: number) {
  const t = 1 - clamp(value, 0, 1);
  return 1 - t * t * t;
}

function toTexture(
  canvas: HTMLCanvasElement,
  renderer: InstanceType<typeof WebGLRenderer>,
  anisotropy = 8,
) {
  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace;
  texture.anisotropy = Math.min(
    anisotropy,
    renderer.capabilities.getMaxAnisotropy(),
  );
  texture.generateMipmaps = true;
  texture.minFilter = LinearMipmapLinearFilter;
  return texture;
}

function createLivingMaterial(color: string, seed: number) {
  return new ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
    uniforms: {
      uTime: { value: 0 },
      uStrength: { value: 0 },
      uColor: { value: new Color(color) },
      uSeed: { value: seed },
    },
    vertexShader: `
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      varying vec2 vUv;
      uniform float uTime;
      uniform float uStrength;
      uniform float uSeed;
      uniform vec3 uColor;

      void main() {
        float t = uTime * (0.035 + fract(uSeed * 0.17) * 0.04);
        float band = fract(
          vUv.x * (0.55 + fract(uSeed) * 0.5) +
          vUv.y * (0.22 + fract(uSeed * 0.3) * 0.35) +
          t
        );
        float sheen = smoothstep(0.42, 0.5, band) * (1.0 - smoothstep(0.5, 0.58, band));
        float ripple = sin(
          (vUv.x + vUv.y) * (8.0 + fract(uSeed * 0.7) * 10.0) + t * 6.0
        ) * 0.5 + 0.5;
        float edge = smoothstep(0.0, 0.16, vUv.x) * smoothstep(1.0, 0.84, vUv.x)
          * smoothstep(0.0, 0.12, vUv.y) * smoothstep(1.0, 0.88, vUv.y);
        float alpha = (sheen * 0.85 + ripple * 0.18) * edge * uStrength * 0.38;
        gl_FragColor = vec4(uColor, alpha);
      }
    `,
  });
}

export class BriefingShelfEngine {
  private canvas: HTMLCanvasElement;
  private booksData: ShelfBriefBook[];
  private callbacks: ShelfCallbacks;
  private renderer: InstanceType<typeof WebGLRenderer>;
  private scene = new Scene();
  private camera: InstanceType<typeof PerspectiveCamera>;
  private controls: OrbitControls;
  private shelfGroup = new Group();
  private shelfFurniture = new Group();
  private ground: InstanceType<typeof Mesh> | null = null;
  private backWall: InstanceType<typeof Mesh> | null = null;
  private keyLight: InstanceType<typeof DirectionalLight> | null = null;
  private spotlightLight: InstanceType<typeof PointLight> | null = null;
  private hemisphereLight: InstanceType<typeof HemisphereLight> | null = null;
  private rimLight: InstanceType<typeof DirectionalLight> | null = null;
  private bounceLight: InstanceType<typeof PointLight> | null = null;
  private sceneTheme: SceneThemeName = "light";
  private runtimeBooks: RuntimeBook[] = [];
  private spotlightIndex: number | null = null;
  private ceremonyOnReturn = false;
  private revealPhase: "idle" | "paint" | "shelve" = "idle";
  private revealProgress = 0;
  private revealBookIndex: number | null = null;
  private pickTargets: InstanceType<typeof Mesh>[] = [];
  private raycaster = new Raycaster();
  private pointer = new Vector2(10, 10);
  private animationFrame = 0;
  private resizeObserver: ResizeObserver;
  private mode: ShelfMode = "browse";
  private selectedIndex: number | null = null;
  private activeIndex = 0;
  private presentTargetIndex = 0;
  private presentedIndex: number | null = 0;
  private pendingFocusIndex: number | null = null;
  private browseMotionPhase: BrowseMotionPhase | "idle" = "idle";
  private browseMotionProgress = 0;
  private presentFromLift = 1;
  private motionBookIndex: number | null = null;
  private motionLayout: MotionLayout = createMotionLayout([]);
  private weekBuckets: WeekBucket[] = [];
  private coverUpgradeQueue: number[] = [];
  private scrollIndex = 0;
  private targetScrollIndex = 0;
  private scrollVelocity = 0;
  private focusProgress = 0;
  private focusCameraPosition = new Vector3();
  private focusCameraTarget = new Vector3();
  private lastInputTime = 0;
  private pointerDown = false;
  private pointerId: number | null = null;
  private pointerStartX = 0;
  private pointerLastX = 0;
  private pointerLastMoveTime = 0;
  private pointerTravel = 0;
  private reducedMotion = false;
  private responsiveBrowseCamera = browseCamera.clone();
  private lastTimestamp = 0;
  private wasScrolling = false;
  private isDisposed = false;
  private bootOpenImmediate = false;

  constructor(
    canvas: HTMLCanvasElement,
    books: ShelfBriefBook[],
    callbacks: ShelfCallbacks,
    boot: ShelfEngineBootOptions = {},
  ) {
    this.canvas = canvas;
    this.booksData = books;
    this.callbacks = callbacks;
    this.spotlightIndex =
      boot.spotlightIndex === undefined ? null : boot.spotlightIndex;
    this.ceremonyOnReturn = !!boot.ceremonyOnReturn;
    this.bootOpenImmediate = !!boot.openImmediate;
    this.sceneTheme = boot.dark ? "dark" : "light";
    const bootIndex = clamp(
      Math.round(boot.initialIndex ?? 0),
      0,
      Math.max(0, books.length - 1),
    );
    this.activeIndex = bootIndex;
    this.presentTargetIndex = bootIndex;
    this.presentedIndex = bootIndex;
    this.scrollIndex = bootIndex;
    this.targetScrollIndex = bootIndex;
    this.reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    this.renderer = new WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    this.renderer.outputColorSpace = SRGBColorSpace;
    this.renderer.toneMapping = ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.03;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = PCFShadowMap;

    this.camera = new PerspectiveCamera(27, 1, 0.08, 80);
    this.camera.position.copy(browseCamera);
    this.camera.lookAt(browseTarget);

    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enabled = false;
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.075;
    this.controls.enablePan = true;
    this.controls.screenSpacePanning = true;
    this.controls.enableZoom = true;
    this.controls.minDistance = 2.7;
    this.controls.maxDistance = 7.2;
    this.controls.minPolarAngle = Math.PI * 0.22;
    this.controls.maxPolarAngle = Math.PI * 0.78;

    this.resizeObserver = new ResizeObserver(this.handleResize);
    this.setupScene();
    this.createBooks();
    this.bindEvents();
    this.resizeObserver.observe(canvas);
    this.handleResize();
    if (this.bootOpenImmediate) {
      this.snapOpenImmediate(this.activeIndex);
    }
    this.callbacks.onReady();
    this.animate();
    // Upgrade placeholder covers after the first frame so the shelf isn't blank.
    queueMicrotask(() => this.scheduleCoverUpgrades());
  }

  private setupScene() {
    const theme = SCENE_THEMES[this.sceneTheme];
    this.scene.background = new Color(theme.paper);
    this.scene.fog = new Fog(theme.paper, 10, 26);

    const hemisphere = new HemisphereLight(
      theme.hemisphereSky,
      theme.hemisphereGround,
      theme.hemisphereIntensity,
    );
    this.scene.add(hemisphere);
    this.hemisphereLight = hemisphere;

    const key = new DirectionalLight(theme.keyColor, theme.keyIntensity);
    key.position.set(-4.2, 7.4, 5.5);
    key.castShadow = true;
    key.shadow.mapSize.set(512, 512);
    key.shadow.camera.left = -10;
    key.shadow.camera.right = 10;
    key.shadow.camera.top = 8;
    key.shadow.camera.bottom = -12;
    key.shadow.camera.near = 0.5;
    key.shadow.camera.far = 40;
    key.shadow.bias = -0.0005;
    this.scene.add(key);
    this.keyLight = key;

    const rim = new DirectionalLight(theme.rimColor, theme.rimIntensity);
    rim.position.set(5, 3, -4);
    this.scene.add(rim);
    this.rimLight = rim;

    const warmBounce = new PointLight(
      theme.bounceColor,
      theme.bounceIntensity,
      10,
      2,
    );
    warmBounce.position.set(-3, 0.4, 3.2);
    this.scene.add(warmBounce);
    this.bounceLight = warmBounce;

    const spotlight = new PointLight("#ffe6bc", 0, 7.2, 1.65);
    spotlight.position.set(0, 1.6, 1.4);
    this.scene.add(spotlight);
    this.spotlightLight = spotlight;

    const wall = new Mesh(
      new PlaneGeometry(40, 40),
      new MeshStandardMaterial({
        color: theme.paper,
        roughness: 1,
        metalness: 0,
      }),
    );
    wall.position.set(0, 0, -3.2);
    wall.receiveShadow = true;
    this.scene.add(wall);
    this.backWall = wall;

    // Placed/resized after week rows are known — a fixed ground was
    // clipping through lower shelves and reading as a false floor.
    const ground = new Mesh(
      new PlaneGeometry(48, 36),
      new MeshStandardMaterial({
        color: theme.ground,
        roughness: 0.94,
        metalness: 0,
      }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.5;
    ground.receiveShadow = true;
    this.scene.add(ground);
    this.ground = ground;

    this.scene.add(this.shelfGroup);
    this.shelfGroup.add(this.shelfFurniture);
    this.matchVellumBackground();
  }

  /** Vellum owns the room color; transparent receivers retain the supplied shadows. */
  matchVellumBackground() {
    this.scene.background=null;
    this.scene.fog=null;
    this.renderer.setClearColor(0x000000,0);
    for(const surface of [this.backWall,this.ground]) {
      if(!surface) continue;
      if(!(surface.material instanceof ShadowMaterial)) {
        (surface.material as InstanceType<typeof MeshStandardMaterial>).dispose();
        surface.material=new ShadowMaterial({color:0x000000,opacity:this.sceneTheme==='dark'?.24:.14});
      } else {
        surface.material.color.set('#000000');
        surface.material.opacity=this.sceneTheme==='dark'?.24:.14;
      }
    }
  }

  /** Swap the room palette live (light = reference design, dark = candle-lit). */
  setTheme(theme: SceneThemeName) {
    if (theme === this.sceneTheme) return;
    this.sceneTheme = theme;
    const next = SCENE_THEMES[theme];

    (this.scene.background as InstanceType<typeof Color>)?.set(next.paper);
    (this.scene.fog as InstanceType<typeof Fog>)?.color.set(next.paper);
    this.renderer.toneMappingExposure = next.exposure;

    if (this.backWall) {
      (this.backWall.material as InstanceType<typeof MeshStandardMaterial>).color.set(
        next.paper,
      );
    }
    if (this.ground) {
      (this.ground.material as InstanceType<typeof MeshStandardMaterial>).color.set(
        next.ground,
      );
    }
    if (this.hemisphereLight) {
      this.hemisphereLight.color.set(next.hemisphereSky);
      this.hemisphereLight.groundColor.set(next.hemisphereGround);
      this.hemisphereLight.intensity = next.hemisphereIntensity;
    }
    if (this.keyLight) {
      this.keyLight.color.set(next.keyColor);
      this.keyLight.intensity = next.keyIntensity;
    }
    if (this.rimLight) {
      this.rimLight.color.set(next.rimColor);
      this.rimLight.intensity = next.rimIntensity;
    }
    if (this.bounceLight) {
      this.bounceLight.color.set(next.bounceColor);
      this.bounceLight.intensity = next.bounceIntensity;
    }
  }

  private createBooks() {
    const gap = 0.045;
    const weekGap = 0.85;
    this.weekBuckets = buildWeekBuckets(
      this.booksData.map((book) => book.date),
      {
        rowPitch: shelfRowPitch,
        baseShelfY: shelfTop,
        labelBuilder: (_monday, weekIndex) =>
          weekIndex === 0
            ? "Recently added"
            : weekIndex === 1
              ? "Earlier additions"
              : weekIndex === 2
                ? "Earlier still"
                : "The archive",
      },
    );

    let cursor = 0;
    const weekWidths: number[] = [];

    this.weekBuckets.forEach((bucket, weekIndex) => {
      if (weekIndex > 0) cursor += weekGap;
      const weekStartX = cursor;

      bucket.bookIndices.forEach((bookIndex, orderInWeek) => {
        if (orderInWeek > 0) cursor += gap;
        const book = this.booksData[bookIndex]!;
        cursor += book.thickness * 0.5;
        const runtime = this.createBook(
          book,
          bookIndex,
          cursor,
          weekIndex,
          bucket.shelfY,
        );
        this.runtimeBooks[bookIndex] = runtime;
        this.shelfGroup.add(runtime.slot);
        if (book.coverImage) {
          void this.loadCustomCover(runtime, book.coverImage);
        }
        cursor += book.thickness * 0.5;
      });

      weekWidths.push(Math.max(cursor - weekStartX, 1.2));
    });

    this.weekBuckets.forEach((bucket, weekIndex) => {
      const shelfWidth = (weekWidths[weekIndex] ?? 1.2) + 1.6;
      const firstBookIndex = bucket.bookIndices[0];
      const lastBookIndex = bucket.bookIndices[bucket.bookIndices.length - 1];
      const startX = this.runtimeBooks[firstBookIndex!]?.x ?? 0;
      const endX = this.runtimeBooks[lastBookIndex!]?.x ?? startX;
      const midX = (startX + endX) * 0.5;

      const shelfGeometry = new RoundedBoxGeometry(
        shelfWidth,
        0.2,
        1.68,
        4,
        0.04,
      );
      const shelfMaterial = new MeshStandardMaterial({
        color: shelfColor,
        roughness: 0.62,
        metalness: 0.03,
      });
      const shelf = new Mesh(shelfGeometry, shelfMaterial);
      shelf.position.set(midX, bucket.shelfY - 0.14, 0);
      shelf.castShadow = true;
      shelf.receiveShadow = true;
      this.shelfFurniture.add(shelf);

      const shelfEdge = new Mesh(
        new RoundedBoxGeometry(shelfWidth, 0.1, 0.14, 3, 0.022),
        new MeshPhysicalMaterial({
          color: "#4b3429",
          roughness: 0.46,
          clearcoat: 0.14,
          clearcoatRoughness: 0.5,
        }),
      );
      shelfEdge.position.set(midX, bucket.shelfY - 0.08, 0.82);
      shelfEdge.castShadow = true;
      this.shelfFurniture.add(shelfEdge);

      // Week label on the front edge of the shelf board.
      const label = this.createWeekShelfLabel(bucket.label, shelfWidth);
      label.position.set(midX, bucket.shelfY - 0.02, 0.9);
      this.shelfFurniture.add(label);
    });

    this.runtimeBooks = this.booksData.map((_, index) => {
      const runtime = this.runtimeBooks[index];
      if (!runtime) {
        throw new Error(`Missing shelf book at index ${index}`);
      }
      return runtime;
    });

    this.motionLayout = createMotionLayout(
      this.runtimeBooks.map((book) => ({
        width: book.width,
        thickness: book.data.thickness,
      })),
    );

    const presented = this.presentedIndex ?? this.activeIndex;
    this.runtimeBooks.forEach((book, index) => {
      this.commitBookPose(
        book,
        index === presented
          ? presentedBookPose(this.motionLayout)
          : shelvedBookPose(this.motionLayout),
        false,
      );
    });

    this.fitSceneToWeekStack();
  }

  /** Keep ground/wall/shadows clear of every week row — no false floor cut-off. */
  private fitSceneToWeekStack() {
    const weekCount = Math.max(1, this.weekBuckets.length);
    const lowestShelfY =
      this.weekBuckets[weekCount - 1]?.shelfY ?? shelfTop;
    const highestBookTop =
      shelfTop +
      Math.max(...this.runtimeBooks.map((book) => book.data.height), 1.8);

    if (this.ground) {
      // Sit comfortably below the lowest shelf lip + book bottoms.
      this.ground.position.y = lowestShelfY - 1.35;
    }
    if (this.backWall) {
      const span = highestBookTop - (lowestShelfY - 2);
      this.backWall.geometry.dispose();
      this.backWall.geometry = new PlaneGeometry(48, Math.max(24, span + 6));
      this.backWall.position.y = (highestBookTop + (lowestShelfY - 2)) * 0.5;
    }
    if (this.keyLight) {
      const cam = this.keyLight.shadow.camera;
      cam.top = highestBookTop + 2;
      cam.bottom = lowestShelfY - 3;
      cam.far = 50;
      cam.updateProjectionMatrix();
      this.keyLight.position.set(-4.2, highestBookTop + 4, 5.5);
    }
  }

  private createWeekShelfLabel(label: string, shelfWidth: number) {
    const canvas = document.createElement("canvas");
    const height = 64;
    const width = Math.max(256, Math.round(shelfWidth * 180));
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (ctx) {
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "rgba(245, 240, 230, 0.92)";
      ctx.font = `600 28px ${'system-ui, -apple-system, "SF Pro Text", sans-serif'}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, width / 2, height / 2);
    }
    const texture = toTexture(canvas, this.renderer, 4);
    const planeW = Math.min(shelfWidth * 0.55, 1.8);
    const planeH = 0.11;
    const mesh = new Mesh(
      new PlaneGeometry(planeW, planeH),
      new MeshBasicMaterial({
        map: texture,
        transparent: true,
        depthWrite: false,
      }),
    );
    // Tilt slightly so it reads on the shelf lip.
    mesh.rotation.x = -0.18;
    return mesh;
  }

  private createBook(
    book: ShelfBriefBook,
    index: number,
    x: number,
    weekIndex: number,
    shelfY: number,
  ): RuntimeBook {
    // Width comes from the book itself so real cover images keep their aspect.
    const width = book.coverPlaneWidth;
    const depth = book.thickness;
    const slot = new Group();
    slot.position.set(x, shelfY + book.height * 0.5, 0.04);

    const content = new Group();
    slot.add(content);
    const pose = shelvedBookPose(this.motionLayout);
    content.position.set(pose.x, 0, pose.z);
    content.rotation.y = pose.yaw;
    content.scale.setScalar(pose.scale);

    const inspectionIdle = new Group();
    content.add(inspectionIdle);

    const physical = new Group();
    inspectionIdle.add(physical);

    const boardMaterial = new MeshPhysicalMaterial({
      color: book.cover,
      roughness: 0.78,
      metalness: 0,
      sheen: 0.28,
      sheenColor: new Color(book.ink),
      sheenRoughness: 0.82,
      clearcoat: 0.04,
      clearcoatRoughness: 0.7,
    });
    const paperMaterial = new MeshStandardMaterial({
      color: pageColor,
      roughness: 0.88,
      metalness: 0,
    });

    const pageBlock = new Mesh(
      new RoundedBoxGeometry(
        width - 0.075,
        book.height - 0.105,
        Math.max(0.08, depth - 0.052),
        3,
        0.018,
      ),
      paperMaterial,
    );
    pageBlock.castShadow = true;
    pageBlock.receiveShadow = true;
    physical.add(pageBlock);

    const boardGeometry = new RoundedBoxGeometry(
      width,
      book.height,
      0.034,
      4,
      0.025,
    );
    const backBoard = new Mesh(boardGeometry, boardMaterial);
    backBoard.position.z = -depth * 0.5;
    backBoard.castShadow = true;
    backBoard.receiveShadow = true;
    physical.add(backBoard);

    const spineBoard = new Mesh(
      new RoundedBoxGeometry(0.055, book.height - 0.01, depth + 0.012, 3, 0.018),
      boardMaterial,
    );
    spineBoard.position.x = -width * 0.5 + 0.022;
    spineBoard.castShadow = true;
    physical.add(spineBoard);

    const headbandMaterial = new MeshPhysicalMaterial({
      color: book.accent,
      roughness: 0.62,
      metalness: 0.2,
    });
    const headbandGeometry = new CylinderGeometry(0.017, 0.017, width - 0.1, 10);
    headbandGeometry.rotateZ(Math.PI / 2);
    const headbandTop = new Mesh(headbandGeometry, headbandMaterial);
    headbandTop.position.set(0, book.height * 0.5 - 0.045, 0);
    physical.add(headbandTop);
    const headbandBottom = headbandTop.clone();
    headbandBottom.position.y = -book.height * 0.5 + 0.045;
    physical.add(headbandBottom);

    const frontTexture = toTexture(createPlaceholderFront(book), this.renderer);
    const spineTexture = toTexture(createPlaceholderSpine(book), this.renderer, 4);
    // Back stays a cheap solid until the full cover pass.
    const backCanvas = document.createElement("canvas");
    backCanvas.width = 64;
    backCanvas.height = 96;
    const backCtx = backCanvas.getContext("2d");
    if (backCtx) {
      backCtx.fillStyle = book.cover;
      backCtx.fillRect(0, 0, 64, 96);
    }
    const backTexture = toTexture(backCanvas, this.renderer, 2);
    const textures = [frontTexture, spineTexture, backTexture];

    const coverW = width - 0.065;
    const coverH = book.height - 0.065;
    const openPageW = width - 0.08;
    const pageH = book.height - 0.08;
    const pageTint = new Color(book.cover).lerp(new Color("#f5f0e6"), 0.72);
    const pageMaterial = new MeshStandardMaterial({
      color: pageTint,
      roughness: 0.92,
      metalness: 0,
    });

    const openPage = new Mesh(new PlaneGeometry(openPageW, pageH), pageMaterial);
    openPage.position.set(0, 0, depth * 0.5 + 0.018);
    openPage.visible = false;
    physical.add(openPage);

    const pageW = (width - 0.08) * 0.5;
    const leftPage = new Mesh(new PlaneGeometry(pageW, pageH), pageMaterial);
    leftPage.position.set(-pageW * 0.5, 0, depth * 0.5 + 0.018);
    leftPage.visible = false;
    physical.add(leftPage);

    const rightHinge = new Group();
    rightHinge.position.set(0, 0, depth * 0.5 + 0.018);
    physical.add(rightHinge);

    const rightPage = new Mesh(new PlaneGeometry(pageW, pageH), pageMaterial);
    rightPage.position.set(pageW * 0.5, 0, 0);
    rightPage.visible = false;
    rightHinge.add(rightPage);

    const coverHinge = new Group();
    coverHinge.position.set(-width * 0.5 + 0.035, 0, depth * 0.5 + 0.019);
    physical.add(coverHinge);

    const frontSurface = new Mesh(
      new PlaneGeometry(coverW, coverH),
      new MeshPhysicalMaterial({
        map: frontTexture,
        roughness: 0.66,
        metalness: 0.02,
        clearcoat: 0.05,
        clearcoatRoughness: 0.48,
      }),
    );
    frontSurface.position.set(coverW * 0.5 - 0.035, 0, 0);
    coverHinge.add(frontSurface);

    const seed =
      book.id.split("").reduce((acc, char) => acc + char.charCodeAt(0), 0) %
      997;
    const livingMaterial = createLivingMaterial(book.accent, seed / 997);
    const shimmer = new Mesh(
      new PlaneGeometry(coverW * 0.94, coverH * 0.94),
      livingMaterial,
    );
    shimmer.name = "livingCoverShimmer";
    shimmer.position.set(coverW * 0.5 - 0.035, 0, 0.012);
    coverHinge.add(shimmer);

    const backSurface = new Mesh(
      new PlaneGeometry(coverW, coverH),
      new MeshStandardMaterial({
        map: backTexture,
        roughness: 0.72,
      }),
    );
    backSurface.position.z = -depth * 0.5 - 0.019;
    backSurface.rotation.y = Math.PI;
    physical.add(backSurface);

    const spineSurface = new Mesh(
      new PlaneGeometry(depth - 0.02, book.height - 0.04),
      new MeshPhysicalMaterial({
        map: spineTexture,
        roughness: 0.68,
        metalness: 0.015,
      }),
    );
    spineSurface.rotation.y = -Math.PI / 2;
    spineSurface.position.x = -width * 0.5 - 0.019;
    physical.add(spineSurface);

    const pickProxy = new Mesh(
      new BoxGeometry(width, book.height, depth + 0.07),
      new MeshBasicMaterial({
        transparent: true,
        opacity: 0,
        depthWrite: false,
      }),
    );
    pickProxy.userData.bookIndex = index;
    inspectionIdle.add(pickProxy);
    this.pickTargets.push(pickProxy);

    return {
      data: book,
      index,
      slot,
      content,
      inspectionIdle,
      physical,
      frontSurface,
      spineSurface,
      backSurface,
      boardMaterial,
      headbandMaterial,
      coverHinge,
      openPage,
      pageBlock,
      spineBoard,
      backBoard,
      headbandTop,
      headbandBottom,
      rightHinge,
      leftPage,
      rightPage,
      pickProxy,
      livingMaterial,
      x,
      width,
      weekIndex,
      pose,
      hover: 0,
      targetHover: 0,
      idleAmount: 0,
      textures,
    };
  }

  private scheduleCoverUpgrades() {
    if (this.isDisposed) return;
    // Paint the active / presented volumes first so the hero book looks finished ASAP.
    const priority = new Set<number>(
      [this.presentedIndex, this.activeIndex, 0].filter(
        (value): value is number => value !== null && value !== undefined,
      ),
    );
    const rest = this.runtimeBooks
      .map((book) => book.index)
      .filter((index) => !priority.has(index));
    this.coverUpgradeQueue = [...priority, ...rest];
    this.pumpCoverUpgrades();
  }

  private pumpCoverUpgrades = () => {
    if (this.isDisposed) return;
    // A couple per frame keeps the main thread responsive.
    const batch = this.coverUpgradeQueue.splice(0, 2);
    for (const index of batch) {
      const runtime = this.runtimeBooks[index];
      if (runtime) this.replaceBookCovers(runtime, runtime.data);
    }
    if (this.coverUpgradeQueue.length > 0) {
      requestAnimationFrame(this.pumpCoverUpgrades);
    }
  };

  private replaceBookCovers(runtime: RuntimeBook, book: ShelfBriefBook) {
    runtime.data = book;

    // Books with a real cover image keep their loaded texture — only the
    // procedural surfaces (spine / back / boards) are repainted here.
    const usesCustomCover = Boolean(book.coverImage);
    const customTexture = usesCustomCover
      ? runtime.frontSurface.material.map
      : null;

    const frontTexture = usesCustomCover
      ? null
      : toTexture(createFrontCover(book), this.renderer);
    const spineTexture = toTexture(createSpineCover(book), this.renderer, 4);
    const backTexture = toTexture(createBackCover(book), this.renderer);

    if (frontTexture) {
      runtime.frontSurface.material.map = frontTexture;
      runtime.frontSurface.material.needsUpdate = true;
    }
    runtime.spineSurface.material.map = spineTexture;
    runtime.spineSurface.material.needsUpdate = true;
    runtime.backSurface.material.map = backTexture;
    runtime.backSurface.material.needsUpdate = true;

    runtime.boardMaterial.color.set(book.cover);
    runtime.boardMaterial.sheenColor.set(book.ink);
    runtime.headbandMaterial.color.set(book.accent);
    if (runtime.livingMaterial) {
      (runtime.livingMaterial.uniforms.uColor.value as InstanceType<typeof Color>).set(
        book.accent,
      );
    }
    const pageTint = new Color(book.cover).lerp(new Color("#f5f0e6"), 0.72);
    (runtime.openPage.material as InstanceType<typeof MeshStandardMaterial>).color.set(
      pageTint,
    );

    for (const texture of runtime.textures) {
      if (customTexture && texture === customTexture) continue;
      texture.dispose();
    }
    runtime.textures = [
      ...(customTexture ? [customTexture] : []),
      ...(frontTexture ? [frontTexture] : []),
      spineTexture,
      backTexture,
    ];
  }

  updateBooks(books: ShelfBriefBook[]) {
    for (const book of books) {
      const runtime = this.runtimeBooks.find((entry) => entry.data.id === book.id);
      if (!runtime) continue;
      const agentKey =
        book.agents
          ?.map(
            (agent) =>
              `${agent.id}:${agent.portrait ? 1 : 0}:${agent.brandLogo ? 1 : 0}`,
          )
          .join("|") ?? "";
      const prevAgentKey =
        runtime.data.agents
          ?.map(
            (agent) =>
              `${agent.id}:${agent.portrait ? 1 : 0}:${agent.brandLogo ? 1 : 0}`,
          )
          .join("|") ?? "";
      if (
        runtime.data.cover === book.cover &&
        runtime.data.accent === book.accent &&
        runtime.data.ink === book.ink &&
        runtime.data.title === book.title &&
        runtime.data.tagline === book.tagline &&
        runtime.data.motif === book.motif &&
        runtime.data.edition === book.edition &&
        runtime.data.tools?.join() === book.tools?.join() &&
        agentKey === prevAgentKey
      ) {
        continue;
      }
      this.replaceBookCovers(runtime, book);
    }
  }

  private bindEvents() {
    this.canvas.addEventListener("wheel", this.handleWheel, { passive: false });
    this.canvas.addEventListener("pointerdown", this.handlePointerDown);
    this.canvas.addEventListener("pointermove", this.handlePointerMove);
    this.canvas.addEventListener("pointerup", this.handlePointerUp);
    this.canvas.addEventListener("pointercancel", this.handlePointerCancel);
    this.canvas.addEventListener("pointerleave", this.handlePointerLeave);
    this.canvas.addEventListener("keydown", this.handleKeyDown);
    window.addEventListener("keydown", this.handleKeyDown);
    window.addEventListener("blur", this.handleWindowBlur);
  }

  private handleWheel = (event: WheelEvent) => {
    if (this.mode !== "browse" || this.revealPhase !== "idle") return;
    event.preventDefault();
    this.pendingFocusIndex = null;
    const dominant =
      Math.abs(event.deltaX) > Math.abs(event.deltaY)
        ? event.deltaX
        : event.deltaY;
    const impulse = dominant * wheelScrollGain;
    this.targetScrollIndex = clamp(
      this.targetScrollIndex + impulse,
      0,
      this.runtimeBooks.length - 1,
    );
    this.scrollVelocity = clamp(
      this.scrollVelocity + impulse * wheelMomentumGain,
      -4.8,
      4.8,
    );
    this.lastInputTime = performance.now();
  };

  private dragScrollDelta(clientDeltaX: number, timestamp: number) {
    const dragScale = Math.max(72, this.canvas.clientWidth * 0.082);
    const indexDelta = -clientDeltaX / dragScale;
    this.targetScrollIndex = clamp(
      this.targetScrollIndex + indexDelta,
      0,
      this.runtimeBooks.length - 1,
    );

    const elapsed = Math.max((timestamp - this.pointerLastMoveTime) / 1000, 1 / 240);
    const instantVelocity = indexDelta / elapsed;
    this.scrollVelocity = MathUtils.lerp(this.scrollVelocity, instantVelocity, 0.42);
    this.pointerLastMoveTime = timestamp;
    this.lastInputTime = timestamp;
  }

  private applyScrollMomentum(delta: number, timestamp: number) {
    if (this.isDragging() || Math.abs(this.scrollVelocity) < scrollMomentumMin) {
      if (Math.abs(this.scrollVelocity) < scrollMomentumMin) {
        this.scrollVelocity = 0;
      }
      return;
    }

    this.targetScrollIndex = clamp(
      this.targetScrollIndex + this.scrollVelocity * delta,
      0,
      this.runtimeBooks.length - 1,
    );
    this.scrollVelocity *= Math.exp(-scrollMomentumFriction * delta);
    if (Math.abs(this.scrollVelocity) < scrollMomentumMin) {
      this.scrollVelocity = 0;
    }
    this.lastInputTime = timestamp;
  }

  private handlePointerDown = (event: PointerEvent) => {
    if (this.mode !== "browse" || this.revealPhase !== "idle") return;
    this.pointerDown = true;
    this.pointerId = event.pointerId;
    this.pointerStartX = event.clientX;
    this.pointerLastX = event.clientX;
    this.pointerLastMoveTime = performance.now();
    this.pointerTravel = 0;
    this.scrollVelocity = 0;
    this.canvas.setPointerCapture(event.pointerId);
  };

  private handlePointerMove = (event: PointerEvent) => {
    this.updatePointer(event);

    if (this.pointerDown && event.pointerId === this.pointerId) {
      if (this.mode !== "browse") return;
      const delta = event.clientX - this.pointerLastX;
      this.pointerLastX = event.clientX;
      this.pointerTravel += Math.abs(delta);
      // Deadzone: ignore tiny jitter so a click never starts a browse retreat.
      if (this.pointerTravel < 6) return;
      this.pendingFocusIndex = null;
      this.dragScrollDelta(delta, performance.now());
      this.canvas.classList.add("is-dragging");
      return;
    }

    this.updateHover();
  };

  private handlePointerUp = (event: PointerEvent) => {
    if (event.pointerId !== this.pointerId) return;
    const wasClick =
      this.pointerTravel < 7 && Math.abs(event.clientX - this.pointerStartX) < 7;
    this.pointerDown = false;
    this.pointerId = null;
    this.canvas.classList.remove("is-dragging");
    if (this.canvas.hasPointerCapture(event.pointerId)) {
      this.canvas.releasePointerCapture(event.pointerId);
    }
    if (wasClick && this.mode === "browse") {
      this.updatePointer(event);
      const hit = this.raycastBook();
      if (hit !== null) this.focusBook(hit);
    }
  };

  private handlePointerCancel = (event: PointerEvent) => {
    if (event.pointerId !== this.pointerId) return;
    this.pointerDown = false;
    this.pointerId = null;
    this.canvas.classList.remove("is-dragging");
  };

  private handlePointerLeave = () => {
    if (!this.pointerDown) {
      this.runtimeBooks.forEach((book) => {
        book.targetHover = 0;
      });
      this.canvas.style.cursor = "grab";
    }
  };

  private handleWindowBlur = () => {
    this.pointerDown = false;
    this.pointerId = null;
    this.canvas.classList.remove("is-dragging");
  };

  private handleKeyDown = (event: KeyboardEvent) => {
    // Never hijack keys typed into form fields (import dialogs, inputs…).
    const target = event.target as HTMLElement | null;
    if (
      target &&
      (target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable)
    ) {
      return;
    }
    if (event.key === "Escape") {
      this.returnToShelf();
      return;
    }
    if ((event.key === "r" || event.key === "R") && this.mode === "open") {
      this.resetFocusView();
      return;
    }
    if (this.mode !== "browse") return;

    if (event.key === "ArrowRight") {
      event.preventDefault();
      this.browseBy(1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      this.browseBy(-1);
    } else if (event.key === "Home") {
      event.preventDefault();
      this.browseTo(0);
    } else if (event.key === "End") {
      event.preventDefault();
      this.browseTo(this.runtimeBooks.length - 1);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      this.focusBook(this.activeIndex);
    }
  };

  private updatePointer(event: PointerEvent) {
    const rect = this.canvas.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  }

  private raycastBook() {
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hit = this.raycaster.intersectObjects(this.pickTargets, false)[0];
    return typeof hit?.object.userData.bookIndex === "number"
      ? (hit.object.userData.bookIndex as number)
      : null;
  }

  private updateHover() {
    if (this.mode !== "browse") return;
    const hit = this.raycastBook();
    this.runtimeBooks.forEach((book) => {
      book.targetHover = book.index === hit ? 1 : 0;
    });
    this.canvas.style.cursor = hit === null ? "grab" : "pointer";
  }

  private xAtIndex(index: number) {
    const lower = Math.floor(index);
    const upper = Math.min(this.runtimeBooks.length - 1, Math.ceil(index));
    const fraction = index - lower;
    return MathUtils.lerp(
      this.runtimeBooks[lower]?.x ?? 0,
      this.runtimeBooks[upper]?.x ?? 0,
      fraction,
    );
  }

  private yAtIndex(index: number) {
    const lower = Math.floor(index);
    const upper = Math.min(this.runtimeBooks.length - 1, Math.ceil(index));
    const fraction = index - lower;
    const yFor = (book: RuntimeBook | undefined) =>
      book ? book.slot.position.y - book.data.height * 0.5 : shelfTop;
    return MathUtils.lerp(
      yFor(this.runtimeBooks[lower]),
      yFor(this.runtimeBooks[upper]),
      fraction,
    );
  }

  private footprintFor(
    book: RuntimeBook,
    pose: BookPose = book.pose,
  ): BookFootprint {
    return {
      id: book.data.id,
      x: book.x + pose.x,
      z: book.slot.position.z + pose.z,
      yaw: pose.yaw,
      scale: pose.scale,
      width: book.width,
      thickness: book.data.thickness,
    };
  }

  private collisionFor(book: RuntimeBook, pose: BookPose) {
    const proposed = this.footprintFor(book, pose);
    return (
      this.runtimeBooks.find(
        (other) =>
          other !== book &&
          bookFootprintsOverlap(
            proposed,
            this.footprintFor(other),
            this.motionLayout.collisionMargin,
          ),
      ) ?? null
    );
  }

  private commitBookPose(
    book: RuntimeBook,
    pose: BookPose,
    guardCollision = true,
  ) {
    if (guardCollision) {
      const collidedWith = this.collisionFor(book, pose);
      if (collidedWith) return false;
    }

    book.pose = { ...pose };
    book.content.position.x = pose.x;
    book.content.position.z = pose.z;
    book.content.rotation.y = pose.yaw;
    book.content.scale.setScalar(pose.scale);
    return true;
  }

  private isDragging() {
    return this.pointerDown && this.pointerTravel >= 6;
  }

  /** True only when the shelf is actually browsing — not a click press. */
  private isScrolling(timestamp: number) {
    return (
      this.isDragging() ||
      Math.abs(this.scrollVelocity) > scrollMomentumMin ||
      timestamp - this.lastInputTime < scrollSettleMs
    );
  }

  private applyScrollLiftPoses(skipIndex: number | null = null) {
    for (const book of this.runtimeBooks) {
      if (book.index === skipIndex) continue;
      const lift = scrollProximityLift(
        book.index,
        this.scrollIndex,
        scrollLiftRadius,
      );
      const pose =
        lift > 0.015
          ? scrollLiftPose(lift, this.motionLayout)
          : shelvedBookPose(this.motionLayout);
      this.commitBookPose(book, pose, false);
    }
  }

  private applySettledBookPoses() {
    for (const book of this.runtimeBooks) {
      if (
        this.browseMotionPhase !== "idle" &&
        book.index === this.motionBookIndex
      ) {
        continue;
      }

      const isPresented =
        this.browseMotionPhase === "idle" &&
        book.index === this.presentedIndex &&
        this.presentedIndex === this.presentTargetIndex;
      const pose = isPresented
        ? presentedBookPose(this.motionLayout)
        : shelvedBookPose(this.motionLayout);
      this.commitBookPose(book, pose, false);
    }
  }

  private shelveStalePresentedBook() {
    if (
      this.presentedIndex === null ||
      this.presentedIndex === this.presentTargetIndex
    ) {
      return;
    }
    this.commitBookPose(
      this.runtimeBooks[this.presentedIndex],
      shelvedBookPose(this.motionLayout),
      false,
    );
    this.presentedIndex = null;
  }

  private bookNeedsPresent(index: number) {
    const book = this.runtimeBooks[index];
    if (!book) return false;
    const presented = presentedBookPose(this.motionLayout);
    return (
      Math.abs(book.pose.z - presented.z) > 0.035 ||
      Math.abs(book.pose.yaw - presented.yaw) > 0.07
    );
  }

  /** Book is already pulled forward — safe to open without extract/unshelf. */
  private isBookForwardPresented(index: number) {
    const book = this.runtimeBooks[index];
    if (!book) return false;
    const presented = presentedBookPose(this.motionLayout);
    const shelved = shelvedBookPose(this.motionLayout);
    const range = presented.z - shelved.z;
    if (range <= 0.001) return false;
    const forward = (book.pose.z - shelved.z) / range;
    return (
      forward > 0.55 &&
      Math.abs(book.pose.yaw - presented.yaw) < 0.28
    );
  }


  private computeFullscreenFocus(book: RuntimeBook) {
    const isMobile = this.canvas.clientWidth < 760;
    const focusDistance = isMobile ? 4.65 : 4.35;
    const fovRad = (this.camera.fov * Math.PI) / 180;
    const visibleHeight = 2 * Math.tan(fovRad / 2) * focusDistance;
    const presented = presentedBookPose(this.motionLayout);
    const targetScale = (visibleHeight * 0.98) / book.data.height;
    return {
      focusZ: presented.z + (isMobile ? 0.62 : 0.74),
      focusScale: Math.max(targetScale, presented.scale * 1.85),
      focusDistance,
    };
  }

  private isBookFullyPresented(index: number) {
    return !this.bookNeedsPresent(index);
  }

  private isRetreatPhase(phase: BrowseMotionPhase | "idle") {
    return (
      phase === "retreat-current" ||
      phase === "turn-current" ||
      phase === "shelve-current"
    );
  }

  private beginPresentMotion() {
    const index = this.presentTargetIndex;
    if (this.isBookForwardPresented(index)) {
      this.commitBookPose(
        this.runtimeBooks[index],
        presentedBookPose(this.motionLayout),
        false,
      );
      this.presentedIndex = index;
      this.motionBookIndex = null;
      this.browseMotionPhase = "idle";
      if (this.pendingFocusIndex === index) {
        this.beginFocus(index);
      }
      return;
    }

    const book = this.runtimeBooks[index];
    if (!book) return;

    // Continue from a scroll-peek instead of restarting extract from shelved.
    const presented = presentedBookPose(this.motionLayout);
    const shelved = shelvedBookPose(this.motionLayout);
    const range = presented.z - shelved.z;
    const forward = range > 0.001 ? (book.pose.z - shelved.z) / range : 0;
    const facingCamera = Math.abs(book.pose.yaw - presented.yaw) < 0.85;
    if (forward > 0.18 && facingCamera) {
      this.presentFromLift = clamp(forward / 0.48, 0.2, 1);
      this.motionBookIndex = index;
      this.browseMotionPhase = "present-from-peek";
      this.browseMotionProgress = 0;
      return;
    }

    this.motionBookIndex = index;
    this.browseMotionPhase = "extract-next";
    this.browseMotionProgress = 0;
  }

  private beginRetreatPresented() {
    if (this.presentedIndex === null) return;
    this.motionBookIndex = this.presentedIndex;
    this.browseMotionPhase = "retreat-current";
    this.browseMotionProgress = 0;
  }

  private updateBrowseMotion(delta: number) {
    if (this.browseMotionPhase === "idle") {
      if (
        this.pendingFocusIndex !== null &&
        this.isBookForwardPresented(this.pendingFocusIndex)
      ) {
        this.presentedIndex = this.pendingFocusIndex;
        this.presentTargetIndex = this.pendingFocusIndex;
        this.beginFocus(this.pendingFocusIndex);
        return;
      }

      const targetSettled =
        this.presentedIndex === this.presentTargetIndex &&
        !this.bookNeedsPresent(this.presentTargetIndex);
      if (targetSettled) {
        if (this.pendingFocusIndex === this.presentTargetIndex) {
          this.beginFocus(this.presentTargetIndex);
        }
        return;
      }

      if (this.isBookForwardPresented(this.presentTargetIndex)) {
        this.presentedIndex = this.presentTargetIndex;
        if (this.pendingFocusIndex === this.presentTargetIndex) {
          this.beginFocus(this.pendingFocusIndex);
        }
        return;
      }

      if (
        this.presentedIndex !== null &&
        this.presentedIndex !== this.presentTargetIndex &&
        this.isBookFullyPresented(this.presentedIndex)
      ) {
        this.beginRetreatPresented();
      } else {
        if (
          this.presentedIndex !== null &&
          this.presentedIndex !== this.presentTargetIndex
        ) {
          this.shelveStalePresentedBook();
        }
        this.beginPresentMotion();
      }
    }

    const phase = this.browseMotionPhase;
    const motionIndex = this.motionBookIndex;
    if (motionIndex === null || phase === "idle") return;
    const duration = this.reducedMotion
      ? Math.max(0.055, browsePhaseDuration[phase] * 0.45)
      : browsePhaseDuration[phase];
    const nextProgress = clamp(
      this.browseMotionProgress + delta / duration,
      0,
      1,
    );
    const movingBook = this.runtimeBooks[motionIndex];
    const proposedPose =
      phase === "present-from-peek"
        ? peekToPresentedPose(
            nextProgress,
            this.motionLayout,
            this.presentFromLift,
          )
        : browseMotionPose(phase, nextProgress, this.motionLayout);
    if (!this.commitBookPose(movingBook, proposedPose, false)) return;

    this.browseMotionProgress = nextProgress;
    if (nextProgress < 1) return;

    this.browseMotionProgress = 0;
    switch (phase) {
      case "retreat-current":
        this.browseMotionPhase = "turn-current";
        break;
      case "turn-current":
        this.browseMotionPhase = "shelve-current";
        break;
      case "shelve-current":
        this.presentedIndex = null;
        if (this.revealPhase === "shelve") {
          // Ceremony finished shelving — gently re-present as today's spotlight.
          this.revealPhase = "idle";
          this.revealProgress = 0;
          const restored = this.revealBookIndex ?? this.presentTargetIndex;
          this.revealBookIndex = null;
          this.presentTargetIndex = restored;
          this.motionBookIndex = null;
          this.browseMotionPhase = "idle";
          if (this.bookNeedsPresent(restored)) {
            this.beginPresentMotion();
          } else {
            this.presentedIndex = restored;
          }
        } else if (this.isScrolling(performance.now())) {
          this.motionBookIndex = null;
          this.browseMotionPhase = "idle";
        } else if (this.bookNeedsPresent(this.presentTargetIndex)) {
          if (this.isBookForwardPresented(this.presentTargetIndex)) {
            this.presentedIndex = this.presentTargetIndex;
            this.motionBookIndex = null;
            this.browseMotionPhase = "idle";
          } else {
            this.beginPresentMotion();
          }
        } else {
          this.motionBookIndex = null;
          this.browseMotionPhase = "idle";
        }
        break;
      case "extract-next":
        this.browseMotionPhase = "turn-next";
        break;
      case "turn-next":
        this.browseMotionPhase = "settle-next";
        break;
      case "settle-next":
      case "present-from-peek":
        this.presentedIndex = motionIndex;
        this.motionBookIndex = null;
        this.browseMotionPhase = "idle";
        if (this.pendingFocusIndex === this.presentedIndex) {
          this.beginFocus(this.presentedIndex);
        }
        break;
    }
  }

  private beginFocus(index: number) {
    if (this.mode !== "browse") return;
    const book = this.runtimeBooks[index];
    if (!book) return;

    // Mint gate: only open from a settled presented book.
    if (
      this.browseMotionPhase !== "idle" ||
      this.presentedIndex !== index
    ) {
      this.pendingFocusIndex = index;
      return;
    }

    this.pendingFocusIndex = null;
    this.browseMotionPhase = "idle";
    this.motionBookIndex = null;
    this.browseMotionProgress = 0;
    this.presentedIndex = index;
    this.presentTargetIndex = index;
    this.selectedIndex = index;
    // Snap to presented so open never inherits peek/shelved yaw.
    const origin = focusOriginPose(this.motionLayout);
    this.commitBookPose(book, origin, false);
    this.applyBookSpread(book, 0);
    this.focusProgress = 0;
    this.mode = "focusing";
    this.renderer.domElement.style.opacity = "1";
    this.runtimeBooks.forEach((entry) => {
      entry.targetHover = 0;
    });
    this.callbacks.onMode(this.mode, index);
    this.emitTransition(0, book);
  }

  private applyBookSpread(book: RuntimeBook, spread: number) {
    const coverAngle = spreadCoverAngle(spread);
    const isOpen = spread > 0.08;
    book.coverHinge.rotation.y = -coverAngle;
    book.rightHinge.rotation.y = 0;
    const showPage = spread > 0.03;
    book.openPage.visible = showPage;
    book.leftPage.visible = false;
    book.rightPage.visible = false;
    book.pageBlock.visible = !isOpen;
    book.spineBoard.visible = !isOpen;
    book.backBoard.visible = !isOpen;
    book.headbandTop.visible = !isOpen;
    book.headbandBottom.visible = !isOpen;
    book.frontSurface.visible = coverAngle < Math.PI * 0.46;
    book.spineSurface.visible = !isOpen;
    book.backSurface.visible = !isOpen;
    book.physical.rotation.x = (1 - spread) * 0.02;
    book.physical.rotation.y = 0;
    if (spread <= 0.001) {
      book.physical.rotation.x = 0;
      book.coverHinge.rotation.y = 0;
      book.rightHinge.rotation.y = 0;
      book.openPage.visible = false;
      book.pageBlock.visible = true;
      book.spineBoard.visible = true;
      book.backBoard.visible = true;
      book.headbandTop.visible = true;
      book.headbandBottom.visible = true;
      book.spineSurface.visible = true;
      book.backSurface.visible = true;
    }
  }

  private projectObjectRect(object: InstanceType<typeof Mesh> | InstanceType<typeof Group>) {
    const width = Math.max(1, this.canvas.clientWidth);
    const height = Math.max(1, this.canvas.clientHeight);
    const box = new Box3().setFromObject(object);
    if (box.isEmpty()) return null;

    const corners = [
      new Vector3(box.min.x, box.min.y, box.min.z),
      new Vector3(box.max.x, box.min.y, box.min.z),
      new Vector3(box.min.x, box.max.y, box.min.z),
      new Vector3(box.max.x, box.max.y, box.min.z),
      new Vector3(box.min.x, box.min.y, box.max.z),
      new Vector3(box.max.x, box.min.y, box.max.z),
      new Vector3(box.min.x, box.max.y, box.max.z),
      new Vector3(box.max.x, box.max.y, box.max.z),
    ];

    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    for (const corner of corners) {
      const projected = corner.clone().project(this.camera);
      const x = (projected.x * 0.5 + 0.5) * width;
      const y = (-projected.y * 0.5 + 0.5) * height;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }

    if (!Number.isFinite(minX) || maxX - minX < 12 || maxY - minY < 12) {
      return null;
    }

    return {
      x: minX,
      y: minY,
      width: maxX - minX,
      height: maxY - minY,
    } satisfies PageScreenRect;
  }

  private projectReaderRect(book: RuntimeBook, spread: number): PageScreenRect | null {
    if (spread > 0.12) {
      return (
        this.projectObjectRect(book.openPage) ??
        this.projectObjectRect(book.physical)
      );
    }
    return (
      this.projectObjectRect(book.frontSurface) ??
      this.projectObjectRect(book.pickProxy)
    );
  }

  private emitTransition(progress: number, book: RuntimeBook | null) {
    const phases = openTransitionPhases(progress);
    const readerRect = book
      ? this.projectReaderRect(book, phases.spread)
      : null;
    this.callbacks.onTransition?.({
      progress,
      spread: phases.spread,
      expand: phases.expand,
      readerRect,
      pageColor: book?.data.cover ?? PAPER,
      viewport: {
        width: Math.max(1, this.canvas.clientWidth),
        height: Math.max(1, this.canvas.clientHeight),
      },
    });
  }

  private applyFocusViewOffset(_progress: number) {
    this.camera.clearViewOffset();
  }

  private frameFocusedBook(
    worldPosition: InstanceType<typeof Vector3>,
    compositionProgress = 1,
    focusDistance = 4.35,
  ) {
    this.applyFocusViewOffset(compositionProgress);
    this.focusCameraTarget.copy(worldPosition);
    this.focusCameraPosition.set(
      worldPosition.x,
      worldPosition.y + 0.08,
      worldPosition.z + focusDistance,
    );
  }

  private updateFocusCamera(delta: number, focusDistance = 4.35) {
    if (this.selectedIndex === null) return;
    const selected = this.runtimeBooks[this.selectedIndex];
    const worldPosition = new Vector3();
    selected.content.getWorldPosition(worldPosition);
    this.frameFocusedBook(worldPosition, easeOutCubic(this.focusProgress), focusDistance);
    this.camera.position.lerp(
      this.focusCameraPosition,
      1 - Math.exp(-(this.reducedMotion ? 28 : 13) * delta),
    );
    this.camera.lookAt(this.focusCameraTarget);
  }

  private animate = () => {
    if (this.isDisposed) return;
    this.animationFrame = requestAnimationFrame(this.animate);
    const timestamp = performance.now();
    const delta = clamp((timestamp - this.lastTimestamp) / 1000 || 1 / 60, 0, 0.05);
    this.lastTimestamp = timestamp;

    if (
      !this.pointerDown &&
      Math.abs(this.scrollVelocity) < scrollMomentumMin &&
      timestamp - this.lastInputTime > scrollIndexSnapMs &&
      this.mode === "browse"
    ) {
      this.targetScrollIndex = damp(
        this.targetScrollIndex,
        Math.round(this.targetScrollIndex),
        this.reducedMotion ? 22 : 11,
        delta,
      );
    }
    if (this.mode === "browse") {
      this.applyScrollMomentum(delta, timestamp);
    }
    this.scrollIndex = damp(
      this.scrollIndex,
      this.targetScrollIndex,
      this.reducedMotion ? 28 : 18,
      delta,
    );

    if (this.mode === "browse") {
      this.focusProgress = damp(this.focusProgress, 0, 10, delta);
      this.camera.position.lerp(
        this.responsiveBrowseCamera,
        1 - Math.exp(-(this.reducedMotion ? 18 : 7) * delta),
      );
      this.camera.lookAt(browseTarget);
    } else if (this.mode === "focusing") {
      this.focusProgress = clamp(
        this.focusProgress + delta / (this.reducedMotion ? 0.1 : focusInDuration),
        0,
        1,
      );
      const focusPhases = openTransitionPhases(this.focusProgress);
      const selected = this.selectedIndex !== null
        ? this.runtimeBooks[this.selectedIndex]
        : null;
      const focusTargets = selected ? this.computeFullscreenFocus(selected) : null;
      if (focusPhases.expand > 0.02) {
        this.updateFocusCamera(delta, focusTargets?.focusDistance);
      } else {
        this.camera.position.lerp(
          this.responsiveBrowseCamera,
          1 - Math.exp(-(this.reducedMotion ? 18 : 9) * delta),
        );
        this.camera.lookAt(browseTarget);
      }
      if (this.selectedIndex !== null) {
        const selected = this.runtimeBooks[this.selectedIndex];
        const phases = openTransitionPhases(this.focusProgress);
        this.applyBookSpread(selected, phases.spread);
        this.emitTransition(this.focusProgress, selected);
      }
      if (this.focusProgress >= 1) {
        this.mode = "open";
        this.controls.enabled = false;
        this.controls.target.copy(this.focusCameraTarget);
        this.camera.position.copy(this.focusCameraPosition);
        this.controls.update();
        this.canvas.style.cursor = "default";
        if (this.selectedIndex !== null) {
          this.emitTransition(1, this.runtimeBooks[this.selectedIndex] ?? null);
        }
        this.callbacks.onMode(this.mode, this.selectedIndex);
      }
    } else if (this.mode === "open") {
      if (this.selectedIndex !== null) {
        this.emitTransition(1, this.runtimeBooks[this.selectedIndex] ?? null);
      }
    } else if (this.mode === "returning") {
      this.controls.enabled = false;
      this.focusProgress = clamp(
        this.focusProgress - delta / (this.reducedMotion ? 0.08 : focusOutDuration),
        0,
        1,
      );
      this.applyFocusViewOffset(this.focusProgress);
      const selected =
        this.selectedIndex !== null
          ? this.runtimeBooks[this.selectedIndex]
          : null;
      const focusTargets = selected
        ? this.computeFullscreenFocus(selected)
        : null;
      const phases = openTransitionPhases(this.focusProgress);
      if (selected) {
        this.applyBookSpread(selected, phases.spread);
        this.emitTransition(this.focusProgress, selected);
      }
      // Hold the focus camera while the volume is still large; only
      // ease back to browse once the book has mostly closed.
      if (phases.expand > 0.08 && focusTargets) {
        this.updateFocusCamera(delta, focusTargets.focusDistance);
      } else {
        this.camera.position.lerp(
          this.responsiveBrowseCamera,
          1 - Math.exp(-(this.reducedMotion ? 24 : 14) * delta),
        );
        this.camera.lookAt(browseTarget);
      }
      if (this.focusProgress <= 0) {
        if (this.selectedIndex !== null) {
          const closing = this.runtimeBooks[this.selectedIndex];
          this.applyBookSpread(closing, 0);
          closing.physical.rotation.x = 0;
          closing.physical.rotation.y = 0;
          this.commitBookPose(
            closing,
            presentedBookPose(this.motionLayout),
          );
          this.presentedIndex = this.selectedIndex;
          this.presentTargetIndex = this.selectedIndex;
        }
        const ceremonyIndex = this.selectedIndex;
        this.selectedIndex = null;
        this.mode = "browse";
        this.emitTransition(0, null);
        this.renderer.domElement.style.opacity = "1";
        this.callbacks.onMode(this.mode, null);
        this.camera.clearViewOffset();
        if (this.ceremonyOnReturn && ceremonyIndex !== null) {
          this.ceremonyOnReturn = false;
          this.beginCoverReveal(ceremonyIndex);
        }
      }
    }

    const nextActive = clamp(
      Math.round(this.scrollIndex),
      0,
      this.runtimeBooks.length - 1,
    );
    if (nextActive !== this.activeIndex) {
      this.activeIndex = nextActive;
      this.callbacks.onActiveIndex(this.activeIndex);
    }

    this.shelfGroup.position.x = -this.xAtIndex(this.scrollIndex);
    const focusShelfY = this.yAtIndex(this.scrollIndex);
    if (this.mode === "browse") {
      browseTarget.y = focusShelfY + 0.94;
      this.responsiveBrowseCamera.y =
        (this.canvas.clientWidth < 760 ? 1.2 : 1.42) +
        (focusShelfY - shelfTop);
    }
    const scrolling =
      this.mode === "browse" &&
      this.revealPhase === "idle" &&
      this.isScrolling(timestamp);
    if (this.mode === "browse") {
      if (this.revealPhase === "paint") {
        this.updateCoverReveal(delta);
      } else if (this.wasScrolling && !scrolling) {
        this.presentTargetIndex = clamp(
          Math.round(this.targetScrollIndex),
          0,
          this.runtimeBooks.length - 1,
        );
        if (this.presentTargetIndex !== this.activeIndex) {
          this.activeIndex = this.presentTargetIndex;
          this.callbacks.onActiveIndex(this.activeIndex);
        }
      }
      this.wasScrolling = scrolling;

      if (this.revealPhase === "paint") {
        // Hold the presented pose while the cover materializes.
        this.applySettledBookPoses();
      } else if (scrolling) {
        if (
          this.browseMotionPhase === "idle" &&
          this.presentedIndex !== null &&
          this.isBookFullyPresented(this.presentedIndex)
        ) {
          this.beginRetreatPresented();
        } else if (
          this.browseMotionPhase !== "idle" &&
          !this.isRetreatPhase(this.browseMotionPhase) &&
          this.motionBookIndex !== null
        ) {
          this.presentedIndex = this.motionBookIndex;
          this.beginRetreatPresented();
        }

        if (this.browseMotionPhase !== "idle") {
          this.updateBrowseMotion(delta);
          this.applyScrollLiftPoses(this.motionBookIndex);
        } else {
          this.applyScrollLiftPoses();
        }
      } else {
        this.updateBrowseMotion(delta);
        if (this.browseMotionPhase === "idle") {
          this.applySettledBookPoses();
        }
      }
    }

    const motionFocus =
      this.mode === "returning"
        ? this.focusProgress
        : easeOutCubic(this.focusProgress);
    const phases = openTransitionPhases(motionFocus);
    const bookFade = easeOutCubic(phases.expand);
    if (
      this.mode === "focusing" ||
      this.mode === "open" ||
      this.mode === "returning"
    ) {
      this.renderer.domElement.style.opacity = `${Math.max(
        0,
        1 - bookFade * 0.96,
      )}`;
    } else {
      this.renderer.domElement.style.opacity = "1";
    }

    if (this.selectedIndex !== null && this.mode !== "browse") {
      for (const book of this.runtimeBooks) {
        if (book.index === this.selectedIndex) continue;
        this.commitBookPose(book, shelvedBookPose(this.motionLayout), false);
      }
    }
    if (this.selectedIndex !== null) {
      const selected = this.runtimeBooks[this.selectedIndex];
      const focusTargets = this.computeFullscreenFocus(selected);
      const motion = focusedBookOpenPose(
        motionFocus,
        this.motionLayout,
        focusTargets.focusZ,
        focusTargets.focusScale,
      );
      this.commitBookPose(
        selected,
        {
          x: motion.x,
          z: motion.z,
          yaw: motion.yaw,
          scale: motion.scale,
        },
        false,
      );
      selected.physical.rotation.x = motion.tiltX;
      this.applyBookSpread(selected, phases.spread);
    }

    this.runtimeBooks.forEach((book) => {
      book.hover = damp(book.hover, book.targetHover, 12, delta);
      const isSelected = book.index === this.selectedIndex;
      book.content.visible = true;
      if (book.livingMaterial) {
        book.livingMaterial.uniforms.uTime.value = timestamp / 1000;
        const isSpotlight =
          book.index === this.spotlightIndex || !!book.data.spotlight;
        const livingStrength =
          isSelected && this.mode !== "browse"
            ? 0
            : this.revealPhase === "paint" && book.index === this.revealBookIndex
              ? 0.15 + Math.sin(this.revealProgress * Math.PI) * 0.75
              : book.index === this.presentedIndex
                ? (isSpotlight ? 0.62 : 0.22) + book.hover * 0.14
                : isSpotlight
                  ? 0.3 + book.hover * 0.1
                  : book.hover * 0.05;
        book.livingMaterial.uniforms.uStrength.value = damp(
          book.livingMaterial.uniforms.uStrength.value as number,
          this.reducedMotion ? 0 : livingStrength,
          10,
          delta,
        );
      }
      const scrollLift =
        scrolling && !isSelected
          ? scrollProximityLift(book.index, this.scrollIndex, scrollLiftRadius)
          : 0;
      const isSpotlight =
        book.index === this.spotlightIndex || !!book.data.spotlight;
      const lift =
        !scrolling && book.index === this.presentedIndex
          ? (isSpotlight ? 0.055 : 0.02) + book.hover * 0.014
          : book.hover * 0.008;
      book.content.position.y = isSelected
        ? motionFocus * 0.04
        : scrollLift * 0.016 + lift;

      const idleTarget =
        isSelected && this.mode === "open" && !this.reducedMotion ? 0 : 0;
      book.idleAmount = damp(book.idleAmount, idleTarget, 5, delta);
      const idleStrength = isSelected ? book.idleAmount : 0;
      const idlePhase = timestamp / 1000 * 0.78 + book.index * 0.37;
      book.inspectionIdle.position.y =
        Math.sin(idlePhase) * inspectionIdleLift * idleStrength;
      book.inspectionIdle.rotation.set(
        Math.sin(idlePhase * 0.73 + 0.8) * inspectionIdlePitch * idleStrength,
        Math.sin(idlePhase * 0.61) * inspectionIdleYaw * idleStrength,
        Math.sin(idlePhase * 0.89 + 1.7) * inspectionIdleRoll * idleStrength,
      );
    });

    this.updateSpotlightLight(delta);
    this.renderer.render(this.scene, this.camera);
  };

  private handleResize = () => {
    const width = Math.max(1, this.canvas.clientWidth);
    const height = Math.max(1, this.canvas.clientHeight);
    const dprCap = width < 760 ? 1.5 : 1.75;
    const focusShelfY = this.yAtIndex(this.scrollIndex);
    this.responsiveBrowseCamera.set(
      0,
      (width < 760 ? 1.2 : 1.42) + (focusShelfY - shelfTop),
      width < 760 ? 8.3 : browseCamera.z,
    );
    browseTarget.y = focusShelfY + 0.94;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, dprCap));
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.fov = width < 600 ? 33 : width < 920 ? 30 : 27;
    this.camera.updateProjectionMatrix();
    if (this.mode === "browse" && this.focusProgress < 0.01) {
      this.camera.clearViewOffset();
      this.camera.position.copy(this.responsiveBrowseCamera);
      this.camera.lookAt(browseTarget);
    } else if (this.mode === "open" && this.selectedIndex !== null) {
      const worldPosition = new Vector3();
      this.runtimeBooks[this.selectedIndex].content.getWorldPosition(worldPosition);
      this.frameFocusedBook(worldPosition);
      this.controls.target.copy(this.focusCameraTarget);
      this.camera.position.copy(this.focusCameraPosition);
      this.controls.update();
    }
  };

  resetFocusView() {
    if (this.mode !== "open" || this.selectedIndex === null) return;
    const selected = this.runtimeBooks[this.selectedIndex];
    const worldPosition = new Vector3();
    selected.content.getWorldPosition(worldPosition);
    this.frameFocusedBook(worldPosition);
    this.controls.target.copy(this.focusCameraTarget);
    this.camera.position.copy(this.focusCameraPosition);
    this.controls.update();
  }

  private async loadCustomCover(runtime: RuntimeBook, coverImage: string) {
    try {
      const texture = await new TextureLoader().loadAsync(coverImage);
      if (this.isDisposed) {
        texture.dispose();
        return;
      }

      texture.colorSpace = SRGBColorSpace;
      texture.anisotropy = Math.min(
        8,
        this.renderer.capabilities.getMaxAnisotropy(),
      );

      const material = runtime.frontSurface.material;
      const proceduralTexture = material.map;
      material.map = texture;
      material.needsUpdate = true;
      runtime.textures.push(texture);

      if (proceduralTexture) {
        const index = runtime.textures.indexOf(proceduralTexture);
        if (index >= 0) runtime.textures.splice(index, 1);
        proceduralTexture.dispose();
      }
    } catch {
      // Keep procedural cover when image fails to load.
    }
  }

  browseBy(direction: number) {
    if (this.mode !== "browse" || this.revealPhase !== "idle") return;
    this.browseTo(Math.round(this.targetScrollIndex) + direction);
  }

  browseTo(index: number) {
    if (this.mode !== "browse" || this.revealPhase !== "idle") return;
    const next = clamp(Math.round(index), 0, this.runtimeBooks.length - 1);
    this.pendingFocusIndex = null;
    this.targetScrollIndex = next;
    this.presentTargetIndex = next;
    this.scrollVelocity = 0;
    this.lastInputTime = performance.now() - scrollSettleMs - 1;
  }

  /** Land straight in the reader — used for the day's first unopened brief. */
  snapOpenImmediate(index = this.activeIndex) {
    const next = clamp(Math.round(index), 0, this.runtimeBooks.length - 1);
    const book = this.runtimeBooks[next];
    if (!book) return;

    this.browseMotionPhase = "idle";
    this.motionBookIndex = null;
    this.browseMotionProgress = 0;
    this.pendingFocusIndex = null;
    this.scrollIndex = next;
    this.targetScrollIndex = next;
    this.activeIndex = next;
    this.presentTargetIndex = next;
    this.presentedIndex = next;
    this.selectedIndex = next;
    this.scrollVelocity = 0;
    this.focusProgress = 1;
    this.mode = "open";
    this.controls.enabled = false;

    const focusTargets = this.computeFullscreenFocus(book);
    const motion = focusedBookOpenPose(
      1,
      this.motionLayout,
      focusTargets.focusZ,
      focusTargets.focusScale,
    );
    this.commitBookPose(
      book,
      {
        x: motion.x,
        z: motion.z,
        yaw: motion.yaw,
        scale: motion.scale,
      },
      false,
    );
    book.physical.rotation.x = motion.tiltX;
    this.applyBookSpread(book, 1);

    const worldPosition = new Vector3();
    book.content.getWorldPosition(worldPosition);
    this.frameFocusedBook(worldPosition, 1, focusTargets.focusDistance);
    this.camera.position.copy(this.focusCameraPosition);
    this.camera.lookAt(this.focusCameraTarget);
    this.controls.target.copy(this.focusCameraTarget);
    this.controls.update();
    this.renderer.domElement.style.opacity = "0.04";
    this.canvas.style.cursor = "default";
    this.callbacks.onActiveIndex(next);
    this.emitTransition(1, book);
    this.callbacks.onMode(this.mode, next);
  }

  setSpotlightIndex(index: number | null) {
    this.spotlightIndex = index;
  }

  private beginCoverReveal(index: number) {
    const book = this.runtimeBooks[index];
    if (!book) return;
    this.revealPhase = "paint";
    this.revealProgress = 0;
    this.revealBookIndex = index;
    this.presentedIndex = index;
    this.presentTargetIndex = index;
    this.commitBookPose(book, presentedBookPose(this.motionLayout), false);
    book.frontSurface.material.color.set("#d8cfc0");
    book.spineSurface.material.color.set("#d8cfc0");
    book.backSurface.material.color.set("#d8cfc0");
    book.physical.scale.setScalar(0.94);
    if (book.livingMaterial) {
      book.livingMaterial.uniforms.uStrength.value = 0.05;
    }
  }

  private updateCoverReveal(delta: number) {
    if (this.revealPhase !== "paint" || this.revealBookIndex === null) return;
    const book = this.runtimeBooks[this.revealBookIndex];
    if (!book) {
      this.revealPhase = "idle";
      return;
    }

    const duration = this.reducedMotion ? 0.08 : 1.05;
    this.revealProgress = clamp(this.revealProgress + delta / duration, 0, 1);
    const t = easeOutCubic(this.revealProgress);
    const pulse = Math.sin(this.revealProgress * Math.PI);

    book.frontSurface.material.color.setRGB(
      0.847 + (1 - 0.847) * t,
      0.812 + (1 - 0.812) * t,
      0.753 + (1 - 0.753) * t,
    );
    book.spineSurface.material.color.copy(book.frontSurface.material.color);
    book.backSurface.material.color.copy(book.frontSurface.material.color);
    book.physical.scale.setScalar(0.94 + t * 0.06 + pulse * 0.03);

    if (this.revealProgress >= 1) {
      book.frontSurface.material.color.set("#ffffff");
      book.spineSurface.material.color.set("#ffffff");
      book.backSurface.material.color.set("#ffffff");
      book.physical.scale.setScalar(1);
      this.revealPhase = "shelve";
      this.beginRetreatPresented();
    }
  }

  private updateSpotlightLight(delta: number) {
    if (!this.spotlightLight) return;
    const index =
      this.spotlightIndex ??
      this.runtimeBooks.findIndex((book) => book.data.spotlight);
    const book = index >= 0 ? this.runtimeBooks[index] : null;
    const browsing =
      this.mode === "browse" && this.revealPhase !== "paint";
    const targetIntensity =
      book && browsing && !this.reducedMotion
        ? book.index === this.presentedIndex
          ? 4.6
          : 2.2
        : this.revealPhase === "paint" && book
          ? 5.0
          : 0;
    this.spotlightLight.intensity = damp(
      this.spotlightLight.intensity,
      targetIntensity,
      6,
      delta,
    );
    if (!book) return;
    const world = new Vector3();
    book.content.getWorldPosition(world);
    this.spotlightLight.position.lerp(
      new Vector3(world.x, world.y + 0.7, world.z + 1.35),
      1 - Math.exp(-8 * delta),
    );
    this.spotlightLight.color.set(book.data.accent || "#ffe6bc");
  }

  focusBook(index = this.activeIndex) {
    if (this.mode !== "browse" || this.revealPhase !== "idle") return;
    const next = clamp(Math.round(index), 0, this.runtimeBooks.length - 1);
    this.targetScrollIndex = next;
    this.scrollIndex = next;
    this.activeIndex = next;
    this.presentTargetIndex = next;
    this.scrollVelocity = 0;
    this.pendingFocusIndex = next;
    this.callbacks.onActiveIndex(next);

    // If this volume is already the presented one (or mid-present on it),
    // open from here — never retreat/re-extract first.
    const alreadyPresented =
      this.presentedIndex === next || this.isBookForwardPresented(next);
    if (alreadyPresented) {
      // Cancel any retreat/handoff that a click press may have started.
      if (
        this.motionBookIndex === next ||
        this.isRetreatPhase(this.browseMotionPhase) ||
        this.browseMotionPhase === "present-from-peek" ||
        this.browseMotionPhase === "settle-next" ||
        this.browseMotionPhase === "turn-next" ||
        this.browseMotionPhase === "extract-next"
      ) {
        this.browseMotionPhase = "idle";
        this.motionBookIndex = null;
        this.browseMotionProgress = 0;
      }
      this.presentedIndex = next;
      this.commitBookPose(
        this.runtimeBooks[next],
        presentedBookPose(this.motionLayout),
        false,
      );
      this.beginFocus(next);
      return;
    }

    // Match mint: open immediately only when already presented + idle.
    if (
      this.browseMotionPhase === "idle" &&
      this.presentedIndex === next
    ) {
      this.beginFocus(next);
    }
  }

  returnToShelf() {
    if (this.mode === "browse" && this.pendingFocusIndex !== null) {
      this.pendingFocusIndex = null;
      return;
    }
    if (this.mode === "browse" || this.mode === "returning") return;
    this.controls.enabled = false;
    this.mode = "returning";
    this.callbacks.onMode(this.mode, this.selectedIndex);
  }

  getWeekBuckets() {
    return this.weekBuckets;
  }

  getMode() {
    return this.mode;
  }

  dispose() {
    this.isDisposed = true;
    this.coverUpgradeQueue = [];
    cancelAnimationFrame(this.animationFrame);
    this.resizeObserver.disconnect();
    this.controls.dispose();
    this.canvas.removeEventListener("wheel", this.handleWheel);
    this.canvas.removeEventListener("pointerdown", this.handlePointerDown);
    this.canvas.removeEventListener("pointermove", this.handlePointerMove);
    this.canvas.removeEventListener("pointerup", this.handlePointerUp);
    this.canvas.removeEventListener("pointercancel", this.handlePointerCancel);
    this.canvas.removeEventListener("pointerleave", this.handlePointerLeave);
    this.canvas.removeEventListener("keydown", this.handleKeyDown);
    window.removeEventListener("keydown", this.handleKeyDown);
    window.removeEventListener("blur", this.handleWindowBlur);

    for (const book of this.runtimeBooks) {
      book.textures.forEach((texture) => texture.dispose());
      book.livingMaterial?.dispose();
    }
    this.renderer.dispose();
  }
}
