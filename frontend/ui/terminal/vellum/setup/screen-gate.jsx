/* ScreenGate — OC "already configured" preface
   ──────────────────────────────────────────────
   Wraps every screen. On first-run, it's transparent — children render
   as normal. On re-run, when state.existing[screenKey] === true, the
   gate intercepts the first render and shows a 3-radio preface:

     (•) Keep current
     (o) Reconfigure
     (o) Skip

   Selection triggers one of the formal reducer actions:
     • Keep current  → KEEP_CURRENT (advances cursor)
     • Reconfigure   → RECONFIGURE  (clears existing flag, gate dissolves,
                                     children render normally)
     • Skip          → SKIP         (advances cursor, marks as skipped)

   The sovereignty screen (06) opts out of gating — it's an
   acknowledgment, not a configuration. */

const {
  useState: useSG_useState,
  useEffect: useSG_useEffect,
} = React;

// label + description per screen (matches the OC pattern preface)
const GATE_COPY = {
  cloud:        { title: "Cloud augmentation",  hint: (s) => s.cloud.provider !== "none" ? `${s.cloud.provider} key set` : "skipped" },
  localModel:   { title: "Local model",         hint: (s) => s.localModel?.id ? `${s.localModel.id} · ${s.localModel.sizeGB || "?"} GB` : "—" },
  learning:     { title: "Learning sources",    hint: (s) => `${Object.values(s.learning).filter(Boolean).length} of 3 sources on` },
  skills:       { title: "Skills",              hint: (s) => `${(s.skills || []).filter(sk => sk.enabled).length} enabled` },
  mcp:          { title: "MCP servers",         hint: (s) => `${(s.mcp || []).filter(m => m.enabled).length} enabled` },
  personalize:  { title: "Personalization",     hint: (s) => s.personalize.name ? `I know you as "${s.personalize.name}"` : "no name captured" },
};

function ScreenGate({ screenKey, s, keepCurrent, reconfigure, skip, children }) {
  const hasExisting = !!(s.existing && s.existing[screenKey]);
  const [revealed, setRevealed] = useSG_useState(false);
  const [idx, setIdx] = useSG_useState(0);  // 0=Keep, 1=Reconfigure, 2=Skip

  // Hooks must run unconditionally. Keyboard listener is no-op when
  // preface isn't shown.
  useSG_useEffect(() => {
    if (!hasExisting || revealed) return;
    const h = (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); setIdx(i => Math.min(2, i + 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setIdx(i => Math.max(0, i - 1)); }
      else if (/^[1-3]$/.test(e.key)) { setIdx(parseInt(e.key, 10) - 1); }
      else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (idx === 0) keepCurrent();
        else if (idx === 1) { reconfigure(screenKey); setRevealed(true); }
        else skip(screenKey);
      }
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [hasExisting, revealed, idx, keepCurrent, reconfigure, skip, screenKey]);

  if (!hasExisting || revealed) return children;

  const copy = GATE_COPY[screenKey] || { title: screenKey, hint: () => "" };
  const hint = copy.hint(s);

  const options = [
    { label: "Keep current", sub: hint ? `— ${hint}` : "" },
    { label: "Reconfigure",  sub: "— show me the screen, let me change it" },
    { label: "Skip",         sub: "— leave it as-is for now, mark as pending" },
  ];

  return (
    <div className="oc-section">
      <div className="oc-line">
        <span className="oc-marker">◆</span>
        <span className="oc-title">{copy.title}</span>
      </div>

      <div className="oc-question">
        {copy.title} is already configured — what would you like to do?
      </div>
      <div className="oc-hint">
        <span className="seg"><kbd>↑↓</kbd> navigate</span>
        <span className="seg"><kbd>1–3</kbd> jump</span>
        <span className="seg"><kbd>ENTER</kbd> select</span>
        <span className="seg"><kbd>ESC</kbd> cancel</span>
      </div>

      <div className="oc-list">
        {options.map((o, i) => (
          <div
            key={o.label}
            className={"oc-row " + (i === idx ? "sel" : "")}
            onMouseEnter={() => setIdx(i)}
            onClick={() => {
              setIdx(i);
              if (i === 0) keepCurrent();
              else if (i === 1) { reconfigure(screenKey); setRevealed(true); }
              else skip(screenKey);
            }}
          >
            <span className="arr">→</span>
            <span className="glyph">{i === idx ? "(•)" : "(o)"}</span>
            <span className="label">{o.label}</span>
            <span className="sub">{o.sub}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

window.ScreenGate = ScreenGate;
window.GATE_COPY = GATE_COPY;
