/**
 * Canonical agent color contract: 1–3 hex strings.
 *
 * Stored historically as agents.color (text[]) under several shapes:
 *   ["blue"]                              — V2 swatch id
 *   ["#a","#b","#c"]                      — hex palette
 *   ["fluid-v1", seed, "#a","#b","#c"]    — generative identity
 *
 * Everything reads/writes through normalizeAgentColor / toAgentColorPayload
 * so consumers never see the old formats.
 */

const HEX_RE = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

/** Swatch id → full 3-stop palette (must match lib/colors.ts V2_COLOR_SWATCHES). */
export const AGENT_COLOR_SWATCH_HEX: Record<string, [string, string, string]> = {
  blue: ["#120a78", "#2d6de0", "#d7ebff"],
  green: ["#034f00", "#8bd400", "#f4ffd9"],
  orange: ["#740012", "#ff3a00", "#ffc400"],
  purple: ["#1e005d", "#9a18dd", "#f0e4ff"],
  red: ["#630000", "#d70000", "#ffd9d4"],
  white: ["#282c37", "#c8ccd7", "#f5f7fb"],
};

export function isHexColor(value: string): boolean {
  return HEX_RE.test(value.trim());
}

function expandShortHex(hex: string): string {
  const raw = hex.trim();
  if (/^#[0-9a-fA-F]{3}$/.test(raw)) {
    const [, a, b, c] = raw;
    return `#${a}${a}${b}${b}${c}${c}`.toLowerCase();
  }
  return raw.toLowerCase();
}

/**
 * Collapse any legacy agent color payload into 1–3 hex colors.
 * Empty / unparseable input → [].
 */
export function normalizeAgentColor(
  raw?: string[] | null,
): string[] {
  if (!Array.isArray(raw) || raw.length === 0) return [];

  // fluid-v1 → the three hexes at the end
  if (raw[0] === "fluid-v1" && raw.length >= 5) {
    return [raw[2], raw[3], raw[4]]
      .filter((c): c is string => typeof c === "string" && isHexColor(c))
      .map(expandShortHex)
      .slice(0, 3);
  }

  // V2 swatch id alone
  if (raw.length === 1 && typeof raw[0] === "string" && !raw[0].startsWith("#")) {
    const swatch = AGENT_COLOR_SWATCH_HEX[raw[0]];
    return swatch ? [...swatch] : [];
  }

  // Hex palette (optionally prefixed with junk — take hex entries only)
  const hexes = raw
    .filter((c): c is string => typeof c === "string" && isHexColor(c))
    .map(expandShortHex)
    .slice(0, 3);

  return hexes;
}

/** Always a 3-tuple for shaders that need three stops. Pads/truncates. */
export function agentColorTriple(
  raw?: string[] | null,
  fallback: [string, string, string] = ["#1e3a5f", "#2d6de0", "#d7ebff"],
): [string, string, string] {
  const colors = normalizeAgentColor(raw);
  if (colors.length >= 3) return [colors[0]!, colors[1]!, colors[2]!];
  if (colors.length === 2) return [colors[0]!, colors[1]!, colors[0]!];
  if (colors.length === 1) return [colors[0]!, colors[0]!, colors[0]!];
  return fallback;
}

/** Payload to persist / send to the API — hexes only, never swatch ids or fluid-v1. */
export function toAgentColorPayload(
  raw?: string[] | null,
): string[] {
  return normalizeAgentColor(raw);
}

/** Mid stop — accent used for tints, beams, mentions. */
export function agentColorAccent(raw?: string[] | null): string | null {
  const colors = normalizeAgentColor(raw);
  if (colors.length === 0) return null;
  return colors[Math.min(1, colors.length - 1)] ?? colors[0] ?? null;
}
