/**
 * Generative fluid agent visual identity.
 *
 * Persisted as `agents.color` / API `agent_color`: 1–3 hex strings.
 * Shape params are derived deterministically from `seed` (usually agent_id)
 * so the icon can be rebuilt anywhere. Mid color is the agent accent used
 * for @mentions and border beams.
 */

import {
  AGENT_COLOR_SWATCH_HEX,
  normalizeAgentColor,
} from "./agent-color";

export const FLUID_IDENTITY_VERSION = "fluid-v1";

export const DEFAULT_AGENT_PALETTE: [string, string, string] = [
  "#8eb8ff",
  "#5b8def",
  "#b8d4ff",
];

export type FluidBlobSpec = {
  /** Position as % of container (can be outside 0–100 for overflow). */
  x: number;
  y: number;
  /** Size as % of container. */
  w: number;
  h: number;
  rotate: number;
  /** CSS border-radius shorthand for organic silhouette. */
  radius: string;
  /** Index into identity.colors — 1 is the dominant main accent. */
  colorIndex: 0 | 1 | 2;
  opacity: number;
  /** Blur in px at a 160px reference size — scaled by render size. */
  blur: number;
  /** Animation phase offset 0–1 */
  phase: number;
};

export type AgentVisualIdentity = {
  version: typeof FLUID_IDENTITY_VERSION;
  seed: string;
  /** Three hex stops: soft deep, main accent, bright minor. Mid drives mentions/beams. */
  colors: [string, string, string];
  blobs: FluidBlobSpec[];
};

/** Mulberry32 — small deterministic PRNG. */
function mulberry32(seed: number): () => number {
  let t = seed >>> 0;
  return () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function hashSeed(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i += 1) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function randRange(rng: () => number, min: number, max: number): number {
  return min + rng() * (max - min);
}

function randInt(rng: () => number, min: number, max: number): number {
  return Math.floor(randRange(rng, min, max + 1));
}

/**
 * ~150 soft/lively hue variants — golden-angle spaced so nearby seeds don't
 * cluster, with sat/light bands for shade diversity across a large fleet.
 */
const MAIN_HUES: { h: number; s: number; lMain: number }[] = (() => {
  const GOLDEN = 137.50776405;
  const out: { h: number; s: number; lMain: number }[] = [];
  for (let i = 0; i < 150; i += 1) {
    const h = (i * GOLDEN) % 360;
    const satBand = i % 5;
    const lightBand = Math.floor(i / 5) % 6;
    out.push({
      h,
      s: 52 + satBand * 7 + (i % 3) * 2,
      lMain: 54 + lightBand * 3 + (i % 2),
    });
  }
  return out;
})();

const MINOR_HUE_OFFSETS = [
  28, -32, 44, -48, 56, -62, 72, -78, 96, -108, 128, -140, 156, -168, 18, -22,
];

function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}

function hslToHex(h: number, s: number, l: number): string {
  const sat = clamp(s, 0, 100) / 100;
  const light = clamp(l, 0, 100) / 100;
  const hue = ((h % 360) + 360) % 360;
  const c = (1 - Math.abs(2 * light - 1)) * sat;
  const x = c * (1 - Math.abs(((hue / 60) % 2) - 1));
  const m = light - c / 2;
  const sector = Math.floor(hue / 60) % 6;
  const [r, g, b] = [
    [c, x, 0],
    [x, c, 0],
    [0, c, x],
    [0, x, c],
    [x, 0, c],
    [c, 0, x],
  ][sector]!;
  const toHex = (v: number) =>
    Math.round((v + m) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

function jitterHsl(
  rng: () => number,
  h: number,
  s: number,
  l: number,
): string {
  return hslToHex(
    h + randRange(rng, -5, 5),
    s + randRange(rng, -6, 6),
    l + randRange(rng, -4, 4),
  );
}

/** Soft liquid palette: readable main + soft deep + bright accent pop. */
function pickPalette(rng: () => number): [string, string, string] {
  const base = MAIN_HUES[randInt(rng, 0, MAIN_HUES.length - 1)]!;
  // Extra continuous hue jitter so even the same table slot rarely matches.
  const hue = base.h + randRange(rng, -4.5, 4.5);
  const minorOff =
    MINOR_HUE_OFFSETS[randInt(rng, 0, MINOR_HUE_OFFSETS.length - 1)]! +
    randRange(rng, -8, 8);
  const deep = jitterHsl(
    rng,
    hue,
    clamp(base.s * 0.68 + randRange(rng, -4, 4), 34, 74),
    clamp(base.lMain - 14 + randRange(rng, -3, 3), 42, 58),
  );
  const main = jitterHsl(
    rng,
    hue,
    clamp(base.s + randRange(rng, -5, 5), 48, 90),
    clamp(base.lMain + randRange(rng, -3, 3), 52, 74),
  );
  const light = jitterHsl(
    rng,
    hue + minorOff,
    clamp(base.s * 0.62 + randRange(rng, -4, 6), 40, 84),
    clamp(base.lMain + randRange(rng, 10, 24), 70, 88),
  );
  return [deep, main, light];
}

/** Stable identity for a proposal / draft before the agent has a real id. */
export function proposalAgentVisualIdentity(
  proposalId: string,
): AgentVisualIdentity {
  return createAgentVisualIdentity(`proposal:${proposalId}`);
}

/** Serialized color[] for proposals — same seed every time for a given id. */
export function proposalAgentVisualColor(proposalId: string): string[] {
  return serializeAgentVisualIdentity(proposalAgentVisualIdentity(proposalId));
}

/** Soft rainbow hexes for multi-agent overflow washes. */
export function rainbowAgentWashStops(count = 6): string[] {
  const stops: string[] = [];
  for (let i = 0; i < count; i += 1) {
    const h = (i * (360 / count) + 12) % 360;
    stops.push(hslToHex(h, 72, 64));
  }
  return stops;
}

const V2_SWATCH_COLORS: Record<string, [string, string, string]> =
  AGENT_COLOR_SWATCH_HEX;

function organicRadius(rng: () => number): string {
  const a = randInt(rng, 28, 92);
  const b = randInt(rng, 18, 88);
  const c = randInt(rng, 28, 92);
  const d = randInt(rng, 14, 88);
  const e = randInt(rng, 30, 94);
  const f = randInt(rng, 20, 88);
  const g = randInt(rng, 30, 94);
  const h = randInt(rng, 20, 88);
  return `${a}% ${b}% ${c}% ${d}% / ${e}% ${f}% ${g}% ${h}%`;
}

/**
 * Three offset lobes (not stacked on one center) so the silhouette reads as
 * liquid. Layout families keep each agent unique.
 */
function buildBlobs(rng: () => number): FluidBlobSpec[] {
  const layouts: [number, number][][] = [
    [
      [42, 40],
      [22, 28],
      [58, 56],
    ],
    [
      [48, 44],
      [62, 24],
      [28, 58],
    ],
    [
      [40, 48],
      [58, 58],
      [24, 32],
    ],
    [
      [46, 38],
      [30, 58],
      [64, 48],
    ],
  ];
  const layout = layouts[randInt(rng, 0, layouts.length - 1)]!;
  const sizes: [number, number][] = [
    [randRange(rng, 52, 68), randRange(rng, 48, 64)],
    [randRange(rng, 40, 56), randRange(rng, 38, 54)],
    [randRange(rng, 36, 52), randRange(rng, 34, 50)],
  ];
  const colorOrder: Array<0 | 1 | 2> = [1, 2, 0];
  return layout.map(([cx, cy], i) => {
    const [w, h] = sizes[i]!;
    return {
      x: cx + randRange(rng, -6, 6) - w / 2,
      y: cy + randRange(rng, -6, 6) - h / 2,
      w,
      h,
      rotate: randRange(rng, -36, 36),
      radius: organicRadius(rng),
      colorIndex: colorOrder[i]!,
      opacity: randRange(rng, i === 0 ? 0.78 : 0.48, i === 0 ? 0.92 : 0.78),
      blur: randRange(rng, i === 0 ? 1.5 : 3, i === 0 ? 5 : 10),
      phase: rng(),
    };
  });
}

/** Palette + blobs from one seed stream (palette draws first so overrides stay shape-stable). */
function deriveFromSeed(seed: string): {
  colors: [string, string, string];
  blobs: FluidBlobSpec[];
} {
  const rng = mulberry32(hashSeed(seed));
  return { colors: pickPalette(rng), blobs: buildBlobs(rng) };
}

function identityFromSeed(
  seed: string,
  colors: [string, string, string],
): AgentVisualIdentity {
  return {
    version: FLUID_IDENTITY_VERSION,
    seed,
    colors,
    blobs: deriveFromSeed(seed).blobs,
  };
}

export function createAgentVisualIdentity(
  seed: string = cryptoRandomSeed(),
): AgentVisualIdentity {
  const { colors, blobs } = deriveFromSeed(seed);
  return {
    version: FLUID_IDENTITY_VERSION,
    seed,
    colors,
    blobs,
  };
}

function cryptoRandomSeed(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID().replace(/-/g, "").slice(0, 16);
  }
  return `s${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

export function isFluidIdentityColor(color?: string[] | null): boolean {
  return Array.isArray(color) && color[0] === FLUID_IDENTITY_VERSION;
}

function isFluidStoredColor(color?: string[] | null): color is string[] {
  return isFluidIdentityColor(color) && !!color && color.length >= 5;
}

/** Lift dark stored hexes so existing agents still feel lively on white UI. */
function hexToRgb(hex: string): { r: number; g: number; b: number } | null {
  const raw = hex.replace("#", "").trim();
  const full =
    raw.length === 3
      ? raw
          .split("")
          .map((c) => c + c)
          .join("")
      : raw;
  if (full.length !== 6 || /[^0-9a-fA-F]/.test(full)) return null;
  return {
    r: Number.parseInt(full.slice(0, 2), 16),
    g: Number.parseInt(full.slice(2, 4), 16),
    b: Number.parseInt(full.slice(4, 6), 16),
  };
}

function rgbToHsl(
  r: number,
  g: number,
  b: number,
): { h: number; s: number; l: number } {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  if (max === min) return { h: 0, s: 0, l: l * 100 };
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h = 0;
  if (max === rn) h = ((gn - bn) / d + (gn < bn ? 6 : 0)) / 6;
  else if (max === gn) h = ((bn - rn) / d + 2) / 6;
  else h = ((rn - gn) / d + 4) / 6;
  return { h: h * 360, s: s * 100, l: l * 100 };
}

function liftHex(hex: string, minL: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const { h, s, l } = rgbToHsl(rgb.r, rgb.g, rgb.b);
  if (l >= minL) return hex;
  const lifted = minL + (l / minL) * 4;
  return hslToHex(h, Math.max(s, 42), Math.min(88, lifted));
}

function brightenPalette(
  colors: [string, string, string],
): [string, string, string] {
  return [
    liftHex(colors[0], 48),
    liftHex(colors[1], 58),
    liftHex(colors[2], 72),
  ];
}

/** Resolve a stored color array to a display palette (brightened when needed). */
function paletteFromColorArray(
  color?: string[] | null,
  fallback: [string, string, string] = DEFAULT_AGENT_PALETTE,
): [string, string, string] {
  const normalized = normalizeAgentColor(color);
  if (normalized.length >= 3) {
    return brightenPalette([normalized[0]!, normalized[1]!, normalized[2]!]);
  }
  if (normalized.length === 2) {
    return brightenPalette([normalized[0]!, normalized[1]!, normalized[0]!]);
  }
  if (normalized.length === 1) {
    return brightenPalette([normalized[0]!, normalized[0]!, normalized[0]!]);
  }
  return fallback;
}

export function serializeAgentVisualIdentity(
  identity: AgentVisualIdentity,
): string[] {
  // Persist hex palette only — no fluid-v1 wrapper, no swatch ids.
  return [identity.colors[0], identity.colors[1], identity.colors[2]];
}

export function extractAgentPaletteColors(
  color?: string[] | null,
  fallback: [string, string, string] = DEFAULT_AGENT_PALETTE,
): [string, string, string] {
  return paletteFromColorArray(color, fallback);
}

export function resolveAgentVisualIdentity(
  color?: string[] | null,
  agentId?: string | null,
): AgentVisualIdentity {
  const normalized = normalizeAgentColor(color);

  // Preserve fluid-v1 seed when still present in legacy payloads
  if (isFluidStoredColor(color)) {
    return identityFromSeed(
      color[1] || agentId || "default",
      paletteFromColorArray(color),
    );
  }

  if (normalized.length >= 1) {
    return identityFromSeed(
      agentId || normalized.join(""),
      paletteFromColorArray(normalized),
    );
  }

  // Legacy swatch id that somehow didn't normalize (shouldn't happen)
  const swatchId = color?.[0];
  if (swatchId && V2_SWATCH_COLORS[swatchId]) {
    return identityFromSeed(agentId || swatchId, V2_SWATCH_COLORS[swatchId]);
  }

  return createAgentVisualIdentity(agentId || color?.[0] || "default");
}

export function agentVisualAccent(identity: AgentVisualIdentity): string {
  return identity.colors[1];
}

export function agentVisualMentionClass(identity: AgentVisualIdentity): string {
  return `text-[${agentVisualAccent(identity)}]`;
}
