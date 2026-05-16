/* Screen 8 — Skills (categorized)
   Browseable list, OC `[ ]`/`[x]` checkbox pattern. 4 default-on.
   ↑↓ across the flat list, SPACE toggle, ENTER continue.
   Skills are grouped by category (Writing / Coding / Research / Daily). */

const { useState: useSkills_useState, useEffect: useSkills_useEffect, useMemo: useSkills_useMemo } = React;

const SKILLS_DEFAULT = [
  { id: "writing.brainstorm", category: "Writing",  label: "Brainstorm & draft",  sub: "— help me think and start writing", enabled: true  },
  { id: "writing.edit",       category: "Writing",  label: "Edit & copy",          sub: "— line edits, tightening, voice", enabled: false },
  { id: "writing.letters",    category: "Writing",  label: "Letters & emails",     sub: "— short replies, longer notes",   enabled: false },

  { id: "code.review",        category: "Coding",   label: "Code review",          sub: "— diff-aware review with suggestions", enabled: true  },
  { id: "code.debug",         category: "Coding",   label: "Debug & trace",        sub: "— follow stacks, propose fixes",       enabled: true  },
  { id: "code.refactor",      category: "Coding",   label: "Refactor & generate",  sub: "— rewrites, scaffolds, test stubs",    enabled: false },

  { id: "research.summarize", category: "Research", label: "Summarize",            sub: "— condense pages, papers, threads",  enabled: true  },
  { id: "research.compare",   category: "Research", label: "Compare sources",      sub: "— show me where they disagree",       enabled: false },
  { id: "research.factcheck", category: "Research", label: "Fact-check",           sub: "— flag claims, cite or hedge",        enabled: false },

  { id: "daily.calendar",     category: "Daily",    label: "Calendar nudges",      sub: "— gentle reminders, prep notes",       enabled: false },
  { id: "daily.reading",      category: "Daily",    label: "Reading queue",        sub: "— things you saved, things I noticed", enabled: false },
  { id: "daily.summary",      category: "Daily",    label: "Daily summary",        sub: "— one paragraph at the end of the day", enabled: false },
];

function SkillsScreen({ s, setRoot, onAdvance }) {
  // Seed skills on first mount if empty
  useSkills_useEffect(() => {
    if (!s.skills || s.skills.length === 0) {
      setRoot("skills", SKILLS_DEFAULT.map(sk => ({ ...sk })));
    }
  }, []); // eslint-disable-line

  const skills = (s.skills && s.skills.length) ? s.skills : SKILLS_DEFAULT;

  // group by category, but maintain a flat ordering for navigation
  const grouped = useSkills_useMemo(() => {
    const order = ["Writing", "Coding", "Research", "Daily"];
    return order.map(cat => ({ cat, items: skills.filter(sk => sk.category === cat) }));
  }, [skills]);

  const flat = useSkills_useMemo(() => grouped.flatMap(g => g.items), [grouped]);
  const [idx, setIdx] = useSkills_useState(0);

  const enabledCount = flat.filter(sk => sk.enabled).length;

  useSkills_useEffect(() => {
    const h = (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); setIdx(i => Math.min(flat.length - 1, i + 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setIdx(i => Math.max(0, i - 1)); }
      else if (e.key === " ") {
        e.preventDefault();
        const target = flat[idx];
        const updated = skills.map(sk => sk.id === target.id ? { ...sk, enabled: !sk.enabled } : sk);
        setRoot("skills", updated);
      }
      else if (e.key === "Enter") {
        e.preventDefault();
        onAdvance();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [idx, flat, skills, setRoot, onAdvance]);

  return (
    <div className="oc-section">
      <div className="oc-line">
        <span className="oc-marker">◆</span>
        <span className="oc-title">Skills</span>
      </div>
      <div className="oc-desc">
        What I'm specialized for. Pick what's useful now — add or remove anytime with <code style={{color:"var(--text)"}}>vellum skills</code>.
        Each skill is a markdown file at <span style={{color:"var(--text-dim)"}}>~/.vellum/skills/</span> — readable, editable, yours.
      </div>

      <div className="oc-question">Toggle skills to enable:</div>
      <div className="oc-hint">
        <span className="seg"><kbd>↑↓</kbd> navigate</span>
        <span className="seg"><kbd>SPACE</kbd> toggle</span>
        <span className="seg"><kbd>ENTER</kbd> continue</span>
        <span className="seg"><kbd>ESC</kbd> back</span>
      </div>

      <div className="oc-list">
        {(() => {
          let flatI = -1;
          const nodes = [];
          for (const g of grouped) {
            const groupCount = g.items.filter(sk => sk.enabled).length;
            nodes.push(
              <div key={"cat-" + g.cat} className="oc-cat">
                <span></span>
                <span></span>
                <span>
                  <span className="name">{g.cat}</span>
                  <span className="count">{groupCount}/{g.items.length}</span>
                </span>
              </div>
            );
            for (const sk of g.items) {
              flatI += 1;
              const i = flatI;
              const on = sk.enabled;
              nodes.push(
                <div
                  key={sk.id}
                  className={"oc-row skill check " + (i === idx ? "sel" : "")}
                  onMouseEnter={() => setIdx(i)}
                  onClick={() => {
                    setIdx(i);
                    const updated = skills.map(x => x.id === sk.id ? { ...x, enabled: !x.enabled } : x);
                    setRoot("skills", updated);
                  }}
                >
                  <span className="arr">→</span>
                  <span className="glyph">[{on ? "x" : " "}]</span>
                  <span className="label">{sk.label}</span>
                  <span className="sub">{sk.sub}</span>
                </div>
              );
            }
          }
          return nodes;
        })()}
      </div>

      <div style={{marginTop: 22, fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--text-faint)"}}>
        <span style={{color: "var(--accent)"}}>{enabledCount}</span> of {flat.length} skills enabled.
      </div>
    </div>
  );
}

window.SkillsScreen = SkillsScreen;
