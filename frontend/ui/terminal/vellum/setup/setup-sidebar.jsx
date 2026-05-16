/* Vellum setup — sidebar (repurposed Dashboard rail)
   Content is screen-aware. Same dimensions as LightTerm's
   Dashboard so the chrome doesn't reflow when entering setup. */

function SetupSidebar({ s }) {
  return (
    <div className="setup-sidebar">
      {s.cursor === 1 && <SS_Minimal note="vellum 0.1.0 · build d3a8" />}
      {s.cursor === 2 && <SS_Minimal note="vellum 0.1.0 · build d3a8" />}
      {s.cursor === 3 && <SS_Hardware s={s} />}
      {s.cursor === 4 && <SS_Model s={s} />}
      {s.cursor === 5 && <SS_Cloud s={s} />}
      {s.cursor === 6 && <SS_Sovereignty />}
      {s.cursor === 7 && <SS_Learning s={s} />}
      {s.cursor === 8 && <SS_Skills s={s} />}
      {s.cursor === 9 && <SS_MCP s={s} />}
      {s.cursor === 10 && <SS_Personalize s={s} />}
      {s.cursor === 11 && <SS_Summary s={s} />}
      {s.cursor === 12 && null /* chrome dissolves on handoff */}
    </div>
  );
}

/* Screens 1 & 2 — minimal, just identity + promise ─────── */
function SS_Minimal({ note }) {
  return (
    <>
      <div className="ss-section">
        <div className="ss-label">Identity</div>
        <div className="model-preview">
          <div className="row"><span>version</span><span className="v">{note}</span></div>
          <div className="row"><span>install</span><span className="v">~/.vellum/</span></div>
          <div className="row"><span>license</span><span className="v">MIT</span></div>
        </div>
      </div>
      <div className="ss-section">
        <div className="ss-label">Promise</div>
        <div className="notice" style={{lineHeight: 1.6, color: "var(--text-dim)"}}>
          No telemetry. No phone-home. <br />
          Everything written here lives in <br />
          <span style={{color: "var(--text)"}}>~/.vellum/</span> as plain files.
        </div>
      </div>
    </>
  );
}

/* Screen 3 — hardware metric cards (live detection) ─────── */
function SS_Hardware({ s }) {
  const hw = s.hw;
  const cards = [
    { label: "RAM",   value: hw?.ramGB,      unit: "GB", meta: hw?.ramMeta },
    { label: "VRAM",  value: hw?.vramGB,     unit: "GB", meta: hw?.gpuName },
    { label: "Disk",  value: hw?.freeDiskGB, unit: "GB free", meta: hw?.diskMeta },
    { label: "CPU",   value: hw?.cpuCores,   unit: "cores", meta: hw?.cpuName },
  ];
  return (
    <>
      <div className="ss-section">
        <div className="ss-label">
          <span>Hardware</span>
          <span className={"tag " + (hw ? "" : "idle")}>{hw ? "detected" : "scanning…"}</span>
        </div>
        {cards.map((c, i) => (
          <div key={c.label} className={"metric-card " + (c.value == null ? "scanning" : "detected")}
               style={{animationDelay: (i * 80) + "ms"}}>
            <div className="label">{c.label}</div>
            <div className="value">
              {c.value == null ? "—" : (
                <>{c.value}<span className="unit"> {c.unit}</span></>
              )}
            </div>
            {c.meta && <div className="meta">{c.meta}</div>}
          </div>
        ))}
      </div>
    </>
  );
}

/* Screen 4 — selected model preview + download progress ──── */
function SS_Model({ s }) {
  const lm = s.localModel;
  const downloading = lm.status === "downloading";
  const ready = lm.status === "ready";

  return (
    <>
      <div className="ss-section">
        <div className="ss-label">
          <span>Selected</span>
          <span className={"tag " + (lm.id ? "" : "idle")}>{lm.id ? "ready to pull" : "no model"}</span>
        </div>
        {lm.id ? (
          <div className="model-preview">
            <div className="row"><span>model</span><span className="v">{lm.id}</span></div>
            <div className="row"><span>size</span><span className="v">{lm.sizeGB} GB</span></div>
            <div className="row"><span>context</span><span className="v">{lm.contextK}K</span></div>
            <div className="row"><span>quantization</span><span className="v">{lm.quant}</span></div>
            <div className="row"><span>throughput</span><span className="v">~{lm.tps} t/s</span></div>
            <div className="row"><span>fit</span>
              <span className={"v"} style={{color:
                lm.fit === "good" ? "var(--accent)" :
                lm.fit === "swap" ? "var(--amber)" : "var(--red)"
              }}>
                {lm.fit === "good" ? "comfortable" : lm.fit === "swap" ? "will swap" : "won't fit"}
              </span>
            </div>
          </div>
        ) : (
          <div className="notice">Choose a model on the left to see fit and download details here.</div>
        )}
      </div>

      {(downloading || ready) && (
        <div className="ss-section">
          <div className="ss-label">
            <span>Download</span>
            <span className={"tag " + (ready ? "" : "")}>{ready ? "complete" : "active"}</span>
          </div>
          <div className="dl-card">
            <div className="head">
              <span>{lm.id}</span>
              <span className="pct">{ready ? "100" : lm.pct.toFixed(1)}%</span>
            </div>
            <div className="bar"><div className="fill" style={{width: (ready ? 100 : lm.pct) + "%"}} /></div>
            <div className="stats">
              <span>{ready ? "—" : (lm.speed + " MB/s")}</span>
              <span>{ready ? "done" : ("eta " + lm.eta)}</span>
            </div>
          </div>
        </div>
      )}

      <div className="ss-section">
        <div className="ss-label">From disk</div>
        <div className="notice" style={{lineHeight: 1.6}}>
          Models land at <span style={{color: "var(--text)"}}>~/.vellum/models/</span>.<br />
          Existing local models are reused — no re-download.
        </div>
      </div>
    </>
  );
}

window.SetupSidebar = SetupSidebar;

/* Screen 5 — provider preview + latency probe ───────────── */
function SS_Cloud({ s }) {
  const c = s.cloud;
  const ENDPOINTS = {
    anthropic:  "api.anthropic.com",
    openai:     "api.openai.com",
    google:     "generativelanguage.googleapis.com",
    openrouter: "openrouter.ai/api/v1",
    groq:       "api.groq.com/openai/v1",
    custom:     "—",
    none:       "—",
  };
  const LABELS = {
    anthropic: "Anthropic",
    openai: "OpenAI",
    google: "Google",
    openrouter: "OpenRouter",
    groq: "Groq",
    custom: "Custom",
    none: "—",
  };
  const showProbe = c.provider && c.provider !== "none";
  return (
    <>
      <div className="ss-section">
        <div className="ss-label">
          <span>Provider</span>
          <span className={"tag " + (c.provider && c.provider !== "none" ? "" : "idle")}>
            {c.provider === "none" || !c.provider ? "skipped" : (c.keyRef ? "ready" : "selecting…")}
          </span>
        </div>
        <div className="model-preview">
          <div className="row"><span>name</span><span className="v">{c.provider && c.provider !== "none" ? LABELS[c.provider] : "Skipped"}</span></div>
          <div className="row"><span>endpoint</span><span className="v">{ENDPOINTS[c.provider] || "—"}</span></div>
          <div className="row"><span>key</span><span className="v">{c.keyTail ? "···· " + c.keyTail : "—"}</span></div>
          <div className="row"><span>storage</span><span className="v" style={{fontSize: 10.5, letterSpacing: 0.04}}>~/.vellum/.env</span></div>
        </div>
      </div>

      {showProbe && (
        <div className="ss-section">
          <div className="ss-label">
            <span>Latency probe</span>
            <span className="tag">{c.keyRef ? "" : "waiting"}</span>
          </div>
          <div className="metric-card detected">
            <div className="label">Round-trip</div>
            <div className="value">{c.keyRef ? "212" : "—"}<span className="unit"> ms</span></div>
            <div className="meta">{c.keyRef ? "1 of 1 healthy" : "probe runs after key"}</div>
          </div>
        </div>
      )}

      <div className="ss-section">
        <div className="ss-label">Routing</div>
        <div className="notice" style={{lineHeight: 1.6}}>
          Local runs by default. Cloud is used only when you ask for it explicitly, or for tasks the local model can't reach.
        </div>
      </div>
    </>
  );
}

/* Screen 6 — sidebar collapses (intentional) ────────────── */
function SS_Sovereignty() {
  return (
    <div className="ss-quiet">
      <b>—</b><br />
      <span style={{color: "var(--text-faint)"}}>The screen is the message.</span>
    </div>
  );
}

/* Screen 7 — DATA AT REST: file paths preview ───────────── */
function SS_Learning({ s }) {
  const enabled = Object.values(s.learning).filter(Boolean).length;
  return (
    <>
      <div className="ss-section">
        <div className="ss-label">
          <span>Sources</span>
          <span className="tag">{enabled} of 3 on</span>
        </div>
        <div className="cat-list">
          <div className="row"><span>conversations</span><span className={"v " + (s.learning.conversations ? "ok" : "dim")}>{s.learning.conversations ? "on" : "off"}</span></div>
          <div className="row"><span>files</span><span className={"v " + (s.learning.files ? "ok" : "dim")}>{s.learning.files ? "on" : "off"}</span></div>
          <div className="row"><span>terminal</span><span className={"v " + (s.learning.terminal ? "ok" : "dim")}>{s.learning.terminal ? "on" : "off"}</span></div>
        </div>
      </div>

      <div className="ss-section">
        <div className="ss-label">Data at rest</div>
        <div className="model-preview">
          <div className="row"><span>journal</span><span className="v">~/.vellum/journal.md</span></div>
          <div className="row"><span>memory</span><span className="v">~/.vellum/memory.sqlite</span></div>
          <div className="row"><span>logs</span><span className="v">~/.vellum/logs/</span></div>
        </div>
        <div className="notice">All plaintext or SQLite. Inspect with any editor.</div>
      </div>

      {s.learning.terminal && (
        <div className="ss-section">
          <div className="ss-label" style={{color: "var(--amber)"}}>Heads-up</div>
          <div className="notice" style={{color: "var(--text-dim)", lineHeight: 1.6}}>
            Terminal capture watches LightTerm panes only. Output is filtered for secrets (env, .env, keys) before write.
          </div>
        </div>
      )}
    </>
  );
}

/* Screen 8 — Selected · n  with per-category tally ──────── */
function SS_Skills({ s }) {
  const skills = s.skills || [];
  const total = skills.length || 12;
  const on = skills.filter(sk => sk.enabled).length;
  const cats = ["Writing", "Coding", "Research", "Daily"];
  const byCat = (cat) => {
    const items = skills.filter(sk => sk.category === cat);
    return { on: items.filter(sk => sk.enabled).length, total: items.length };
  };

  return (
    <>
      <div className="ss-section">
        <div className="ss-label">
          <span>Selected</span>
          <span className="tag">live</span>
        </div>
        <div className="metric-card detected">
          <div className="label">Skills enabled</div>
          <div className="count-big">{on}<span className="of">/ {total}</span></div>
          <div className="count-tag">
            <span className="ok">{on}</span> active · {total - on} dormant
          </div>
        </div>
      </div>

      <div className="ss-section">
        <div className="ss-label">By category</div>
        <div className="cat-list">
          {cats.map(c => {
            const b = byCat(c);
            return (
              <div key={c} className="row">
                <span>{c.toLowerCase()}</span>
                <span className={"v " + (b.on > 0 ? "ok" : "dim")}>{b.on}/{b.total}</span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="ss-section">
        <div className="ss-label">On disk</div>
        <div className="notice" style={{lineHeight: 1.6}}>
          Each enabled skill becomes <span style={{color: "var(--text-dim)"}}>~/.vellum/skills/{"{name}"}.md</span> — editable, version-controllable.
        </div>
      </div>
    </>
  );
}

/* Screen 9 — MCP server count + per-category + status dots ─ */
function SS_MCP({ s }) {
  const list = s.mcp || [];
  const total = list.length || 11;
  const on = list.filter(m => m.enabled).length;
  const cats = ["Built-in", "Productivity", "Dev tools", "Personal"];
  const byCat = (cat) => {
    const items = list.filter(m => m.category === cat);
    return { on: items.filter(m => m.enabled).length, total: items.length };
  };

  return (
    <>
      <div className="ss-section">
        <div className="ss-label">
          <span>Selected</span>
          <span className="tag">live</span>
        </div>
        <div className="metric-card detected">
          <div className="label">MCP servers</div>
          <div className="count-big">{on}<span className="of">/ {total}</span></div>
          <div className="count-tag">
            <span className="ok">{on}</span> active · {Math.max(0, total - on)} dormant
          </div>
        </div>
      </div>

      <div className="ss-section">
        <div className="ss-label">By category</div>
        <div className="cat-list">
          {cats.map(c => {
            const b = byCat(c);
            return (
              <div key={c} className="row">
                <span>{c.toLowerCase()}</span>
                <span className={"v " + (b.on > 0 ? "ok" : "dim")}>{b.on}/{b.total}</span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="ss-section">
        <div className="ss-label">Status</div>
        <div className="cat-list">
          {list.filter(m => m.enabled).slice(0, 6).map(m => (
            <div key={m.id} className="row">
              <span style={{overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap", maxWidth: 180}}>{m.label}</span>
              <span className="v ok">●</span>
            </div>
          ))}
          {list.filter(m => m.enabled).length === 0 && (
            <div className="notice" style={{padding: "4px 0"}}>No MCP servers enabled yet.</div>
          )}
        </div>
      </div>
    </>
  );
}

/* Screen 10 — what we've captured so far ────────────────── */
function SS_Personalize({ s }) {
  const p = s.personalize;
  return (
    <>
      <div className="ss-section">
        <div className="ss-label">Captured</div>
        <div className="model-preview">
          <div className="row"><span>name</span><span className={"v " + (p.name ? "" : "")} style={{color: p.name ? "var(--accent)" : "var(--text-faint)"}}>{p.name || "—"}</span></div>
          <div className="row"><span>working on</span><span className={"v"} style={{color: p.workingOn ? "var(--accent)" : "var(--text-faint)", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap"}}>{p.workingOn || "—"}</span></div>
        </div>
      </div>
      <div className="ss-section">
        <div className="ss-label">Why</div>
        <div className="notice" style={{lineHeight: 1.6}}>
          Your <span style={{color: "var(--text)"}}>name</span> shapes my greeting only.<br />
          Your <span style={{color: "var(--text)"}}>working-on</span> becomes the first dated line of <span style={{color: "var(--text-dim)"}}>journal.md</span>.
          <br /><br />
          Both stay on this machine.
        </div>
      </div>
    </>
  );
}

/* Screen 11 — small summary glance ──────────────────────── */
function SS_Summary({ s }) {
  const local = !!(s.localModel && s.localModel.id);
  const cloud = s.cloud && s.cloud.provider && s.cloud.provider !== "none";
  const cloudReady = cloud && !!s.cloud.keyRef;
  const learnOn = Object.values(s.learning).filter(Boolean).length;
  const skillsOn = (s.skills || []).filter(sk => sk.enabled).length;
  const mcpOn = (s.mcp || []).filter(m => m.enabled).length;
  const sov = !!s.sovereignty.acknowledgedAt;
  const name = !!s.personalize.name;
  const work = !!s.personalize.workingOn;

  const ok = [local, cloudReady, sov, learnOn > 0, skillsOn > 0, mcpOn > 0, name, work].filter(Boolean).length;
  const total = 8;

  return (
    <>
      <div className="ss-section">
        <div className="ss-label">
          <span>Configuration</span>
          <span className="tag">final</span>
        </div>
        <div className="metric-card detected">
          <div className="label">Ready</div>
          <div className="count-big">{ok}<span className="of">/ {total}</span></div>
          <div className="count-tag"><span className="ok">{ok}</span> configured · {total - ok} not</div>
        </div>
      </div>
      <div className="ss-section">
        <div className="ss-label">Next</div>
        <div className="notice" style={{lineHeight: 1.6}}>
          Press <span style={{color: "var(--accent)", fontFamily: "var(--mono)"}}>ENTER</span> and the chrome falls away. You'll see Vellum.
        </div>
      </div>
    </>
  );
}
