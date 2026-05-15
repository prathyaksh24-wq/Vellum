/* Screen 9 — MCP servers (categorized + custom URL)
   Same `[ ]`/`[x]` pattern as skills. After the list, a `❭ _`
   input lets the user paste a custom MCP URL. Tab toggles focus
   between the list and the input; ENTER on the list continues,
   ENTER on the input adds the URL. */

const { useState: useMCP_useState, useEffect: useMCP_useEffect, useMemo: useMCP_useMemo, useRef: useMCP_useRef } = React;

/* MCP catalog
   "Built-in" group mirrors the servers that already ship with the
   backend (agent/mcp/client.py · SERVER_RUNNERS). They are on by
   default and scoped per CLAUDE.md §3:
     – Filesystem MCP is restricted to OBSIDIAN_VAULT_PATH
     – Apify MCP is used only for the Amazon/YouTube scrapers
   The remaining groups are optional additions that get appended
   to the user's ~/.vellum/mcp.yaml on completion. */
const MCP_DEFAULT = [
  { id: "b.filesystem", category: "Built-in",     label: "Filesystem",       sub: "— scoped to OBSIDIAN_VAULT_PATH · read-only fetch", url: "builtin://filesystem",      enabled: true,  builtin: true },
  { id: "b.apify",      category: "Built-in",     label: "Apify",            sub: "— Amazon + YouTube scrapers · output scrubbed before LLM", url: "https://mcp.apify.com/sse", enabled: true,  builtin: true },

  { id: "p.notion",     category: "Productivity", label: "Notion",           sub: "— pages, databases (read+write)", url: "mcp://notion",                    enabled: false },
  { id: "p.linear",     category: "Productivity", label: "Linear",           sub: "— issues, projects",              url: "mcp://linear",                    enabled: false },
  { id: "p.gcal",       category: "Productivity", label: "Google Calendar",  sub: "— next 7 days · read-only",       url: "mcp://gcal",                      enabled: false },

  { id: "d.github",     category: "Dev tools",    label: "GitHub",           sub: "— repos, PRs, issues",            url: "mcp://github",                    enabled: true  },
  { id: "d.fs.work",    category: "Dev tools",    label: "Filesystem (~/work)", sub: "— second filesystem mount, scoped to ~/work/", url: "mcp://fs?root=~/work",  enabled: false },
  { id: "d.shell",      category: "Dev tools",    label: "Shell",            sub: "— run vetted commands · confirmation required", url: "mcp://shell",        enabled: false },

  { id: "x.notes",      category: "Personal",     label: "Apple Notes",      sub: "— search + add notes",            url: "mcp://apple-notes",               enabled: false },
  { id: "x.pocket",     category: "Personal",     label: "Pocket",           sub: "— saved articles",                url: "mcp://pocket",                    enabled: false },
  { id: "x.spotify",    category: "Personal",     label: "Spotify",          sub: "— now-playing + queue (read)",    url: "mcp://spotify",                   enabled: false },
];

function MCPScreen({ s, setRoot, onAdvance, persistNow }) {
  // seed on first mount
  useMCP_useEffect(() => {
    if (!s.mcp || s.mcp.length === 0) setRoot("mcp", MCP_DEFAULT.map(m => ({ ...m })));
  }, []); // eslint-disable-line

  const list = (s.mcp && s.mcp.length) ? s.mcp : MCP_DEFAULT;

  const order = ["Built-in", "Productivity", "Dev tools", "Personal"];
  const grouped = useMCP_useMemo(() => order.map(cat => ({ cat, items: list.filter(m => m.category === cat) })), [list]);
  const flat = useMCP_useMemo(() => grouped.flatMap(g => g.items), [grouped]);

  const [idx, setIdx] = useMCP_useState(0);
  const [focus, setFocus] = useMCP_useState("list");  // "list" | "input"
  const [urlVal, setUrlVal] = useMCP_useState("");
  const urlRef = useMCP_useRef(null);

  useMCP_useEffect(() => {
    if (focus === "input") urlRef.current && urlRef.current.focus();
  }, [focus]);

  // ── list keys
  useMCP_useEffect(() => {
    if (focus !== "list") return;
    const h = (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); setIdx(i => Math.min(flat.length - 1, i + 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setIdx(i => Math.max(0, i - 1)); }
      else if (e.key === " ") {
        e.preventDefault();
        const t = flat[idx];
        setRoot("mcp", list.map(m => m.id === t.id ? { ...m, enabled: !m.enabled } : m));
      }
      else if (e.key === "Tab") {
        e.preventDefault();
        setFocus("input");
      }
      else if (e.key === "Enter") {
        e.preventDefault();
        onAdvance();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [focus, idx, flat, list, setRoot, onAdvance]);

  // ── url input keys
  useMCP_useEffect(() => {
    if (focus !== "input") return;
    const h = (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setFocus("list"); }
      else if (e.key === "Tab") { e.preventDefault(); setFocus("list"); }
      else if (e.key === "Enter") {
        e.preventDefault(); e.stopPropagation();
        const v = urlVal.trim();
        if (v.length > 4) {
          const id = "custom." + Math.random().toString(36).slice(2, 7);
          setRoot("mcp", [...list, {
            id, category: "Personal", label: "Custom", sub: "— " + v, url: v, enabled: true,
          }]);
          setUrlVal("");
          setFocus("list");
        } else {
          // empty enter → continue
          onAdvance();
        }
      }
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [focus, urlVal, list, setRoot, onAdvance]);

  const enabledCount = flat.filter(m => m.enabled).length;

  return (
    <div className="oc-section">
      <div className="oc-line">
        <span className="oc-marker">◆</span>
        <span className="oc-title">MCP servers</span>
      </div>
      <div className="oc-desc">
        Tools I can call out to. Vellum speaks the MCP protocol — pick what's useful, paste a URL for anything custom.
      </div>

      <div className="oc-question">Toggle MCP servers to enable:</div>
      <div className="oc-hint">
        <span className="seg"><kbd>↑↓</kbd> navigate</span>
        <span className="seg"><kbd>SPACE</kbd> toggle</span>
        <span className="seg"><kbd>TAB</kbd> add custom</span>
        <span className="seg"><kbd>ENTER</kbd> continue</span>
        <span className="seg"><kbd>ESC</kbd> back</span>
      </div>

      <div className="oc-list">
        {(() => {
          let flatI = -1;
          const nodes = [];
          for (const g of grouped) {
            const groupCount = g.items.filter(m => m.enabled).length;
            nodes.push(
              <div key={"cat-" + g.cat} className="oc-cat">
                <span></span><span></span>
                <span>
                  <span className="name">{g.cat}</span>
                  <span className="count">{groupCount}/{g.items.length}</span>
                </span>
              </div>
            );
            for (const m of g.items) {
              flatI += 1;
              const i = flatI;
              const on = m.enabled;
              nodes.push(
                <div
                  key={m.id}
                  className={"oc-row skill check " + (focus === "list" && i === idx ? "sel" : "")}
                  onMouseEnter={() => { setIdx(i); setFocus("list"); }}
                  onClick={() => {
                    setIdx(i); setFocus("list");
                    setRoot("mcp", list.map(x => x.id === m.id ? { ...x, enabled: !x.enabled } : x));
                  }}
                >
                  <span className="arr">→</span>
                  <span className="glyph">[{on ? "x" : " "}]</span>
                  <span className="label">{m.label}</span>
                  <span className="sub">{m.sub}</span>
                </div>
              );
            }
          }
          return nodes;
        })()}
      </div>

      <div className="mcp-add">
        <div className="lbl">
          Or add a <b>custom MCP URL</b>:&nbsp;
          <span style={{color: focus === "input" ? "var(--accent)" : "var(--text-faint)"}}>
            {focus === "input" ? "(focused — paste, then ENTER to add)" : "(press TAB to focus)"}
          </span>
        </div>
        <div className="oc-input" style={{borderBottomColor: focus === "input" ? "var(--accent)" : "var(--border-soft)"}}>
          <span className="prompt">❭</span>
          <input
            ref={urlRef}
            value={urlVal}
            onChange={(e) => setUrlVal(e.target.value)}
            onFocus={() => setFocus("input")}
            onBlur={() => persistNow && persistNow()}
            placeholder="mcp://your-server  or  https://your-endpoint/mcp"
          />
        </div>
      </div>

      <div style={{marginTop: 18, fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--text-faint)"}}>
        <span style={{color: "var(--accent)"}}>{enabledCount}</span> of {flat.length} MCP servers enabled.
      </div>
    </div>
  );
}

window.MCPScreen = MCPScreen;
