/* Vellum setup state — formal reducer with action types
   ────────────────────────────────────────────────────────
   Actions:
     NEXT          advance one screen, push current onto history
     BACK          pop history; cursor returns to previous screen
     GOTO          jump to a specific cursor (used by tests / dev)
     SKIP          advance + mark this screen as skipped in summary
     RECONFIGURE   user chose to redo this section — clears existing flag
     KEEP_CURRENT  same as NEXT — keeps existing config untouched
     SET           merge into a slice
     SET_ROOT      replace a root key
     SET_EXISTING  preload existing[] (used on rerun mode)
     RESTORE       wholesale state restore (used on mount from disk)

   Persistence: every state change writes to localStorage debounced
   250ms. Real LightTerm hooks this to ~/.vellum/setup-state.json
   via a shell adapter. Writes happen on:
     • screen advance (NEXT/BACK/SKIP/RECONFIGURE/KEEP_CURRENT)
     • SET / SET_ROOT — keystrokes coalesce inside the 250ms window
     • on input blur — screens call persistNow() to flush early */

const {
  useReducer: useSS_useReducer,
  useEffect:  useSS_useEffect,
  useRef:     useSS_useRef,
  useCallback: useSS_useCallback,
} = React;

const SETUP_INITIAL = {
  mode: "first-run",        // "first-run" | "rerun"
  flow: null,               // "quick" | "full" | "restore"
  cursor: 1,
  history: [],

  hw: null,
  localModel: { id: null, status: "none", pct: 0, speed: 0, eta: "—" },
  cloud: { provider: "none" },
  sovereignty: { acknowledgedAt: null },
  learning: { conversations: true, files: true, terminal: false },
  skills: [],
  mcp: [],
  personalize: { name: null, workingOn: null, capturedAt: null },

  ui: { avatar: "breathing" },
  existing: {},             // { model: true, cloud: true, ... } on rerun
  skipped:  {},             // { skills: true, ... } populated by SKIP
};

function setupReducer(s, a) {
  switch (a.type) {
    case "NEXT":
      return { ...s, cursor: Math.min(12, s.cursor + 1), history: [...s.history, s.cursor] };
    case "BACK":
      if (s.history.length === 0) return s;
      return { ...s, cursor: s.history[s.history.length - 1], history: s.history.slice(0, -1) };
    case "GOTO":
      return { ...s, cursor: a.n, history: [...s.history, s.cursor] };
    case "SKIP":
      return {
        ...s,
        cursor: Math.min(12, s.cursor + 1),
        history: [...s.history, s.cursor],
        skipped: { ...(s.skipped || {}), [a.screen]: true },
      };
    case "RECONFIGURE":
      // Clears existing flag for this screen so the screen renders fresh.
      return { ...s, existing: { ...(s.existing || {}), [a.screen]: false } };
    case "KEEP_CURRENT":
      // Identical to NEXT but documents intent for telemetry/logging.
      return { ...s, cursor: Math.min(12, s.cursor + 1), history: [...s.history, s.cursor] };
    case "SET": {
      const cur = s[a.slice];
      const isObj = cur !== null && typeof cur === "object" && !Array.isArray(cur);
      return { ...s, [a.slice]: isObj ? { ...cur, ...a.value } : a.value };
    }
    case "SET_ROOT":
      return { ...s, [a.key]: a.value };
    case "SET_EXISTING":
      return { ...s, mode: "rerun", existing: { ...(s.existing || {}), ...a.value } };
    case "RESTORE":
      return { ...a.snapshot };
    default:
      return s;
  }
}

/* ─────────────────────────────────────────────────────────────
 * Persistence — debounced 250ms write. localStorage is the offline
 * fallback; when the backend API is reachable, the same payload
 * is mirrored to POST /api/setup/state so the wizard survives
 * across machines and `vellum setup` restarts on the server.
 * ─────────────────────────────────────────────────────────── */
const PERSIST_KEY = "vellum.setupState";
const PERSIST_DEBOUNCE_MS = 250;
const API_BASE = (typeof window !== "undefined" && window.__VELLUM_API_BASE) || "http://localhost:8000";

function readSnapshot() {
  try {
    const raw = localStorage.getItem(PERSIST_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    if (!obj || typeof obj !== "object") return null;
    return obj;
  } catch (e) { return null; }
}

async function fetchBackendState() {
  try {
    const res = await fetch(API_BASE + "/api/setup/state", { method: "GET" });
    if (!res.ok) return null;
    const body = await res.json();
    if (body && typeof body === "object") {
      window.__vellumSetupCatalog = body.catalog || null;
      return body.state && Object.keys(body.state).length ? body.state : null;
    }
    return null;
  } catch (e) { return null; }
}

function postBackendState(snapshot, { complete = false } = {}) {
  const url = API_BASE + (complete ? "/api/setup/complete" : "/api/setup/state");
  try {
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: snapshot }),
      keepalive: true,
    }).catch(() => {});
  } catch (e) { /* offline — localStorage already captured it */ }
}

function useSetupState(overrides = {}) {
  // Restore from disk (localStorage) if present, then apply overrides.
  // Overrides are how previews jump-start the wizard for review.
  const initial = (() => {
    const stored = readSnapshot();
    return { ...SETUP_INITIAL, ...(stored || {}), ...overrides };
  })();

  const [s, dispatch] = useSS_useReducer(setupReducer, initial);

  // ── debounced persistence (localStorage + backend mirror)
  const timer = useSS_useRef(null);
  const persist = useSS_useCallback((snapshot) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      try { localStorage.setItem(PERSIST_KEY, JSON.stringify(snapshot)); } catch (e) {}
      postBackendState(snapshot, { complete: snapshot.cursor === 12 });
    }, PERSIST_DEBOUNCE_MS);
  }, []);

  // Any state change triggers a debounced write. Rapid SET dispatches
  // (typing) coalesce into one disk write 250ms after the last keystroke.
  useSS_useEffect(() => {
    persist(s);
  }, [s, persist]);

  // Flush pending write immediately — call from input onBlur.
  const persistNow = useSS_useCallback(() => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    try { localStorage.setItem(PERSIST_KEY, JSON.stringify(s)); } catch (e) {}
    postBackendState(s, { complete: s.cursor === 12 });
  }, [s]);

  // On mount, ask the backend if it already has a setup state. If so,
  // hydrate the reducer (RESTORE) so a returning user picks up where
  // they left off — this also seeds existing[] flags so ScreenGate can
  // present "Keep / Reconfigure / Skip" on rerun.
  useSS_useEffect(() => {
    let cancelled = false;
    fetchBackendState().then((snap) => {
      if (cancelled || !snap) return;
      // Don't clobber an in-progress local session: only hydrate if the
      // backend snapshot looks completed or strictly newer.
      const localCursor = (s && s.cursor) || 1;
      const backendCursor = snap.cursor || 1;
      if (snap.completed_at || backendCursor >= localCursor) {
        dispatch({ type: "RESTORE", snapshot: { ...SETUP_INITIAL, ...snap } });
      }
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── action helpers (thin wrappers around dispatch — screens use these)
  const next         = useSS_useCallback(() => dispatch({ type: "NEXT" }), []);
  const back         = useSS_useCallback(() => dispatch({ type: "BACK" }), []);
  const goto         = useSS_useCallback((n) => dispatch({ type: "GOTO", n }), []);
  const skip         = useSS_useCallback((screen) => dispatch({ type: "SKIP", screen }), []);
  const reconfigure  = useSS_useCallback((screen) => dispatch({ type: "RECONFIGURE", screen }), []);
  const keepCurrent  = useSS_useCallback(() => dispatch({ type: "KEEP_CURRENT" }), []);
  const set          = useSS_useCallback((slice, value) => dispatch({ type: "SET", slice, value }), []);
  const setRoot      = useSS_useCallback((key, value) => dispatch({ type: "SET_ROOT", key, value }), []);
  const setExisting  = useSS_useCallback((value) => dispatch({ type: "SET_EXISTING", value }), []);

  return {
    s, dispatch,
    next, back, goto, skip, reconfigure, keepCurrent,
    set, setRoot, setExisting,
    persistNow,
  };
}

window.useSetupState = useSetupState;
window.SETUP_INITIAL = SETUP_INITIAL;
window.setupReducer  = setupReducer;
