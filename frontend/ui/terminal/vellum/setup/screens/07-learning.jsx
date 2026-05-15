/* Screen 7 — Learning sources
   Three checkboxes. Default: first two on, third off (terminal
   activity is the most invasive). ↑↓ navigate, SPACE toggle,
   ENTER continue. Footnote about changing later. */

const { useState: useLearn_useState, useEffect: useLearn_useEffect } = React;

const LEARN_OPTIONS = [
  { id: "conversations", label: "Our conversations",            sub: "— everything we say to each other" },
  { id: "files",         label: "Files I point you at",          sub: "— files you explicitly share or open with me" },
  { id: "terminal",      label: "Terminal activity in LightTerm", sub: "— commands you run, output you see. (most invasive — default off)" },
];

function LearningScreen({ s, set, onAdvance }) {
  const [idx, setIdx] = useLearn_useState(0);

  useLearn_useEffect(() => {
    const h = (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); setIdx(i => Math.min(LEARN_OPTIONS.length - 1, i + 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setIdx(i => Math.max(0, i - 1)); }
      else if (/^[1-9]$/.test(e.key)) {
        const n = parseInt(e.key, 10) - 1;
        if (n < LEARN_OPTIONS.length) setIdx(n);
      }
      else if (e.key === " ") {
        e.preventDefault();
        const key = LEARN_OPTIONS[idx].id;
        set("learning", { [key]: !s.learning[key] });
      }
      else if (e.key === "Enter") {
        e.preventDefault();
        onAdvance();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [idx, s.learning, set, onAdvance]);

  return (
    <div className="oc-section">
      <div className="oc-line">
        <span className="oc-marker">◆</span>
        <span className="oc-title">Learning sources</span>
      </div>
      <div className="oc-desc">
        What I'm allowed to learn from. Everything I notice goes into <span style={{color:"var(--text)"}}>~/.vellum/journal.md</span> — readable, deletable, yours.
      </div>

      <div className="oc-question">Toggle what I can learn from:</div>
      <div className="oc-hint">
        <span className="seg"><kbd>↑↓</kbd> navigate</span>
        <span className="seg"><kbd>SPACE</kbd> toggle</span>
        <span className="seg"><kbd>ENTER</kbd> continue</span>
        <span className="seg"><kbd>ESC</kbd> back</span>
      </div>

      <div className="oc-list">
        {LEARN_OPTIONS.map((o, i) => {
          const on = !!s.learning[o.id];
          return (
            <div
              key={o.id}
              className={"oc-row check " + (i === idx ? "sel" : "")}
              onMouseEnter={() => setIdx(i)}
              onClick={() => { setIdx(i); set("learning", { [o.id]: !on }); }}
            >
              <span className="arr">→</span>
              <span className="glyph">[{on ? "x" : " "}]</span>
              <span className="label">{o.label}</span>
              <span className="sub">{o.sub}</span>
            </div>
          );
        })}
      </div>

      <div style={{marginTop: 22, fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--text-faint)", letterSpacing: 0.02}}>
        change anytime in <code style={{color:"var(--text-dim)"}}>vellum config learn</code>
      </div>
    </div>
  );
}

window.LearningScreen = LearningScreen;
