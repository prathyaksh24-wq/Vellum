/* Screen 2 — Setup mode
   ◆ Setup mode  /  cyan title, gray desc, yellow question
   Three radio options. Default: Quick. ENTER advances. */

const { useState: useMode_useState, useEffect: useMode_useEffect } = React;

const MODE_OPTIONS = [
  { id: "quick",   label: "Quick setup",          sub: "— 4 screens, sensible defaults  (recommended)" },
  { id: "full",    label: "Full setup",           sub: "— 12 screens, every choice" },
  { id: "restore", label: "Restore from backup",  sub: "— ~/.vellum.tar.gz or a path" },
];

function ModeScreen({ s, set, onAdvance }) {
  const initial = MODE_OPTIONS.findIndex(o => o.id === (s.flow || "quick"));
  const [idx, setIdx] = useMode_useState(initial < 0 ? 0 : initial);

  useMode_useEffect(() => {
    const h = (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); setIdx(i => (i + 1) % MODE_OPTIONS.length); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setIdx(i => (i - 1 + MODE_OPTIONS.length) % MODE_OPTIONS.length); }
      else if (/^[1-9]$/.test(e.key)) {
        const n = parseInt(e.key, 10) - 1;
        if (n < MODE_OPTIONS.length) setIdx(n);
      }
      else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        set("flow", MODE_OPTIONS[idx].id);
        // mode shapes the rest of the wizard, but Pass 2 only routes the next 2 screens
        onAdvance();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [idx, set, onAdvance]);

  return (
    <div className="oc-section">
      <div className="oc-line">
        <span className="oc-marker">◆</span>
        <span className="oc-title">Setup mode</span>
      </div>
      <div className="oc-desc">
        Let's configure your Vellum installation. Press <code style={{color:"var(--text)"}}>Ctrl+C</code> at any time to exit.
      </div>

      <div className="oc-question">How would you like to set up Vellum?</div>
      <div className="oc-hint">
        <span className="seg"><kbd>↑↓</kbd> navigate</span>
        <span className="seg"><kbd>1–3</kbd> jump</span>
        <span className="seg"><kbd>ENTER</kbd> select</span>
        <span className="seg"><kbd>ESC</kbd> cancel</span>
      </div>

      <div className="oc-list">
        {MODE_OPTIONS.map((o, i) => (
          <div
            key={o.id}
            className={"oc-row " + (i === idx ? "sel" : "")}
            onMouseEnter={() => setIdx(i)}
            onClick={() => { set("flow", o.id); onAdvance(); }}
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

window.ModeScreen = ModeScreen;
