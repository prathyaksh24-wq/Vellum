/* Screen 3 — Hardware check
   No input. Acknowledgment only. Scan lines appear sequentially,
   sidebar metric cards fill in lockstep. ENTER to continue. */

const { useState: useHW_useState, useEffect: useHW_useEffect } = React;

// Real scan from the backend (GET /api/setup/hardware): memory, disk, GPU,
// CPU and whether Ollama is installed, plus a local-vs-cloud recommendation.
const HW_API_BASE = (typeof window !== "undefined" && window.__VELLUM_API_BASE) || "http://localhost:8000";

function scanSteps(hw) {
  return [
    { key: "ram",  line: "Inspecting memory…", resolve: { ramGB: hw.ram_gb, ramMeta: "installed" } },
    { key: "gpu",  line: "Probing GPU…",       resolve: { vramGB: hw.vram_gb, gpuName: hw.gpu_name || "no dedicated GPU" } },
    { key: "disk", line: "Checking free space…", resolve: { freeDiskGB: hw.free_disk_gb, diskMeta: "on Vellum's drive" } },
    { key: "cpu",  line: "Counting cores…",    resolve: { cpuCores: hw.cpu_cores, cpuName: hw.cpu_name || "processor" } },
  ];
}

function HardwareScreen({ s, setRoot, onAdvance }) {
  const [step, setStep] = useHW_useState(0);
  const [scan, setScan] = useHW_useState(null);   // { hardware, recommendation }
  const [failed, setFailed] = useHW_useState(false);
  const steps = scan ? scanSteps(scan.hardware) : [];
  const done = !!scan && step >= steps.length;

  useHW_useEffect(() => {
    let live = true;
    fetch(HW_API_BASE + "/api/setup/hardware")
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(body => { if (live) setScan(body); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, []);

  // Progressive reveal of the real results; the last step stores the recommendation too.
  useHW_useEffect(() => {
    if (!scan || done) return;
    const t = setTimeout(() => {
      const next = { ...(s.hw || {}), ...steps[step].resolve };
      if (step === steps.length - 1) {
        next.recommendation = scan.recommendation;
        next.ollamaInstalled = scan.hardware.ollama_installed;
      }
      setRoot("hw", next);
      setStep(i => i + 1);
    }, step === 0 ? 280 : 420);
    return () => clearTimeout(t);
  }, [scan, step, done, setRoot, s.hw]);

  // ENTER continues — only once scan completes
  useHW_useEffect(() => {
    const h = (e) => {
      if (!done && !failed) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onAdvance(); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [done, failed, onAdvance]);

  return (
    <div className="oc-section">
      <div className="oc-line">
        <span className="oc-marker">◆</span>
        <span className="oc-title">Hardware check</span>
      </div>
      <div className="oc-desc">
        A quick look at what this machine can run. Nothing leaves disk.
      </div>

      <div className="hw-body">
        {failed && (
          <div className="scan" style={{color: "var(--text-faint)"}}>
            Couldn't read this computer's hardware. You can still pick a model on the next screen.
          </div>
        )}
        {steps.slice(0, step).map((st, i) => (
          <div key={st.key} className="scan">
            <span className="ok">✓</span> <span>{st.line}</span> &nbsp;
            <span className="v">{describeResolve(st.resolve)}</span>
          </div>
        ))}
        {!done && !failed && (
          <div className="scan" style={{color: "var(--text-faint)"}}>
            <span style={{color: "var(--amber)"}}>·</span> {steps[step] ? steps[step].line : "Scanning this computer…"}<Cursor />
          </div>
        )}

        {done && (
          <>
            <div className="summary">
              Detected:&nbsp;
              <b>{scan.hardware.ram_gb} GB RAM</b> ·&nbsp;
              <b>{scan.hardware.vram_gb} GB VRAM</b> <span style={{color:"var(--text-faint)"}}>({scan.hardware.gpu_name || "no dedicated GPU"})</span> ·&nbsp;
              <b>{scan.hardware.free_disk_gb} GB free</b>.
              <br />
              {scan.recommendation.mode === "local"
                ? <>Recommended: run <em>{scan.recommendation.label}</em> on this computer ({scan.recommendation.size_gb} GB). {scan.recommendation.reasons.join(". ")}.</>
                : <>Recommended: use a <em>cloud model</em>. {scan.recommendation.reasons.join(" ")}</>}
            </div>

            <div className="oc-question" style={{marginTop: 22}}>Ready to choose a model?</div>
            <div className="oc-hint">
              <span className="seg"><kbd>ENTER</kbd> continue</span>
              <span className="seg"><kbd>ESC</kbd> back</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function describeResolve(r) {
  if ("ramGB" in r) return `${r.ramGB} GB · ${r.ramMeta}`;
  if ("vramGB" in r) return `${r.vramGB} GB · ${r.gpuName}`;
  if ("freeDiskGB" in r) return `${r.freeDiskGB} GB free · ${r.diskMeta}`;
  if ("cpuCores" in r) return `${r.cpuCores} cores · ${r.cpuName}`;
  return "";
}

function Cursor() {
  return <span style={{
    display: "inline-block",
    width: 7, height: 12,
    background: "var(--accent)",
    marginLeft: 6,
    verticalAlign: -1,
    animation: "blink 1.05s steps(2) infinite",
  }} />;
}

window.HardwareScreen = HardwareScreen;
