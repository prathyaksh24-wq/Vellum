/* SlashAwareInput — leading-slash detection
   ─────────────────────────────────────────────
   The structural distinction:
     • LEADING slash:    value[0] === "/" — input is in command mode.
                         The placeholder palette opens. ENTER fires
                         onCommand(value.slice(1)). ESC cancels and
                         clears the field.
     • MID-MESSAGE slash: a "/" appears later in the value (e.g.,
                         "/var/log", "either/or"). Input stays in
                         normal mode; ENTER fires onSubmit(value).

   In this pass the palette is a placeholder — "commands coming".
   The full catalogue is wired up post-wizard, where it joins
   LightTerm's ⌘K palette. The contract on this component is fixed:
   leading slash → onCommand, anything else → onSubmit. */

const {
  useState: useSI_useState,
  useEffect: useSI_useEffect,
  useRef:    useSI_useRef,
} = React;

function SlashAwareInput({
  value, onChange,
  onSubmit, onCommand,
  onBlur, placeholder,
  inputRef: externalRef,
  autoFocus,
}) {
  const internalRef = useSI_useRef(null);
  const inputRef = externalRef || internalRef;

  const inSlash = typeof value === "string" && value.length > 0 && value[0] === "/";
  const query = inSlash ? value.slice(1) : "";

  useSI_useEffect(() => {
    if (autoFocus && inputRef.current) inputRef.current.focus();
  }, [autoFocus, inputRef]);

  const handleKey = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (inSlash) {
        if (onCommand) onCommand(query);
      } else {
        if (onSubmit) onSubmit(value);
      }
    } else if (e.key === "Escape" && inSlash) {
      e.preventDefault();
      onChange("");
    }
  };

  return (
    <div className={"slash-input-wrap " + (inSlash ? "in-slash" : "")}>
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKey}
        onBlur={onBlur}
        placeholder={placeholder}
        className="slash-input"
        autoComplete="off"
        spellCheck="false"
      />
      {inSlash && <SlashPalettePlaceholder query={query} />}
    </div>
  );
}

/* Placeholder palette — Pass-1 scaffolding for the slash palette.
   Visually consistent with LightTerm's ⌘K palette. Shows preview of
   the commands that will land in Pass 4 of the chat work, dimmed,
   with a "commands coming" footer. */
function SlashPalettePlaceholder({ query }) {
  const PREVIEW = [
    { cmd: "/help",    sub: "keyboard shortcuts & guides" },
    { cmd: "/clear",   sub: "clear conversation" },
    { cmd: "/model",   sub: "switch model (local / cloud)" },
    { cmd: "/save",    sub: "save this session to disk" },
    { cmd: "/journal", sub: "open ~/.vellum/journal.md" },
    { cmd: "/skills",  sub: "manage enabled skills" },
    { cmd: "/setup",   sub: "re-run the setup wizard" },
  ];
  // Light filtering by query — even the placeholder respects what you typed.
  const items = query
    ? PREVIEW.filter(p => p.cmd.toLowerCase().includes("/" + query.toLowerCase()))
    : PREVIEW;

  return (
    <div className="slash-palette-placeholder">
      <div className="sp-head">
        <span className="sp-glyph">/</span>
        <span className="sp-query">
          {query || <span className="sp-q-faint">type a command…</span>}
        </span>
        <span className="sp-hint">commands coming</span>
      </div>
      <div className="sp-list">
        {items.length === 0 && (
          <div className="sp-empty">no matches yet · this catalogue is a placeholder</div>
        )}
        {items.map(p => (
          <div key={p.cmd} className="sp-row">
            <span className="sp-cmd">{p.cmd}</span>
            <span className="sp-sub">{p.sub}</span>
          </div>
        ))}
      </div>
      <div className="sp-foot">
        <span className="sp-note">scaffolding — full palette lands when chat ships</span>
        <span className="sp-keys"><kbd>ENTER</kbd> run · <kbd>ESC</kbd> cancel</span>
      </div>
    </div>
  );
}

window.SlashAwareInput = SlashAwareInput;
window.SlashPalettePlaceholder = SlashPalettePlaceholder;
