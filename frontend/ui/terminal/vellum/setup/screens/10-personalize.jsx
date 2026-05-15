/* Screen 10 — Personalization (name + working-on)
   Two staged inputs, in sequence, on one screen.

     Q1: What should I call you?       → captures personalize.name
     Q2: What are you working on…      → captures personalize.workingOn

   Both ESC-skippable. ENTER on a value commits and advances to the
   next question. ENTER on an empty input also advances (skip).
   Once both are resolved, ENTER advances to summary.

   The captured value from Q1 stays visible above Q2 so the user
   sees what Vellum heard. */

const { useState: usePers_useState, useEffect: usePers_useEffect, useRef: usePers_useRef } = React;

function PersonalizeScreen({ s, set, onAdvance, persistNow }) {
  const [phase, setPhase] = usePers_useState(() => {
    // resume: if name already captured (rerun), jump to phase 2
    if (s.personalize.name) return "workingOn";
    return "name";
  });
  const [nameVal, setNameVal] = usePers_useState(s.personalize.name || "");
  const [workVal, setWorkVal] = usePers_useState(s.personalize.workingOn || "");

  const nameRef = usePers_useRef(null);
  const workRef = usePers_useRef(null);

  // ── focus management
  usePers_useEffect(() => {
    if (phase === "name") nameRef.current && nameRef.current.focus();
    else if (phase === "workingOn") workRef.current && workRef.current.focus();
  }, [phase]);

  // ── keys for the active input
  usePers_useEffect(() => {
    const h = (e) => {
      if (phase === "name") {
        if (e.key === "Enter") {
          e.preventDefault(); e.stopPropagation();
          const v = nameVal.trim();
          set("personalize", { name: v || null });
          setPhase("workingOn");
        } else if (e.key === "Escape") {
          e.preventDefault(); e.stopPropagation();
          // skip name → go to phase 2, or back if already past
          set("personalize", { name: null });
          setNameVal("");
          setPhase("workingOn");
        }
      } else if (phase === "workingOn") {
        if (e.key === "Enter") {
          e.preventDefault(); e.stopPropagation();
          const v = workVal.trim();
          set("personalize", { workingOn: v || null, capturedAt: new Date().toISOString() });
          onAdvance();
        } else if (e.key === "Escape") {
          e.preventDefault(); e.stopPropagation();
          set("personalize", { workingOn: null, capturedAt: new Date().toISOString() });
          setWorkVal("");
          onAdvance();
        }
      }
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [phase, nameVal, workVal, set, onAdvance]);

  const nameCaptured = phase === "workingOn";
  const nameValue = (s.personalize.name || nameVal).trim();

  return (
    <div className="oc-section">
      <div className="oc-line">
        <span className="oc-marker">◆</span>
        <span className="oc-title">Personalization</span>
      </div>
      <div className="oc-desc">
        A couple of optional things, so I don't start cold. Skip either with <kbd style={{fontFamily:"var(--mono)",color:"var(--text-dim)",border:"1px solid var(--border-soft)",padding:"0 5px"}}>ESC</kbd>.
      </div>

      <div className="pers-stage">
        {/* Q1 — name */}
        <div className={"pers-q " + (nameCaptured ? "complete" : "")}>
          <span className="num">Q1 ·</span>
          <span className="text">What should I call you?</span>
        </div>

        {phase === "name" ? (
          <>
            <div className="oc-hint">
              <span className="seg"><kbd>ENTER</kbd> save &amp; continue</span>
              <span className="seg"><kbd>ESC</kbd> skip — I'll just say "Hi."</span>
            </div>
            <div className="oc-input" style={{borderBottomColor: "var(--accent)"}}>
              <span className="prompt">❭</span>
              <input
                ref={nameRef}
                value={nameVal}
                onChange={(e) => setNameVal(e.target.value)}
                onBlur={() => persistNow && persistNow()}
                placeholder="(first name, nickname, anything you like)"
                maxLength={48}
              />
            </div>
          </>
        ) : (
          <div className={"pers-captured " + (nameValue ? "" : "skipped")}>
            <span className="lbl">name</span>
            {nameValue ? (
              <span className="v">{nameValue}</span>
            ) : (
              <span className="v">— skipped</span>
            )}
          </div>
        )}

        {/* Q2 — working on */}
        {phase === "workingOn" && (
          <>
            <div className="pers-q" style={{marginTop: 28}}>
              <span className="num">Q2 ·</span>
              <span className="text">What are you working on these days?</span>
            </div>
            <div className="oc-hint">
              <span className="seg"><kbd>ENTER</kbd> save &amp; continue</span>
              <span className="seg"><kbd>ESC</kbd> skip</span>
            </div>
            <div className="oc-input" style={{borderBottomColor: "var(--accent)"}}>
              <span className="prompt">❭</span>
              <input
                ref={workRef}
                value={workVal}
                onChange={(e) => setWorkVal(e.target.value)}
                onBlur={() => persistNow && persistNow()}
                placeholder="one sentence is plenty — becomes the first line of your journal"
                maxLength={140}
              />
            </div>
          </>
        )}
      </div>

      <div style={{marginTop: 30, fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--text-faint)", lineHeight: 1.6, maxWidth: 560}}>
        {phase === "name"
          ? "Used only when I greet you. Never exported, never sent anywhere."
          : "Becomes the first dated entry in ~/.vellum/journal.md so I can pick up where you are."}
      </div>
    </div>
  );
}

window.PersonalizeScreen = PersonalizeScreen;
