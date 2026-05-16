/* Screen 11 — Summary
   Status group header (Configured · Pending · Skipped) followed
   by the OC-style file-path block and `vellum …` commands.
   ENTER advances to the handoff. */

const { useEffect: useSum_useEffect, useMemo: useSum_useMemo } = React;

function SummaryScreen({ s, onAdvance }) {
  // ── derive status per section
  const sections = useSum_useMemo(() => {
    const local = !!(s.localModel && s.localModel.id);
    const cloud = s.cloud && s.cloud.provider && s.cloud.provider !== "none";
    const cloudReady = cloud && !!s.cloud.keyRef;
    const sov = !!s.sovereignty.acknowledgedAt;
    const learnOn = Object.values(s.learning).filter(Boolean).length;
    const skillsOn = (s.skills || []).filter(sk => sk.enabled).length;
    const mcpOn = (s.mcp || []).filter(m => m.enabled).length;
    const name = !!s.personalize.name;
    const work = !!s.personalize.workingOn;

    return [
      { id: "model",    label: "Local model",      v: s.localModel?.id || "—", status: local ? "ok" : "pend" },
      { id: "cloud",    label: "Cloud augmentation", v: cloud ? (cloudReady ? capitalize(s.cloud.provider) : "key needed") : "skipped",
        status: cloud ? (cloudReady ? "ok" : "pend") : "skip" },
      { id: "sov",      label: "Data sovereignty", v: sov ? "acknowledged" : "—", status: sov ? "ok" : "pend" },
      { id: "learn",    label: "Learning sources", v: learnOn + " of 3 on", status: learnOn > 0 ? "ok" : "skip" },
      { id: "skills",   label: "Skills",           v: skillsOn + " enabled", status: skillsOn > 0 ? "ok" : "skip" },
      { id: "mcp",      label: "MCP servers",      v: mcpOn + " enabled",    status: mcpOn > 0 ? "ok" : "skip" },
      { id: "name",     label: "Name",             v: s.personalize.name || "—", status: name ? "ok" : "skip" },
      { id: "work",     label: "Working on",       v: s.personalize.workingOn || "—", status: work ? "ok" : "skip" },
    ];
  }, [s]);

  const tally = useSum_useMemo(() => {
    const ok = sections.filter(x => x.status === "ok").length;
    const pend = sections.filter(x => x.status === "pend").length;
    const skip = sections.filter(x => x.status === "skip").length;
    return { ok, pend, skip };
  }, [sections]);

  useSum_useEffect(() => {
    const h = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onAdvance();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onAdvance]);

  return (
    <div className="oc-section">
      <div className="oc-line">
        <span className="oc-marker">◆</span>
        <span className="oc-title">Configuration summary</span>
      </div>

      <div className="summary-groups">
        <div className="grp ok"><b>{tally.ok}</b><span>configured</span></div>
        <div className="grp pending"><b>{tally.pend}</b><span>pending</span></div>
        <div className="grp skipped"><b>{tally.skip}</b><span>skipped</span></div>
      </div>

      <div className="sum-list">
        {sections.map(x => (
          <div key={x.id} className={"item " + x.status}>
            <span className="g">{x.status === "ok" ? "✓" : x.status === "pend" ? "⚠" : "·"}</span>
            <span>{x.label}</span>
            <span className="v">{x.v}</span>
          </div>
        ))}
      </div>

      {tally.pend > 0 && (
        <div style={{marginTop: 22, padding: "10px 14px", borderLeft: "2px solid var(--amber)", background: "color-mix(in oklab, var(--amber) 8%, var(--bg-elev))", color: "var(--text-dim)", fontSize: 12.5, maxWidth: 620}}>
          <span style={{color: "var(--amber)"}}>⚠</span>&nbsp; {tally.pend} {tally.pend === 1 ? "thing is" : "things are"} pending — Vellum will start without them. Run <code style={{color:"var(--text)"}}>vellum setup</code> to fill them in later.
        </div>
      )}

      <div className="summary-block">
        <h4><span className="ico">📁</span>Your files are at <span style={{color:"var(--text)"}}>~/.vellum/</span></h4>
        <div className="path-line"><span className="k">config:</span><span className="v">~/.vellum/config.yaml</span></div>
        <div className="path-line"><span className="k">data:</span><span className="v">~/.vellum/</span></div>
        <div className="path-line"><span className="k">logs:</span><span className="v">~/.vellum/logs/</span></div>
        <div className="path-line"><span className="k">env:</span><span className="v">~/.vellum/.env <span style={{color:"var(--text-faint)"}}>(mode 0600)</span></span></div>

        <h4><span className="ico">📝</span>To change later</h4>
        <div className="cmd-line"><span className="cmd">vellum config</span><span className="desc">view current</span></div>
        <div className="cmd-line"><span className="cmd">vellum config edit</span><span className="desc">open in editor</span></div>
        <div className="cmd-line"><span className="cmd">vellum model</span><span className="desc">change model</span></div>
        <div className="cmd-line"><span className="cmd">vellum skills</span><span className="desc">add or remove skills</span></div>
        <div className="cmd-line"><span className="cmd">vellum setup</span><span className="desc">re-run this wizard</span></div>
      </div>

      <div className="oc-question" style={{marginTop: 32}}>Ready to meet Vellum?</div>
      <div className="oc-hint">
        <span className="seg"><kbd>ENTER</kbd> meet vellum</span>
        <span className="seg"><kbd>ESC</kbd> go back &amp; adjust</span>
      </div>
    </div>
  );
}

function capitalize(x) { return x ? (x[0].toUpperCase() + x.slice(1)) : x; }

window.SummaryScreen = SummaryScreen;
