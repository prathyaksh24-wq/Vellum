/* Vellum pixel avatar — 8×8 grid, scaled.
   The agent's identity. Pinned top-left throughout the wizard
   and into the handoff (via portal so it survives tab-kind swap).

   States:
   - "dither"    : one-shot reveal (used by intro)
   - "breathing" : idle subtle brightness pulse (default)
   - "still"     : fully static (used briefly during state writes)
*/

const VELLUM_GLYPH = [
  ". . M M M M . .",
  ". M M M M M M .",
  "M M C M M C M M",
  "M M M M M M M M",
  "M M . . . . M M",
  ". M M A A M M .",
  ". . M M M M . .",
  ". . . . . . . .",
];

function VellumAvatar({ size = 32, state = "breathing", className = "" }) {
  const pixels = [];
  VELLUM_GLYPH.forEach((row, y) => {
    row.replace(/ /g, "").split("").forEach((c, x) => {
      if (c === "M") pixels.push({ x, y, fill: "var(--magenta)" });
      else if (c === "C") pixels.push({ x, y, fill: "var(--cyan)" });
      else if (c === "A") pixels.push({ x, y, fill: "var(--accent)" });
    });
  });
  return (
    <svg
      className={`vellum-avatar ${state} ${className}`}
      width={size}
      height={size}
      viewBox="0 0 8 8"
      style={{ imageRendering: "pixelated" }}
      aria-label="Vellum"
    >
      {pixels.map((p, i) => (
        <rect key={i} x={p.x} y={p.y} width="1" height="1" fill={p.fill} />
      ))}
    </svg>
  );
}

window.VellumAvatar = VellumAvatar;
