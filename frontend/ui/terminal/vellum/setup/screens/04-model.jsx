/* Screen 4 — Local model selection
   Row list with per-row fit badge (from screen 3 detection).
   Default: gemma-3:12b — matches backend FAST_MODEL. ENTER begins
   download in the sidebar and advances. Models flagged as "bad"
   are read-only.

   Catalog mirrors backend/agent/config.py defaults:
     primary  = google/gemma-4-31b-it
     fallback = qwen/qwen3.5-35b-a3b
     fast     = google/gemma-3-12b-it
*/

const { useState: useModel_useState, useEffect: useModel_useEffect, useMemo: useModel_useMemo } = React;

const MODELS = [
  { id: "gemma-3:12b",    family: "Gemma 3",       params: "12B", sizeGB: 7.4,  contextK: 8,   tps: 48, quality: 74, quant: "Q4_K_M", desc: "Fast default — matches backend FAST_MODEL." },
  { id: "gemma-4:4b",     family: "Gemma 4",       params: "4B",  sizeGB: 2.7,  contextK: 8,   tps: 78, quality: 62, quant: "Q4_K_M", desc: "Tiniest — chat & lightweight reasoning." },
  { id: "gemma-4:12b",    family: "Gemma 4",       params: "12B", sizeGB: 7.4,  contextK: 8,   tps: 42, quality: 78, quant: "Q4_K_M", desc: "Mid-range. Stronger reasoning, still snappy." },
  { id: "gemma-4:31b",    family: "Gemma 4",       params: "31B", sizeGB: 18.0, contextK: 128, tps: 22, quality: 88, quant: "Q4_K_M", desc: "Primary — backend PRIMARY_MODEL for deep synthesis." },
  { id: "qwen-3.5:35b",   family: "Qwen 3.5",      params: "35B", sizeGB: 20.5, contextK: 128, tps: 18, quality: 86, quant: "Q4_K_M", desc: "Fallback — backend FALLBACK_MODEL, broad coverage." },
  { id: "llama-3.3:70b",  family: "Llama 3.3",     params: "70B", sizeGB: 41.0, contextK: 128, tps: 7,  quality: 91, quant: "Q4_K_M", desc: "Top-tier open-weights — needs serious VRAM." },
  { id: "deepseek-r1:32b",family: "DeepSeek R1",   params: "32B", sizeGB: 19.0, contextK: 128, tps: 20, quality: 87, quant: "Q4_K_M", desc: "Reasoning model — strong for code & math." },
  { id: "phi-3:3.8b",     family: "Phi 3",         params: "3.8B",sizeGB: 2.2,  contextK: 4,   tps: 92, quality: 58, quant: "Q4_K_M", desc: "Fastest on the list — tight loops." },
];

// fit grading uses hw from screen 3
function gradeFit(m, hw) {
  if (!hw) return "good";
  if (m.sizeGB > hw.vramGB + 4) return "bad";
  if (m.sizeGB > hw.vramGB)     return "swap";
  return "good";
}

function ModelScreen({ s, set, onAdvance }) {
  const fit = useModel_useMemo(() => MODELS.map(m => ({ ...m, fit: gradeFit(m, s.hw) })), [s.hw]);
  const defaultIdx = fit.findIndex(m => m.id === (s.localModel.id || "gemma-3:12b"));
  const [idx, setIdx] = useModel_useState(defaultIdx < 0 ? 0 : defaultIdx);

  useModel_useEffect(() => {
    const h = (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); setIdx(i => Math.min(fit.length - 1, i + 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setIdx(i => Math.max(0, i - 1)); }
      else if (/^[1-9]$/.test(e.key)) {
        const n = parseInt(e.key, 10) - 1;
        if (n < fit.length) setIdx(n);
      }
      else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        const m = fit[idx];
        if (m.fit === "bad") return;
        beginDownload(m, set);
        // Brief delay so the user sees the download begin in sidebar before we move on
        setTimeout(onAdvance, 650);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [idx, fit, set, onAdvance]);

  const cur = fit[idx];

  return (
    <div className="oc-section">
      <div className="oc-line">
        <span className="oc-marker">◆</span>
        <span className="oc-title">Local model</span>
      </div>
      <div className="oc-desc">
        Which model runs locally, by default. You can change this anytime with <code style={{color:"var(--text)"}}>vellum model</code>.
        {s.hw && <> Fit is graded against the <b style={{color:"var(--text)"}}>{s.hw.vramGB} GB</b> of VRAM detected.</>}
      </div>

      <div className="oc-question">Select default local model:</div>
      <div className="oc-hint">
        <span className="seg"><kbd>↑↓</kbd> navigate</span>
        <span className="seg"><kbd>1–{fit.length}</kbd> jump</span>
        <span className="seg"><kbd>ENTER</kbd> begin download</span>
        <span className="seg"><kbd>ESC</kbd> back</span>
      </div>

      <div className="model-grid">
        <div className="col-head"></div>
        <div className="col-head"></div>
        <div className="col-head">Model</div>
        <div className="col-head r">Size</div>
        <div className="col-head r">Quality &amp; fit</div>

        {fit.map((m, i) => (
          <div
            key={m.id}
            className={"row " + (i === idx ? "sel" : "") + (m.fit === "bad" ? " bad" : "")}
            onMouseEnter={() => setIdx(i)}
            onClick={() => {
              if (m.fit === "bad") return;
              beginDownload(m, set);
              setTimeout(onAdvance, 650);
            }}
            style={m.fit === "bad" ? { opacity: 0.5, cursor: "not-allowed" } : {}}
          >
            <div className="arr">→</div>
            <div className="glyph">{i === idx ? "(•)" : "(o)"}</div>
            <div className="name">
              <b>{m.id}</b>
              <div className="meta">
                {m.params} · {m.contextK}K ctx · ~{m.tps} t/s · {m.desc}
              </div>
            </div>
            <div className="size">{m.sizeGB} GB</div>
            <div className="qfit">
              <span className="qbar"><i style={{width: m.quality + "%"}} /></span>
              <span className={"fit " + m.fit}>
                {m.fit === "good" ? "✓ fits" : m.fit === "swap" ? "⚠ will swap" : "✗ won't fit"}
              </span>
            </div>
          </div>
        ))}
      </div>

      {cur && cur.fit === "swap" && (
        <div style={{marginTop: 18, padding: "10px 14px", borderLeft: "2px solid var(--amber)", background: "color-mix(in oklab, var(--amber) 8%, var(--bg-elev))", color: "var(--text-dim)", fontSize: 12.5}}>
          <span style={{color: "var(--amber)"}}>⚠</span>&nbsp; {cur.id} is larger than your {s.hw?.vramGB || "—"} GB VRAM. It will run, but the OS will swap layers — expect ~½ throughput.
        </div>
      )}
    </div>
  );
}

function beginDownload(m, set) {
  set("localModel", {
    id: m.id,
    sizeGB: m.sizeGB,
    contextK: m.contextK,
    quant: m.quant,
    tps: m.tps,
    fit: m.fit,
    status: "downloading",
    pct: 0.5,
    speed: 95,
    eta: "—",
  });
}

window.ModelScreen = ModelScreen;
