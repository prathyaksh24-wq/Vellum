/* Vellum setup — pane shell + screen router
   ──────────────────────────────────────────
   Owns:
   - avatar (top-left, persistent)
   - identity + crumb line
   - global ESC → back
   - download tick loop (runs while s.localModel.status === "downloading")
   - the screen-stage transition (oc-section fadeIn)
   - the data-handoff flag (drives chrome dissolve via setup.css)
   - the setupActive signal (drives the LightTerm tab-strip transition;
     correction 1 — one motion, not a remount cascade) */

const { useEffect: useSP_useEffect } = React;

// Screens that can be re-run with an "already configured" preface.
// Map cursor index → state key the ScreenGate consults.
const GATEABLE = {
  4:  "localModel",
  5:  "cloud",
  7:  "learning",
  8:  "skills",
  9:  "mcp",
  10: "personalize",
};

function SetupPane({ initialFlow }) {
  const {
    s, next, back, set, setRoot,
    keepCurrent, reconfigure, skip,
    persistNow,
  } = window.useSetupState(initialFlow ? { flow: initialFlow } : {});

  // Global ESC = back. Screens that own their ESC handler call
  // e.stopPropagation() to keep this from firing.
  useSP_useEffect(() => {
    const h = (e) => {
      if (e.key === "Escape" && s.cursor > 1 && s.cursor < 12) back();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [s.cursor, back]);

  // Download tick loop (sidebar reads s.localModel.pct)
  useSP_useEffect(() => {
    if (s.localModel.status !== "downloading") return;
    const id = setInterval(() => {
      set("localModel", (() => {
        const m = s.localModel;
        if (m.pct >= 100) return { ...m, status: "ready", pct: 100, eta: "done" };
        const inc = Math.random() * 1.6 + 0.4;
        const pct = Math.min(100, +(m.pct + inc).toFixed(1));
        const speed = Math.max(40, Math.round(m.speed + (Math.random() - 0.5) * 22));
        const remaining = 100 - pct;
        const eta = pct >= 100 ? "done" : `${Math.floor(remaining / 8)}:${String(Math.floor(Math.random() * 60)).padStart(2, "0")}`;
        return { ...m, pct, speed, eta };
      })());
    }, 380);
    return () => clearInterval(id);
  }, [s.localModel.status, s.localModel.pct, set, s.localModel]);

  // ── setupActive signal: documentElement[data-setup-active] is the
  //    single boolean LightTerm's chrome reads. Goes "true" while
  //    cursor < 12, "false" the instant cursor === 12. The CSS in
  //    setup.css transitions the tab strip via 400ms when this flips.
  useSP_useEffect(() => {
    const active = s.cursor < 12;
    document.documentElement.dataset.setupActive = active ? "true" : "false";
    window.dispatchEvent(new CustomEvent("vellum-setup-active", { detail: { active } }));
  }, [s.cursor]);

  const crumbLabel = (() => {
    if (!s.flow) return "setup";
    if (s.flow === "quick")   return "setup · quick";
    if (s.flow === "full")    return "setup · full";
    if (s.flow === "restore") return "setup · restore";
    return "setup";
  })();

  const inHandoff = s.cursor === 12;

  // Helper: wrap a screen in ScreenGate when the cursor maps to a
  // gateable key. Children only render after the gate resolves.
  // Safe-degraded if ScreenGate isn't loaded (older preview shells).
  function Gated(children) {
    const key = GATEABLE[s.cursor];
    if (!key || !window.ScreenGate) return children;
    return (
      <window.ScreenGate
        screenKey={key} s={s}
        keepCurrent={keepCurrent}
        reconfigure={reconfigure}
        skip={skip}
      >{children}</window.ScreenGate>
    );
  }

  return (
    <div className="setup-pane" data-handoff={inHandoff ? "true" : "false"}>
      <div className="setup-body">
        <div className="setup-head">
          <VellumAvatar size={32} state={s.ui.avatar} />
          <div className="ident">
            <b>vellum</b>
            <span className="crumb"><span className="cur">{crumbLabel}</span></span>
          </div>
          <div className="ident" style={{color: "var(--text-faint)"}}>
            {s.cursor === 1 ? "" : (inHandoff ? "" : `screen ${s.cursor}`)}
          </div>
        </div>

        <div className="setup-stage" key={s.cursor}>
          {s.cursor === 1  && <window.IntroScreen        onAdvance={next} />}
          {s.cursor === 2  && <window.ModeScreen         s={s} set={setRoot} onAdvance={next} />}
          {s.cursor === 3  && <window.HardwareScreen     s={s} setRoot={setRoot} onAdvance={next} />}
          {s.cursor === 4  && Gated(<window.ModelScreen        s={s} set={set} onAdvance={next} />)}
          {s.cursor === 5  && Gated(<window.CloudScreen        s={s} set={set} onAdvance={next} persistNow={persistNow} />)}
          {s.cursor === 6  && <window.SovereigntyScreen  s={s} set={set} onAdvance={next} />}
          {s.cursor === 7  && Gated(<window.LearningScreen     s={s} set={set} onAdvance={next} />)}
          {s.cursor === 8  && Gated(<window.SkillsScreen       s={s} setRoot={setRoot} onAdvance={next} />)}
          {s.cursor === 9  && Gated(<window.MCPScreen          s={s} setRoot={setRoot} onAdvance={next} persistNow={persistNow} />)}
          {s.cursor === 10 && Gated(<window.PersonalizeScreen  s={s} set={set} onAdvance={next} persistNow={persistNow} />)}
          {s.cursor === 11 && <window.SummaryScreen      s={s} onAdvance={next} />}
          {s.cursor === 12 && <window.HandoffScreen      s={s} />}
        </div>

        <div className="setup-footer">
          {s.cursor > 1 && !inHandoff && (
            <>
              <span className="h"><kbd>ESC</kbd> back</span>
              <span className="h"><kbd>⌘K</kbd> palette</span>
              <span className="h"><kbd>/</kbd> slash command</span>
              <span className="h"><kbd>Ctrl+C</kbd> exit setup</span>
            </>
          )}
          {s.cursor === 1 && <span className="h">vellum is dithering in — any key skips</span>}
        </div>
      </div>

      <window.SetupSidebar s={s} />

      {/* expose state to the preview chrome for the badge & status bar */}
      <Bridge s={s} />
    </div>
  );
}

function Bridge({ s }) {
  useSP_useEffect(() => {
    window.__vellumSetupState = s;
    window.dispatchEvent(new CustomEvent("vellum-setup-state"));
  }, [s]);
  return null;
}

window.SetupPane = SetupPane;
window.GATEABLE  = GATEABLE;
