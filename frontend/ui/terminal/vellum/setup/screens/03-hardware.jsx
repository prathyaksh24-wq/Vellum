/* Screen 3 — Hardware check
   No input. Acknowledgment only. Scan lines appear sequentially,
   sidebar metric cards fill in lockstep. ENTER to continue. */

const { useState: useHW_useState, useEffect: useHW_useEffect } = React;

const HW_TRUTH = {
  ramGB: 32,    ramMeta: "DDR5-5600 · 4 slots",
  vramGB: 12,   gpuName: "NVIDIA RTX 4070",
  freeDiskGB: 184, diskMeta: "1 TB NVMe · 81% free",
  cpuCores: 16, cpuName: "Ryzen 7 7700X · 5.4 GHz",
};

const SCAN_STEPS = [
  { key: "ram",  line: "Inspecting memory…",       resolve: { ramGB: HW_TRUTH.ramGB, ramMeta: HW_TRUTH.ramMeta } },
  { key: "gpu",  line: "Probing GPU…",             resolve: { vramGB: HW_TRUTH.vramGB, gpuName: HW_TRUTH.gpuName } },
  { key: "disk", line: "Checking ~/.vellum/ path…", resolve: { freeDiskGB: HW_TRUTH.freeDiskGB, diskMeta: HW_TRUTH.diskMeta } },
  { key: "cpu",  line: "Counting cores…",          resolve: { cpuCores: HW_TRUTH.cpuCores, cpuName: HW_TRUTH.cpuName } },
];

function HardwareScreen({ s, setRoot, onAdvance }) {
  const [step, setStep] = useHW_useState(0);
  const done = step >= SCAN_STEPS.length;

  // Progressive scan — each step resolves a slice of s.hw
  useHW_useEffect(() => {
    if (done) return;
    const t = setTimeout(() => {
      setRoot("hw", { ...(s.hw || {}), ...SCAN_STEPS[step].resolve });
      setStep(i => i + 1);
    }, step === 0 ? 280 : 420);
    return () => clearTimeout(t);
  }, [step, done, setRoot, s.hw]);

  // ENTER continues — only once scan completes
  useHW_useEffect(() => {
    const h = (e) => {
      if (!done) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onAdvance(); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [done, onAdvance]);

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
        {SCAN_STEPS.slice(0, step).map((st, i) => (
          <div key={st.key} className="scan">
            <span className="ok">✓</span> <span>{st.line}</span> &nbsp;
            <span className="v">{describeResolve(st.resolve)}</span>
          </div>
        ))}
        {!done && (
          <div className="scan" style={{color: "var(--text-faint)"}}>
            <span style={{color: "var(--amber)"}}>·</span> {SCAN_STEPS[step].line}<Cursor />
          </div>
        )}

        {done && (
          <>
            <div className="summary">
              Detected:&nbsp;
              <b>{HW_TRUTH.ramGB} GB RAM</b> ·&nbsp;
              <b>{HW_TRUTH.vramGB} GB VRAM</b> <span style={{color:"var(--text-faint)"}}>({HW_TRUTH.gpuName})</span> ·&nbsp;
              <b>{HW_TRUTH.freeDiskGB} GB free</b>.
              <br />
              You can run models up to <em>~27B comfortably</em>. I'll keep that in mind on the next screen.
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
