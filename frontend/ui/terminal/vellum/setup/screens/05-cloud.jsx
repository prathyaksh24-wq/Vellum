/* Screen 5 — Cloud augmentation (optional, skippable)
   Two phases on one screen:
     1) provider radio list — default selection is "Skip"
     2) if non-skip chosen, an `❭ _` key-input slides in below
   ENTER on Skip advances. ENTER on a provider focuses the input.
   ENTER on the input (with a value) commits + advances. */

const { useState: useCloud_useState, useEffect: useCloud_useEffect, useRef: useCloud_useRef } = React;

/* Provider catalog — mirrors backend/agent/llm/providers.py.
   OpenRouter is the default broker (ZDR enforced, data_collection=deny);
   direct provider keys are also accepted and bypass OpenRouter when set. */
const CLOUD_PROVIDERS = [
  { id: "skip",       label: "Skip",                 sub: "— local-only. You can add a cloud model later with `vellum cloud`." },
  { id: "openrouter", label: "OpenRouter",           sub: "— recommended · single key, ZDR-only routing across every provider below" },
  { id: "anthropic",  label: "Anthropic (Claude)",   sub: "— claude opus 4.7, haiku 4.5 · direct API" },
  { id: "openai",     label: "OpenAI (GPT)",         sub: "— gpt-4o, gpt-4o-mini · direct API" },
  { id: "google",     label: "Google (Gemini)",      sub: "— gemini 2.5 pro, gemma 4 31b" },
  { id: "xai",        label: "xAI (Grok)",           sub: "— grok 4, grok 4 fast" },
  { id: "deepseek",   label: "DeepSeek",             sub: "— deepseek v4, deepseek r1 · open weights" },
  { id: "meta",       label: "Meta (Llama)",         sub: "— llama 3.3 70b, llama 3.2 3b · open weights" },
  { id: "groq",       label: "Groq",                 sub: "— fast inference, open models" },
  { id: "custom",     label: "Custom endpoint",      sub: "— any OpenAI-compatible URL" },
];

function CloudScreen({ s, set, onAdvance, persistNow }) {
  const start = CLOUD_PROVIDERS.findIndex(p => p.id === (s.cloud.provider || "skip"));
  const [idx, setIdx] = useCloud_useState(start < 0 ? 0 : start);
  const [phase, setPhase] = useCloud_useState("pick"); // "pick" | "key"
  const [keyVal, setKeyVal] = useCloud_useState("");
  const keyRef = useCloud_useRef(null);

  const cur = CLOUD_PROVIDERS[idx];

  // ─── pick phase keys
  useCloud_useEffect(() => {
    if (phase !== "pick") return;
    const h = (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); setIdx(i => Math.min(CLOUD_PROVIDERS.length - 1, i + 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setIdx(i => Math.max(0, i - 1)); }
      else if (/^[1-9]$/.test(e.key)) {
        const n = parseInt(e.key, 10) - 1;
        if (n < CLOUD_PROVIDERS.length) setIdx(n);
      }
      else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        const p = CLOUD_PROVIDERS[idx];
        if (p.id === "skip") {
          set("cloud", { provider: "none" });
          onAdvance();
        } else {
          set("cloud", { provider: p.id });
          setPhase("key");
        }
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [idx, phase, set, onAdvance]);

  // ─── key phase keys
  useCloud_useEffect(() => {
    if (phase !== "key") return;
    keyRef.current && keyRef.current.focus();
    const h = (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        setPhase("pick");
        setKeyVal("");
      } else if (e.key === "Enter") {
        e.preventDefault();
        e.stopPropagation();
        if (keyVal.trim().length > 8) {
          set("cloud", { provider: cur.id, keyRef: "~/.vellum/.env#" + cur.id.toUpperCase() + "_API_KEY", keyTail: keyVal.slice(-4) });
          onAdvance();
        }
      }
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [phase, keyVal, cur, set, onAdvance]);

  return (
    <div className="oc-section">
      <div className="oc-line">
        <span className="oc-marker">◆</span>
        <span className="oc-title">Cloud augmentation</span>
      </div>
      <div className="oc-desc">
        Use a cloud model for hard tasks while everything else stays local. Optional — Vellum is fully useful without it.
      </div>

      {phase === "pick" && (
        <>
          <div className="oc-question">Connect a cloud provider? <span style={{color:"var(--text-faint)", fontSize: "11.5px", letterSpacing: "0.04em"}}>(Skip is fine — recommended for first run)</span></div>
          <div className="oc-hint">
            <span className="seg"><kbd>↑↓</kbd> navigate</span>
            <span className="seg"><kbd>1–{CLOUD_PROVIDERS.length}</kbd> jump</span>
            <span className="seg"><kbd>ENTER</kbd> select</span>
            <span className="seg"><kbd>ESC</kbd> back</span>
          </div>

          <div className="oc-list">
            {CLOUD_PROVIDERS.map((p, i) => (
              <div
                key={p.id}
                className={"oc-row " + (i === idx ? "sel" : "")}
                onMouseEnter={() => setIdx(i)}
                onClick={() => {
                  setIdx(i);
                  if (p.id === "skip") { set("cloud", { provider: "none" }); onAdvance(); }
                  else { set("cloud", { provider: p.id }); setPhase("key"); }
                }}
              >
                <span className="arr">→</span>
                <span className="glyph">{i === idx ? "(•)" : "(o)"}</span>
                <span className="label">{p.label}</span>
                <span className="sub">{p.sub}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {phase === "key" && (
        <>
          <div className="oc-question">Paste your <span style={{color:"var(--text)"}}>{cur.label}</span> API key:</div>
          <div className="oc-hint">
            <span className="seg"><kbd>ENTER</kbd> save &amp; continue</span>
            <span className="seg"><kbd>ESC</kbd> pick a different provider</span>
          </div>

          <div className="oc-input">
            <span className="prompt">❭</span>
            <input
              ref={keyRef}
              type="password"
              value={keyVal}
              onChange={(e) => setKeyVal(e.target.value)}
              onBlur={() => persistNow && persistNow()}
              placeholder={"sk-... (stored at ~/.vellum/.env, never sent anywhere except " + cur.label + ")"}
            />
          </div>

          <div className="key-state">
            {keyVal.length === 0 && <span className="dim">no key yet · paste or press ESC to go back</span>}
            {keyVal.length > 0 && keyVal.length <= 8 && <span className="warn">⚠ that looks short — most keys are 30+ characters</span>}
            {keyVal.length > 8 && <span className="ok">✓ looks like a key · ENTER to save</span>}
          </div>

          <div style={{marginTop: 18, color: "var(--text-faint)", fontSize: 11.5, fontFamily: "var(--mono)", letterSpacing: 0.02, lineHeight: 1.6, maxWidth: 560}}>
            Your key is written to <span style={{color: "var(--text-dim)"}}>~/.vellum/.env</span> with mode <span style={{color: "var(--text-dim)"}}>0600</span>. Vellum reads it only to make requests you initiate — it isn't included in journal exports.
          </div>
        </>
      )}
    </div>
  );
}

window.CloudScreen = CloudScreen;
