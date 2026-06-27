/* Screen 12 — Handoff (the room changes)
   The wizard chrome dissolves (parent SetupPane sets data-handoff="true"
   on the .setup-pane when cursor === 12). What stays:
     - the avatar (top-left of the setup-head; unchanged)
     - a one-line agent status
     - one line of Vellum's voice (uses captured name if present)
     - the `❭ _` prompt input
   When the user submits, their message appears, Vellum replies once.
   The user never sees a "setup complete" screen. */

const { useState: useHo_useState, useEffect: useHo_useEffect, useRef: useHo_useRef } = React;

function HandoffScreen({ s }) {
  const [thread, setThread] = useHo_useState([]);   // [{ who, body }]
  const [draft, setDraft] = useHo_useState("");
  const inputRef = useHo_useRef(null);

  useHo_useEffect(() => {
    // tab title bridge — preview chrome listens for this
    try { window.dispatchEvent(new CustomEvent("vellum-handoff", { detail: { name: s.personalize.name } })); } catch (e) {}
    const t = setTimeout(() => inputRef.current && inputRef.current.focus(), 900);
    return () => clearTimeout(t);
  }, [s.personalize.name]);

  const submit = () => {
    const v = draft.trim();
    if (!v) return;
    setThread(prev => [...prev, { who: "you", body: v }]);
    setDraft("");
    // Vellum's calm one-shot reply
    setTimeout(() => {
      setThread(prev => [...prev, {
        who: "vellum",
        body: pickReply(v, s.personalize.name),
      }]);
    }, 700);
  };

  const lm = s.localModel;
  const learnList = Object.entries(s.learning).filter(([, v]) => v).map(([k]) => k).join(" + ") || "nothing yet";
  const skillsOn = (s.skills || []).filter(sk => sk.enabled).length;
  const mcpOn = (s.mcp || []).filter(m => m.enabled).length;
  const cloud = s.cloud.provider && s.cloud.provider !== "none" ? s.cloud.provider : "off";

  const greeting = (() => {
    const n = (s.personalize.name || "").trim();
    if (!n) return "Hi. Want to tell me what you're working on, or sit quietly until you call?";
    if (s.personalize.workingOn) return `Hi, ${n}. You mentioned you're working on ${quoteShort(s.personalize.workingOn)} — want to keep going, or sit quietly until you call?`;
    return `Hi, ${n}. Want to tell me what you're working on, or sit quietly until you call?`;
  })();

  return (
    <div className="agent-view">
      <div className="av-head">
        <span className="name">vellum</span>
        <span className="meta">ready</span>
      </div>
      <div className="status">
        <span><span className="k">local:</span> <span className="v">{lm.id || "—"}</span></span>
        <span className="sep">·</span>
        <span><span className="k">cloud:</span> <span className="v">{cloud}</span></span>
        <span className="sep">·</span>
        <span><span className="k">learning:</span> <span className="v">{learnList}</span></span>
        <span className="sep">·</span>
        <span><span className="v">{skillsOn}</span> <span className="k">skills</span></span>
        <span className="sep">·</span>
        <span><span className="v">{mcpOn}</span> <span className="k">mcp</span></span>
      </div>

      <div className="voice">
        {greeting}
      </div>

      {thread.map((m, i) => (
        m.who === "you" ? (
          <div key={i} className="you-msg"><span className="who">you</span><span className="body">{m.body}</span></div>
        ) : (
          <div key={i} className="vellum-reply"><span className="who">vellum</span><span className="body">{m.body}</span></div>
        )
      ))}

      <div className="prompt-row">
        <span className="sigil">❭</span>
        {window.SlashAwareInput ? (
          <window.SlashAwareInput
            value={draft}
            onChange={setDraft}
            onSubmit={(v) => { setDraft(v); submit(); }}
            onCommand={(cmd) => {
              setThread(prev => [...prev, { who: "you", body: "/" + cmd }]);
              setDraft("");
              setTimeout(() => {
                setThread(prev => [...prev, {
                  who: "vellum",
                  body: "I'll know that command soon — slash palette ships next.",
                }]);
              }, 600);
            }}
            inputRef={inputRef}
            placeholder={thread.length === 0 ? "say something, or press / for a command — I'm not going anywhere." : "keep going…"}
          />
        ) : (
          <input
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } }}
            placeholder={thread.length === 0 ? "say something, or just close the tab — I'm not going anywhere." : "keep going…"}
          />
        )}
      </div>
    </div>
  );
}

function quoteShort(s) {
  if (!s) return "";
  if (s.length > 60) return `"${s.slice(0, 60)}…"`;
  return `"${s}"`;
}

function pickReply(_msg, name) {
  // Calm. Direct. No exclamation marks. Match the OC tone.
  const lines = [
    name ? `Got it, ${name}. I'll keep that in mind.` : "Got it. I'll keep that in mind.",
    "Noted. I'll be here when you're ready.",
    "Logged. Anything else?",
    "Heard. Ask me when you want to pick it up.",
  ];
  return lines[Math.floor(Math.random() * lines.length)];
}

window.HandoffScreen = HandoffScreen;
