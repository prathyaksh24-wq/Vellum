/* Screen 6 — Data sovereignty (trust anchor)
   No choice. Acknowledgment only. The screen is the message —
   no boxes, no animation beyond the standard fade-in.
   ENTER continues. ESC is the only back. */

const { useEffect: useSov_useEffect } = React;

function SovereigntyScreen({ set, onAdvance }) {
  useSov_useEffect(() => {
    const h = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        set("sovereignty", { acknowledgedAt: new Date().toISOString() });
        onAdvance();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [set, onAdvance]);

  return (
    <div className="oc-section">
      <div className="oc-line">
        <span className="oc-marker">◆</span>
        <span className="oc-title">Data sovereignty</span>
      </div>

      <div className="sovereignty">
        <div className="anchor">Your data lives at <b style={{color: "var(--text)"}}>~/.vellum/</b>.</div>

        <div className="files">
          <b>memory.sqlite</b>    <span className="com">— what I remember</span><br />
          <b>journal.md</b>       <span className="com">— what I've noticed</span><br />
          <b>skills/</b>          <span className="com">— what you've taught me</span>
        </div>

        <p>Plain files. Export, inspect, delete anytime.</p>

        <p className="promise">
          I don't phone home. Nothing leaves this machine unless you've enabled a cloud model and asked me to use it.
        </p>
      </div>

      <div className="oc-question" style={{marginTop: 36}}>Acknowledge and continue.</div>
      <div className="oc-hint">
        <span className="seg"><kbd>ENTER</kbd> continue</span>
        <span className="seg"><kbd>ESC</kbd> back</span>
      </div>
    </div>
  );
}

window.SovereigntyScreen = SovereigntyScreen;
