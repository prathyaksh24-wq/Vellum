// vellum-mobile.jsx
// Vellum's mobile UI — platform-agnostic. Lives inside iOS or Android frames.
// All visual language comes from BRAND.md + DESIGN.md: graphite + parchment + ember,
// Fraunces 300 (with italic v), DM Sans 500 microcopy, Roman numerals.

const VELLUM = {
  graphite: '#0c0c0e',
  charcoal: '#131316',
  slate: '#1a1a1c',
  parchment: '#ece6db',
  vellumPaper: '#f6f3ee',
  muted: 'rgba(236,230,219,0.72)',
  whisper: 'rgba(236,230,219,0.46)',
  faint: 'rgba(236,230,219,0.22)',
  ember: '#d97746',
  softEmber: '#f1b27a',
  line: 'rgba(244,237,226,0.10)',
  line2: 'rgba(244,237,226,0.16)',
  serif: '"Fraunces", Georgia, serif',
  sans: '"DM Sans", -apple-system, system-ui, sans-serif',
};

// ─────────────────────────────────────────────────────────────
// Wordmark — italic v + ellum
// ─────────────────────────────────────────────────────────────
function VWordmark({ size = 32, color = VELLUM.parchment }) {
  return (
    <span style={{
      fontFamily: VELLUM.serif, fontWeight: 300, fontSize: size,
      letterSpacing: '-0.045em', color, lineHeight: 1, userSelect: 'none',
    }}>
      <em style={{ fontStyle: 'italic', fontWeight: 300 }}>v</em>ellum
    </span>
  );
}

// ─────────────────────────────────────────────────────────────
// Paper grain + warm wash overlay (sits inside the device screen)
// ─────────────────────────────────────────────────────────────
function VAmbient() {
  const grain = "data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0.93 0 0 0 0 0.9 0 0 0 0 0.86 0 0 0 0.06 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E";
  return (
    <>
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 1,
        backgroundImage: `url("${grain}")`, opacity: 0.35, mixBlendMode: 'overlay',
      }} />
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 1,
        background: 'radial-gradient(ellipse 120% 80% at 80% 10%, rgba(217,119,70,0.06), transparent 60%)',
      }} />
    </>
  );
}

// Tiny breathing ember — pure DOM (no @keyframes needed at this scale)
function VEmber({ size = 5, ml = 0 }) {
  return (
    <span style={{
      display: 'inline-block', width: size, height: size, borderRadius: '50%',
      background: VELLUM.ember, marginLeft: ml,
      animation: 'vEmberBreathe 5.5s ease-in-out infinite',
    }} />
  );
}

// ─────────────────────────────────────────────────────────────
// SCREEN 1 — Landing (sign-in / first launch)
// ─────────────────────────────────────────────────────────────
function VLanding({ topInset = 60, bottomInset = 34 }) {
  return (
    <div style={{
      width: '100%', height: '100%', position: 'relative',
      background: VELLUM.graphite, overflow: 'hidden',
      display: 'flex', flexDirection: 'column',
      paddingTop: topInset, paddingBottom: bottomInset,
    }}>
      <VAmbient />

      {/* status row */}
      <div style={{
        position: 'relative', zIndex: 2,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        gap: 10, padding: '20px 0 0',
        fontFamily: VELLUM.sans, fontWeight: 500, fontSize: 9,
        letterSpacing: '0.28em', textTransform: 'uppercase',
        color: VELLUM.whisper,
      }}>
        <VEmber />
        private · local-first
      </div>

      {/* center wordmark stack */}
      <div style={{
        position: 'relative', zIndex: 2,
        flex: 1, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        textAlign: 'center', padding: '0 32px',
      }}>
        <div style={{ marginBottom: 28 }}>
          <VWordmark size={68} />
        </div>
        <div style={{
          fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
          fontSize: 19, lineHeight: 1.45, color: VELLUM.muted,
          letterSpacing: '-0.005em', marginBottom: 14, maxWidth: 280,
        }}>
          A personal AI,<br />trained on you.
        </div>
        <div style={{
          fontFamily: VELLUM.serif, fontWeight: 300,
          fontSize: 13, color: VELLUM.whisper,
        }}>
          Yours alone. Nothing leaves your machine.
        </div>
      </div>

      {/* enter button */}
      <div style={{
        position: 'relative', zIndex: 2,
        padding: '0 24px 32px', display: 'flex', flexDirection: 'column', gap: 14,
      }}>
        <div style={{
          height: 50, borderRadius: 4, border: `1px solid ${VELLUM.line2}`,
          background: 'rgba(19,19,22,0.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
          fontSize: 16, color: VELLUM.parchment, gap: 14,
        }}>
          enter
          <span style={{ color: VELLUM.ember, fontStyle: 'normal' }}>→</span>
        </div>
        <div style={{
          textAlign: 'center',
          fontFamily: VELLUM.sans, fontWeight: 500, fontSize: 9,
          letterSpacing: '0.20em', textTransform: 'uppercase',
          color: VELLUM.whisper,
        }}>
          by invitation · spring 2026
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// SCREEN 2 — Threads list (the rail, full-screen on mobile)
// ─────────────────────────────────────────────────────────────
function VThreads({ topInset = 60, bottomInset = 34 }) {
  const groups = [
    {
      label: 'Today',
      threads: [
        { num: 'iii.', title: 'Tarkovsky on stillness', active: true },
        { num: 'ii.',  title: 'Memo to self · sunday' },
      ],
    },
    {
      label: 'Yesterday',
      threads: [
        { num: 'i.', title: 'F1 qualifying · Suzuka' },
      ],
    },
    {
      label: 'Earlier',
      threads: [
        { num: 'iv.', title: 'Notes on solitude · Maugham' },
        { num: 'v.',  title: 'A reading order for Tarkovsky' },
        { num: 'vi.', title: "What I'm taking to New Zealand" },
      ],
    },
  ];

  return (
    <div style={{
      width: '100%', height: '100%', position: 'relative',
      background: VELLUM.graphite, overflow: 'hidden',
      display: 'flex', flexDirection: 'column',
      paddingTop: topInset, paddingBottom: bottomInset,
    }}>
      <VAmbient />

      {/* top bar */}
      <div style={{
        position: 'relative', zIndex: 2,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 20px 18px',
        borderBottom: `1px solid ${VELLUM.line}`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <VWordmark size={20} />
          <VEmber />
        </div>
        <div style={{
          fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
          fontSize: 18, color: VELLUM.muted, lineHeight: 1,
        }}>&amp;</div>
      </div>

      {/* section header — "the library" */}
      <div style={{ position: 'relative', zIndex: 2, padding: '24px 24px 16px' }}>
        <div style={{
          fontFamily: VELLUM.sans, fontWeight: 500, fontSize: 9,
          letterSpacing: '0.28em', textTransform: 'uppercase',
          color: VELLUM.whisper, marginBottom: 8,
        }}>
          The library
        </div>
        <div style={{
          fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
          fontSize: 22, color: VELLUM.parchment, letterSpacing: '-0.01em',
        }}>
          What we have spoken of.
        </div>
      </div>

      {/* threads */}
      <div style={{
        position: 'relative', zIndex: 2, flex: 1, overflow: 'auto',
        padding: '8px 0 4px',
      }}>
        {groups.map((g) => (
          <div key={g.label} style={{ marginBottom: 24 }}>
            <div style={{
              padding: '0 24px 10px',
              fontFamily: VELLUM.sans, fontWeight: 500, fontSize: 9,
              letterSpacing: '0.24em', textTransform: 'uppercase',
              color: VELLUM.whisper,
            }}>{g.label}</div>
            {g.threads.map((t, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'baseline', gap: 14,
                padding: '12px 24px',
                borderLeft: `2px solid ${t.active ? VELLUM.ember : 'transparent'}`,
                background: t.active ? 'rgba(217,119,70,0.04)' : 'transparent',
              }}>
                <span style={{
                  fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
                  fontSize: 13, minWidth: 26,
                  color: t.active ? VELLUM.ember : VELLUM.whisper,
                }}>{t.num}</span>
                <span style={{
                  fontFamily: VELLUM.serif, fontWeight: 300, fontSize: 15,
                  color: t.active ? VELLUM.parchment : VELLUM.muted,
                  letterSpacing: '-0.005em', lineHeight: 1.35,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>{t.title}</span>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* "begin again" — lives above the home indicator, no floating button */}
      <div style={{
        position: 'relative', zIndex: 2,
        borderTop: `1px solid ${VELLUM.line}`,
        padding: '16px 24px',
        display: 'flex', alignItems: 'baseline', gap: 12,
      }}>
        <span style={{ color: VELLUM.ember, fontFamily: VELLUM.serif, fontSize: 16 }}>+</span>
        <span style={{
          fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
          fontSize: 15, color: VELLUM.parchment,
        }}>begin again</span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// SCREEN 3 — Conversation (with answer + footnotes)
// ─────────────────────────────────────────────────────────────
function VConversation({ topInset = 60, bottomInset = 34, thinking = false }) {
  return (
    <div style={{
      width: '100%', height: '100%', position: 'relative',
      background: VELLUM.graphite, overflow: 'hidden',
      display: 'flex', flexDirection: 'column',
      paddingTop: topInset, paddingBottom: bottomInset,
    }}>
      <VAmbient />

      {/* top bar */}
      <div style={{
        position: 'relative', zIndex: 2,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 20px 14px',
        borderBottom: `1px solid ${VELLUM.line}`,
      }}>
        <span style={{
          fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
          fontSize: 22, color: VELLUM.muted, lineHeight: 1,
        }}>‹</span>
        <div style={{
          flex: 1, textAlign: 'center', display: 'flex',
          alignItems: 'baseline', justifyContent: 'center', gap: 8,
        }}>
          <span style={{
            fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
            fontSize: 12, color: VELLUM.ember,
          }}><em>iii.</em></span>
          <span style={{
            fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
            fontSize: 14, color: VELLUM.muted, letterSpacing: '-0.005em',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>Tarkovsky on stillness</span>
        </div>
        <span style={{
          fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
          fontSize: 18, color: VELLUM.muted, lineHeight: 1,
        }}>&amp;</span>
      </div>

      {/* messages */}
      <div style={{
        position: 'relative', zIndex: 2, flex: 1, overflow: 'auto',
        padding: '24px 22px 16px',
      }}>
        {/* user */}
        <div style={{ marginBottom: 28 }}>
          <div style={{
            fontFamily: VELLUM.sans, fontWeight: 500, fontSize: 9,
            letterSpacing: '0.24em', textTransform: 'uppercase',
            color: VELLUM.whisper, marginBottom: 10,
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <span style={{
              width: 4, height: 4, borderRadius: '50%', background: VELLUM.whisper,
            }} />
            you
          </div>
          <div style={{
            fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
            fontSize: 15, lineHeight: 1.6, color: VELLUM.muted,
            letterSpacing: '-0.005em',
          }}>
            what did i make of stillness in tarkovsky
          </div>
        </div>

        {/* agent */}
        {!thinking && (
          <div>
            <div style={{
              fontFamily: VELLUM.sans, fontWeight: 500, fontSize: 9,
              letterSpacing: '0.24em', textTransform: 'uppercase',
              color: VELLUM.whisper, marginBottom: 10,
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <span style={{
                width: 4, height: 4, borderRadius: '50%', background: VELLUM.ember,
              }} />
              from your library
            </div>
            <div style={{
              fontFamily: VELLUM.serif, fontWeight: 300,
              fontSize: 15, lineHeight: 1.7, color: VELLUM.parchment,
              letterSpacing: '-0.005em',
            }}>
              Tarkovsky's stillness is not the absence of action.
              It is the presence of attention. The long takes in{' '}
              <em style={{ color: VELLUM.vellumPaper }}>Stalker</em>
              <sup style={{
                color: VELLUM.ember, fontFamily: VELLUM.serif, fontStyle: 'italic',
                fontSize: 10, verticalAlign: 'super', lineHeight: 0,
              }}>i</sup> and{' '}
              <em style={{ color: VELLUM.vellumPaper }}>Mirror</em>
              <sup style={{
                color: VELLUM.ember, fontFamily: VELLUM.serif, fontStyle: 'italic',
                fontSize: 10, verticalAlign: 'super', lineHeight: 0,
              }}>ii</sup>{' '}
              hold their gaze the way a person holds a thought he refuses to interrupt.
              <sup style={{
                color: VELLUM.ember, fontFamily: VELLUM.serif, fontStyle: 'italic',
                fontSize: 10, verticalAlign: 'super', lineHeight: 0,
              }}>iii</sup>
            </div>

            {/* footnotes — marginalia register */}
            <div style={{
              marginTop: 22, paddingTop: 14, borderTop: `1px solid ${VELLUM.line}`,
              display: 'flex', flexDirection: 'column', gap: 8,
            }}>
              {[
                { mark: 'i.',   src: 'Books / Sculpting in Time, p. 114' },
                { mark: 'ii.',  src: 'Books / Sculpting in Time, p. 79' },
                { mark: 'iii.', src: 'youtube / Tarkovsky on the long take · 2024' },
              ].map((f) => (
                <div key={f.mark} style={{
                  display: 'flex', gap: 10, paddingLeft: 14,
                  borderLeft: `1px solid ${VELLUM.line}`,
                  fontFamily: VELLUM.sans, fontSize: 10, lineHeight: 1.55,
                  color: VELLUM.whisper,
                }}>
                  <span style={{
                    fontFamily: VELLUM.serif, fontStyle: 'italic',
                    color: VELLUM.ember, width: 16, flexShrink: 0,
                  }}>{f.mark}</span>
                  <span>
                    From your notes —{' '}
                    <span style={{
                      color: VELLUM.muted, fontStyle: 'italic',
                      fontFamily: VELLUM.serif, fontSize: 11.5,
                    }}>{f.src}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* thinking — single quiet line + drawing line */}
        {thinking && (
          <div>
            <div style={{
              fontFamily: VELLUM.sans, fontWeight: 500, fontSize: 9,
              letterSpacing: '0.28em', textTransform: 'uppercase',
              color: VELLUM.whisper, marginBottom: 18,
              display: 'flex', alignItems: 'center', gap: 12,
            }}>
              <span style={{ width: 22, height: 1, background: VELLUM.ember, opacity: 0.6 }} />
              Reading.
            </div>
            <div style={{
              height: 1, background: VELLUM.ember, opacity: 0.5,
              animation: 'vDrawAcross 3.6s cubic-bezier(0.22, 1, 0.36, 1) infinite',
              transformOrigin: 'left center',
            }} />
          </div>
        )}
      </div>

      {/* input bar */}
      <div style={{
        position: 'relative', zIndex: 2,
        padding: '14px 16px 16px',
        borderTop: `1px solid ${VELLUM.line}`,
        background: 'rgba(12,12,14,0.7)',
      }}>
        <div style={{
          border: `1px solid ${VELLUM.line2}`, borderRadius: 6,
          padding: '12px 16px', background: 'rgba(19,19,22,0.7)',
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <span style={{
            flex: 1, fontFamily: VELLUM.serif, fontStyle: 'italic',
            fontWeight: 300, fontSize: 15, color: VELLUM.whisper,
          }}>Ask.</span>
          <span style={{
            fontFamily: VELLUM.sans, fontWeight: 500, fontSize: 9,
            letterSpacing: '0.20em', textTransform: 'uppercase',
            color: VELLUM.whisper,
          }}>Gemma 4 · 31b</span>
          <VEmber />
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// SCREEN 4 — Faculties / Mind panel (full-screen sheet)
// ─────────────────────────────────────────────────────────────
function VFaculties({ topInset = 60, bottomInset = 34 }) {
  return (
    <div style={{
      width: '100%', height: '100%', position: 'relative',
      background: VELLUM.charcoal, overflow: 'hidden',
      display: 'flex', flexDirection: 'column',
      paddingTop: topInset, paddingBottom: bottomInset,
    }}>
      <VAmbient />

      {/* top */}
      <div style={{
        position: 'relative', zIndex: 2,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 20px 18px',
        borderBottom: `1px solid ${VELLUM.line}`,
      }}>
        <span style={{
          fontFamily: VELLUM.sans, fontWeight: 500, fontSize: 9,
          letterSpacing: '0.28em', textTransform: 'uppercase',
          color: VELLUM.whisper,
        }}>Mind &amp; Faculties</span>
        <span style={{
          fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
          fontSize: 13, color: VELLUM.muted,
        }}>close</span>
      </div>

      <div style={{
        position: 'relative', zIndex: 2, flex: 1, overflow: 'auto',
        padding: '28px 22px',
      }}>
        {/* MIND */}
        <div style={{ marginBottom: 36 }}>
          <div style={{
            fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
            fontSize: 22, color: VELLUM.parchment, marginBottom: 6,
          }}>Mind</div>
          <div style={{
            fontFamily: VELLUM.serif, fontWeight: 300, fontSize: 12.5,
            color: VELLUM.whisper, lineHeight: 1.55, marginBottom: 16,
          }}>
            The model that thinks for you.<br />
            Switch quietly. The conversation continues.
          </div>

          {[
            { num: 'i.',   name: 'Gemma 4', size: '31b', tag: 'primary',  active: true },
            { num: 'ii.',  name: 'Qwen 3.5', size: '35b', tag: 'fallback' },
            { num: 'iii.', name: 'Gemma 4', size: '12b', tag: 'quick' },
          ].map((m) => (
            <div key={m.num} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '12px 0', borderTop: `1px solid ${VELLUM.line}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
                <span style={{
                  fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
                  fontSize: 12, color: m.active ? VELLUM.ember : VELLUM.whisper, minWidth: 22,
                }}>{m.num}</span>
                <span style={{
                  fontFamily: VELLUM.serif, fontWeight: 300, fontSize: 14.5,
                  color: VELLUM.parchment,
                }}>
                  {m.name}{' '}
                  <em style={{
                    color: VELLUM.muted, fontStyle: 'italic', fontSize: 12.5,
                  }}>· {m.size}</em>
                </span>
              </div>
              <span style={{
                fontFamily: VELLUM.sans, fontWeight: 500, fontSize: 9,
                letterSpacing: '0.18em', textTransform: 'uppercase',
                color: VELLUM.whisper,
              }}>{m.tag}</span>
            </div>
          ))}
        </div>

        {/* FACULTIES */}
        <div style={{ marginBottom: 36 }}>
          <div style={{
            fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
            fontSize: 22, color: VELLUM.parchment, marginBottom: 6,
          }}>Faculties</div>
          <div style={{
            fontFamily: VELLUM.serif, fontWeight: 300, fontSize: 12.5,
            color: VELLUM.whisper, lineHeight: 1.55, marginBottom: 16,
          }}>
            Tools the agent may call upon. Toggle by tapping the line.
          </div>

          {[
            { num: 'i.',   name: 'Filesystem', meta: 'your vault · 184 notes',     status: 'attending', state: 'on' },
            { num: 'ii.',  name: 'Apify',      meta: 'private · 4 calls today',    status: 'attending', state: 'on', italic: 'amazon' },
            { num: 'iii.', name: 'Web',        meta: 'duckduckgo · privacy-gated', status: 'withheld',  state: 'off' },
            { num: 'iv.',  name: 'Memory',     meta: 'long-term · sqlite',         status: 'resting',   state: 'off' },
          ].map((f) => (
            <div key={f.num} style={{
              display: 'flex', alignItems: 'baseline', gap: 14,
              padding: '14px 0', borderTop: `1px solid ${VELLUM.line}`,
              opacity: f.state === 'off' ? 0.55 : 1,
            }}>
              <span style={{
                fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
                fontSize: 12, color: VELLUM.whisper, minWidth: 22,
              }}>{f.num}</span>
              <div style={{ flex: 1 }}>
                <div style={{
                  fontFamily: VELLUM.serif, fontWeight: 300, fontSize: 15.5,
                  color: VELLUM.parchment, marginBottom: 3,
                  letterSpacing: '-0.005em',
                }}>
                  {f.name}
                  {f.italic && (
                    <em style={{
                      color: VELLUM.muted, fontStyle: 'italic',
                      fontSize: 13.5, marginLeft: 4,
                    }}>· {f.italic}</em>
                  )}
                </div>
                <div style={{
                  fontFamily: VELLUM.sans, fontWeight: 500, fontSize: 9,
                  letterSpacing: '0.18em', textTransform: 'uppercase',
                  color: VELLUM.whisper,
                }}>{f.meta}</div>
              </div>
              <span style={{
                fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
                fontSize: 12.5,
                color: f.state === 'on' ? VELLUM.ember : VELLUM.whisper,
              }}>{f.status}</span>
            </div>
          ))}
        </div>

        {/* DISCRETION */}
        <div>
          <div style={{
            fontFamily: VELLUM.serif, fontStyle: 'italic', fontWeight: 300,
            fontSize: 22, color: VELLUM.parchment, marginBottom: 6,
          }}>Discretion</div>
          <div style={{
            fontFamily: VELLUM.serif, fontWeight: 300, fontSize: 12.5,
            color: VELLUM.whisper, lineHeight: 1.65,
          }}>
            Nothing leaves your machine without your knowledge.
            Outgoing requests are scrubbed of names and identifiers.
            Private folders <em style={{ fontStyle: 'italic', color: VELLUM.muted }}>(X, youtube, books, feedback)</em>{' '}
            are read but never quoted in the open.
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, {
  VELLUM, VWordmark, VAmbient, VEmber,
  VLanding, VThreads, VConversation, VFaculties,
});
