import type { BriefCoverMotif } from "./brief-cover-meta";
import {
  drawAgentOrb,
  drawAgentOrbRow,
  type CoverAgentPortrait,
} from "./brief-cover-agents";
import type { ShelfBriefBook } from "./types";

const serif = 'Georgia, "Iowan Old Style", "Times New Roman", serif';
const sans = 'system-ui, -apple-system, "SF Pro Text", sans-serif';

export type CoverEdition =
  | "folio"
  | "broadside"
  | "atlas"
  | "field-notes"
  | "quartz"
  | "nocturne"
  | "linen"
  | "signal";

const TOOLKIT_ACCENTS: Record<string, string> = {
  github: "#6e5494",
  slack: "#e01e5a",
  gmail: "#ea4335",
  googlecalendar: "#4285f4",
  notion: "#2383e2",
};

/** Lively mid-tone washes — full color fields, not near-black with a highlight. */
const EDITION_PALETTES: Array<{
  cover: string;
  accent: string;
  ink: string;
  titleColor: string;
}> = [
  { cover: "#e87a5d", accent: "#fff1e6", ink: "#2a1210", titleColor: "#fff8f2" },
  { cover: "#5ba4d9", accent: "#ffe08a", ink: "#102234", titleColor: "#fff9ef" },
  { cover: "#e8b84a", accent: "#2f5d50", ink: "#2a1c08", titleColor: "#1f1608" },
  { cover: "#5cba9a", accent: "#fff0c8", ink: "#102820", titleColor: "#fff8e8" },
  { cover: "#9b7ed9", accent: "#ffe6a8", ink: "#1c1430", titleColor: "#fff6ea" },
  { cover: "#d4784a", accent: "#ffe9c8", ink: "#2a1408", titleColor: "#fff5ea" },
  { cover: "#e07a9a", accent: "#fff0d8", ink: "#2a1018", titleColor: "#fff7f0" },
  { cover: "#3a9e9a", accent: "#ffe6a0", ink: "#0e2424", titleColor: "#fff8e8" },
  { cover: "#f0d078", accent: "#4a3a8a", ink: "#2a220c", titleColor: "#1e1808" },
  { cover: "#7b8fd4", accent: "#ffd6a8", ink: "#12182e", titleColor: "#fff6ea" },
  { cover: "#f0a878", accent: "#3d5c8a", ink: "#2a160c", titleColor: "#1f120a" },
  { cover: "#6db8a8", accent: "#fff0c0", ink: "#102420", titleColor: "#fff9ec" },
  { cover: "#e9a03a", accent: "#2a4a6a", ink: "#2a1a08", titleColor: "#1c1206" },
  { cover: "#c4a0e0", accent: "#fff0b8", ink: "#221830", titleColor: "#1a1224" },
  { cover: "#8fb87a", accent: "#fff2d0", ink: "#182414", titleColor: "#fff9ec" },
  { cover: "#d45a7a", accent: "#ffe8c0", ink: "#2a1018", titleColor: "#fff6ee" },
];

const EDITIONS: CoverEdition[] = [
  "folio",
  "broadside",
  "atlas",
  "field-notes",
  "quartz",
  "nocturne",
  "linen",
  "signal",
];

function seeded(seed: string) {
  let state = 2166136261;
  for (const char of seed) {
    state ^= char.charCodeAt(0);
    state = Math.imul(state, 16777619);
  }
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function parseColor(color: string) {
  if (color.startsWith("#")) return hexToRgb(color);
  const match = color.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
  if (!match) return null;
  return {
    r: Number(match[1]),
    g: Number(match[2]),
    b: Number(match[3]),
  };
}

function shade(color: string, amount: number) {
  const rgb = parseColor(color);
  if (!rgb) return color;
  const channels = [rgb.r, rgb.g, rgb.b].map((value) =>
    Math.min(255, Math.max(0, value + amount)),
  );
  return `rgb(${channels.join(", ")})`;
}

function hexToRgb(hex: string) {
  const normalized = hex.replace("#", "").trim();
  if (normalized.length !== 6) return null;
  return {
    r: parseInt(normalized.slice(0, 2), 16),
    g: parseInt(normalized.slice(2, 4), 16),
    b: parseInt(normalized.slice(4, 6), 16),
  };
}

function mixHex(a: string, b: string, t: number) {
  const left = hexToRgb(a);
  const right = hexToRgb(b);
  if (!left || !right) return a;
  const mixChannel = (x: number, y: number) => Math.round(x + (y - x) * t);
  return `rgb(${mixChannel(left.r, right.r)}, ${mixChannel(left.g, right.g)}, ${mixChannel(left.b, right.b)})`;
}

function withAlpha(color: string, alpha: number) {
  const rgb = parseColor(color);
  if (!rgb) return color;
  return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
}

function relativeLuminance(color: string) {
  const rgb = parseColor(color);
  if (!rgb) return 0.5;
  const channels = [rgb.r, rgb.g, rgb.b].map((value) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0]! + 0.7152 * channels[1]! + 0.0722 * channels[2]!;
}

/** Lower than before — big win on first paint, still sharp on covers. */
function coverCanvasSize(book: ShelfBriefBook) {
  const planeW = book.coverPlaneWidth - 0.065;
  const planeH = book.height - 0.065;
  const height = 1024;
  const width = Math.max(520, Math.round(height * (planeW / planeH)));
  return { width, height };
}

function spineCanvasSize(book: ShelfBriefBook) {
  const planeW = Math.max(0.06, book.thickness - 0.02);
  const planeH = book.height - 0.04;
  const height = 1024;
  const width = Math.max(40, Math.round(height * (planeW / planeH)));
  return { width, height };
}

function wrapText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  lineHeight: number,
  maxLines = 6,
) {
  const words = text.split(/\s+/);
  const lines: string[] = [];
  let line = "";

  for (const word of words) {
    const test = line ? `${line} ${word}` : word;
    if (ctx.measureText(test).width > maxWidth && line) {
      lines.push(line);
      line = word;
    } else {
      line = test;
    }
  }

  if (line) lines.push(line);
  lines.slice(0, maxLines).forEach((entry, index) => {
    ctx.fillText(entry, x, y + index * lineHeight);
  });
  return Math.min(lines.length, maxLines);
}

function formatCoverDate(isoDate: string) {
  const parsed = new Date(`${isoDate}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return new Intl.DateTimeFormat(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  })
    .format(parsed)
    .toUpperCase();
}

function formatWeekday(isoDate: string) {
  const parsed = new Date(`${isoDate}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return new Intl.DateTimeFormat(undefined, { weekday: "long" }).format(parsed);
}

function addPaperGrain(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  seed: string,
  density = 420,
) {
  const random = seeded(`${seed}-grain`);
  ctx.save();
  for (let i = 0; i < density; i += 1) {
    const alpha = 0.012 + random() * 0.028;
    ctx.fillStyle =
      random() > 0.5 ? `rgba(255,255,255,${alpha})` : `rgba(0,0,0,${alpha})`;
    const size = random() * 2 + 0.3;
    ctx.fillRect(random() * width, random() * height, size, size);
  }
  ctx.restore();
}

function portraitAgents(book: ShelfBriefBook): CoverAgentPortrait[] {
  return (book.agents ?? []) as CoverAgentPortrait[];
}

function fillBase(
  ctx: CanvasRenderingContext2D,
  book: ShelfBriefBook,
  width: number,
  height: number,
  edition: CoverEdition,
) {
  if (edition === "quartz") {
    const gradient = ctx.createRadialGradient(
      width * 0.28,
      height * 0.22,
      40,
      width * 0.55,
      height * 0.55,
      width * 0.95,
    );
    gradient.addColorStop(0, shade(book.cover, 18));
    gradient.addColorStop(0.55, book.cover);
    gradient.addColorStop(1, shade(book.cover, -10));
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);
    return;
  }

  if (edition === "nocturne") {
    // Soft vignette on the lively field — not a near-black wash.
    ctx.fillStyle = shade(book.cover, -6);
    ctx.fillRect(0, 0, width, height);
    const glow = ctx.createRadialGradient(
      width * 0.72,
      height * 0.18,
      16,
      width * 0.72,
      height * 0.18,
      width * 0.42,
    );
    glow.addColorStop(0, withAlpha(book.accent, 0.42));
    glow.addColorStop(1, "transparent");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, width, height);
    return;
  }

  const gradient = ctx.createLinearGradient(0, 0, width * 0.15, height);
  gradient.addColorStop(0, shade(book.cover, 10));
  gradient.addColorStop(0.55, book.cover);
  gradient.addColorStop(1, shade(book.cover, -8));
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
}

/**
 * One bold mark per edition — deliberately different shapes/scales so
 * volumes don't all share the same scratchy line field.
 */
function drawEditionMark(
  ctx: CanvasRenderingContext2D,
  book: ShelfBriefBook,
  width: number,
  height: number,
  edition: CoverEdition,
) {
  const random = seeded(`${book.id}-mark`);
  ctx.save();
  ctx.strokeStyle = book.accent;
  ctx.fillStyle = book.accent;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  switch (edition) {
    case "folio": {
      ctx.globalAlpha = 0.9;
      ctx.fillRect(72, 88, 8, height - 220);
      ctx.globalAlpha = 0.35;
      ctx.lineWidth = 3;
      ctx.strokeRect(48, 48, width - 96, height - 96);
      break;
    }
    case "broadside": {
      ctx.globalAlpha = 1;
      ctx.fillRect(0, 0, width, 36);
      ctx.fillRect(0, height - 36, width, 36);
      ctx.globalAlpha = 0.85;
      ctx.fillRect(88, height * 0.42, width - 176, 6);
      break;
    }
    case "atlas": {
      ctx.globalAlpha = 0.28;
      ctx.lineWidth = 2;
      const cols = 4 + Math.floor(random() * 2);
      const rows = 5 + Math.floor(random() * 2);
      for (let c = 1; c < cols; c += 1) {
        const x = (width / cols) * c;
        ctx.beginPath();
        ctx.moveTo(x, 120);
        ctx.lineTo(x, height - 160);
        ctx.stroke();
      }
      for (let r = 1; r < rows; r += 1) {
        const y = 140 + ((height - 300) / rows) * r;
        ctx.beginPath();
        ctx.moveTo(90, y);
        ctx.lineTo(width - 90, y);
        ctx.stroke();
      }
      ctx.globalAlpha = 0.7;
      ctx.beginPath();
      ctx.arc(width * 0.68, height * 0.58, 54 + random() * 30, 0, Math.PI * 2);
      ctx.lineWidth = 4;
      ctx.stroke();
      break;
    }
    case "field-notes": {
      ctx.globalAlpha = 1;
      ctx.fillStyle = mixHex(book.accent, book.cover, 0.35);
      ctx.fillRect(0, 0, 64, height);
      ctx.fillStyle = book.accent;
      ctx.fillRect(64, 0, 10, height);
      break;
    }
    case "quartz": {
      ctx.globalAlpha = 0.22;
      ctx.beginPath();
      ctx.moveTo(width * 0.12, 0);
      ctx.lineTo(width * 0.48, 0);
      ctx.lineTo(width * 0.3, height);
      ctx.lineTo(-0.02 * width, height);
      ctx.closePath();
      ctx.fill();
      ctx.globalAlpha = 0.55;
      ctx.beginPath();
      ctx.moveTo(width * 0.55, height * 0.35);
      ctx.lineTo(width * 0.82, height * 0.28);
      ctx.lineTo(width * 0.74, height * 0.62);
      ctx.closePath();
      ctx.fill();
      break;
    }
    case "nocturne": {
      ctx.globalAlpha = 0.55;
      ctx.lineWidth = 3;
      const cx = width * 0.72;
      const cy = height * 0.28;
      ctx.beginPath();
      ctx.arc(cx, cy, 70, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(cx, cy, 38, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 0.85;
      ctx.beginPath();
      ctx.arc(cx + 48, cy - 10, 14, 0, Math.PI * 2);
      ctx.fill();
      break;
    }
    case "linen": {
      // Soft ruled page — only this edition gets horizontal rules.
      ctx.globalAlpha = 0.18;
      ctx.lineWidth = 1.5;
      for (let y = 200; y < height - 180; y += 28) {
        ctx.beginPath();
        ctx.moveTo(100, y);
        ctx.lineTo(width - 90, y);
        ctx.stroke();
      }
      break;
    }
    case "signal": {
      ctx.globalAlpha = 1;
      const bars = 5;
      for (let i = 0; i < bars; i += 1) {
        ctx.globalAlpha = 0.3 + i * 0.14;
        const w = 22 + i * 22;
        const h = 14 + i * 4;
        ctx.fillRect(width - 80 - w, 160 + i * (h + 14), w, h);
      }
      break;
    }
  }
  ctx.restore();
}

export function editionForSeed(id: string): CoverEdition {
  const random = seeded(`${id}-edition`);
  return EDITIONS[Math.floor(random() * EDITIONS.length)] ?? "folio";
}

function drawSummaryLines(
  ctx: CanvasRenderingContext2D,
  book: ShelfBriefBook,
  x: number,
  top: number,
  width: number,
  lineCount: number,
  lineGap: number,
) {
  ctx.save();
  ctx.strokeStyle = withAlpha(book.ink, 0.14);
  ctx.lineWidth = 1.5;
  for (let i = 0; i < lineCount; i += 1) {
    const y = top + i * lineGap;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + width, y);
    ctx.stroke();
  }
  ctx.restore();
}

function drawSummaryOnLines(
  ctx: CanvasRenderingContext2D,
  book: ShelfBriefBook,
  text: string,
  x: number,
  firstBaseline: number,
  maxWidth: number,
  lineGap: number,
  maxLines: number,
) {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    const test = line ? `${line} ${word}` : word;
    if (ctx.measureText(test).width > maxWidth && line) {
      lines.push(line);
      line = word;
    } else {
      line = test;
    }
  }
  if (line) lines.push(line);

  const dark = relativeLuminance(book.cover) < 0.42;
  ctx.fillStyle = dark ? "rgba(255,255,255,0.92)" : withAlpha(book.ink, 0.88);
  lines.slice(0, maxLines).forEach((entry, index) => {
    ctx.fillText(entry, x, firstBaseline + index * lineGap);
  });
}

export function createFrontCover(book: ShelfBriefBook) {
  const { width, height } = coverCanvasSize(book);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const edition = book.edition ?? editionForSeed(book.id);
  fillBase(ctx, book, width, height, edition);
  // Quiet edition chrome only — no random motif shapes.
  if (edition === "field-notes" || edition === "folio" || edition === "broadside") {
    drawEditionMark(ctx, book, width, height, edition);
  }
  addPaperGrain(ctx, width, height, book.id);

  const leftPad = edition === "field-notes" ? 100 : 88;
  const title = book.shortTitle || formatWeekday(book.date);

  ctx.fillStyle = mixHex(book.ink, book.accent, 0.22);
  ctx.font = `600 20px ${sans}`;
  ctx.fillText(formatCoverDate(book.date), leftPad, 128);

  const titleSize =
    title.length > 12 ? 86 : title.length > 9 ? 102 : 118;
  ctx.font = `600 ${titleSize}px ${serif}`;
  ctx.fillStyle = book.titleColor ?? book.ink;
  // Leave clear air under the date so they never collide.
  wrapText(ctx, title, leftPad, 220, width - leftPad - 70, titleSize * 0.98, 2);

  const summary = book.tagline?.trim();
  const lineGap = 36;
  const summaryTop = 220 + titleSize * 1.15 + 36;
  const summaryWidth = width - leftPad - 80;
  const lineCount = 7;

  if (summary) {
    drawSummaryLines(
      ctx,
      book,
      leftPad,
      summaryTop,
      summaryWidth,
      lineCount,
      lineGap,
    );
    ctx.font = `italic 400 26px ${serif}`;
    // Baseline sits just above each rule.
    drawSummaryOnLines(
      ctx,
      book,
      summary,
      leftPad,
      summaryTop - 10,
      summaryWidth,
      lineGap,
      Math.min(6, lineCount - 1),
    );
  }

  const agents = portraitAgents(book);
  if (agents.length) {
    drawAgentOrbRow(ctx, agents, leftPad, height - 96, 28, 12);
  }

  return canvas;
}

export function createSpineCover(book: ShelfBriefBook) {
  const { width, height } = spineCanvasSize(book);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, shade(book.cover, 4));
  gradient.addColorStop(1, shade(book.cover, -12));
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
  addPaperGrain(ctx, width, height, `${book.id}-spine`, 180);

  ctx.fillStyle = book.accent;
  ctx.fillRect(
    Math.max(5, width * 0.1),
    18,
    Math.max(3, width * 0.14),
    height - 36,
  );

  const weekday = formatWeekday(book.date);
  const spineTitle = (book.shortTitle || weekday).trim();
  const spineSubtitle = (book.tagline ?? "").trim();
  let titleSize = Math.min(46, Math.max(24, width * 2.1));
  const dateSize = Math.min(18, Math.max(12, width * 0.85));
  const textX = width / 2 + Math.max(3, width * 0.05);

  // Shrink then ellipsize so long book titles stay on the spine.
  const maxTitleLength = height * 0.58;
  ctx.font = `600 ${titleSize}px ${serif}`;
  let spineText = spineTitle;
  if (ctx.measureText(spineText).width > maxTitleLength) {
    titleSize = Math.max(17, titleSize * 0.72);
    ctx.font = `600 ${titleSize}px ${serif}`;
  }
  if (ctx.measureText(spineText).width > maxTitleLength) {
    while (
      spineText.length > 4 &&
      ctx.measureText(`${spineText}…`).width > maxTitleLength
    ) {
      spineText = spineText.slice(0, -1).trimEnd();
    }
    spineText = `${spineText}…`;
  }

  // Title in the upper band — clear of the subtitle.
  ctx.save();
  ctx.translate(textX, height * 0.34);
  ctx.rotate(-Math.PI / 2);
  ctx.fillStyle = book.ink;
  ctx.font = `600 ${titleSize}px ${serif}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(spineText, 0, 0);
  ctx.restore();

  // Subtitle (author) in the lower band with generous gap so they never collide.
  if (spineSubtitle) {
    ctx.save();
    ctx.translate(textX, height * 0.72);
    ctx.rotate(-Math.PI / 2);
    ctx.fillStyle = mixHex(book.ink, book.accent, 0.3);
    ctx.font = `600 ${dateSize}px ${sans}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(spineSubtitle, 0, 0);
    ctx.restore();
  }

  const agents = portraitAgents(book);
  if (agents.length) {
    const orbRadius = Math.min(width * 0.24, 16);
    const centerX = width / 2;
    const baseY = height - 48;
    agents.slice(0, 2).forEach((agent, index) => {
      const offset = (index - 0.5) * (orbRadius * 2.1);
      drawAgentOrb(ctx, agent, centerX + offset, baseY, orbRadius);
    });
  }

  return canvas;
}

export function createBackCover(book: ShelfBriefBook) {
  const { width, height } = coverCanvasSize(book);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  ctx.fillStyle = shade(book.cover, -6);
  ctx.fillRect(0, 0, width, height);
  addPaperGrain(ctx, width, height, `${book.id}-back`, 260);

  ctx.fillStyle = book.ink;
  ctx.font = `500 36px ${serif}`;
  wrapText(ctx, book.tagline || book.title, 88, 160, width - 176, 48, 8);

  ctx.fillStyle = book.accent;
  ctx.fillRect(88, 440, 72, 6);

  return canvas;
}

/** Fast first-paint placeholder — solid boards until full covers land. */
export function createPlaceholderFront(book: ShelfBriefBook) {
  const { width, height } = coverCanvasSize(book);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * 0.5);
  canvas.height = Math.round(height * 0.5);
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  ctx.fillStyle = book.cover;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = book.accent;
  ctx.fillRect(24, 28, 4, canvas.height - 70);
  ctx.fillStyle = book.ink;
  ctx.font = `600 42px ${serif}`;
  ctx.fillText(book.shortTitle.slice(0, 10), 36, 90);
  return canvas;
}

export function createPlaceholderSpine(book: ShelfBriefBook) {
  const { width, height } = spineCanvasSize(book);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(24, Math.round(width * 0.5));
  canvas.height = Math.round(height * 0.5);
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  ctx.fillStyle = shade(book.cover, -12);
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = book.accent;
  ctx.fillRect(4, 8, 3, canvas.height - 16);
  return canvas;
}

export function paletteForBrief(
  date: string,
  index: number,
  agentColors: string[] = [],
  tools: string[] = [],
) {
  const random = seeded(`${date}-${index}-palette`);
  const base =
    EDITION_PALETTES[Math.floor(random() * EDITION_PALETTES.length)] ??
    EDITION_PALETTES[0]!;

  const primaryAgent = agentColors[0];
  const toolAccent = tools
    .map((tool) => TOOLKIT_ACCENTS[tool])
    .find(Boolean);

  // Light agent tint only — keep the edition wash as a full lively field.
  const cover = primaryAgent
    ? mixHex(base.cover, primaryAgent, 0.06 + random() * 0.06)
    : base.cover;
  const accent = toolAccent
    ? mixHex(base.accent, toolAccent, 0.28)
    : primaryAgent
      ? mixHex(base.accent, primaryAgent, 0.18)
      : base.accent;
  const dark = relativeLuminance(cover) < 0.42;

  return {
    cover,
    accent,
    ink: dark ? base.ink : "#17130f",
    titleColor: dark ? base.titleColor : mixHex(base.titleColor, "#1a1520", 0.2),
  };
}

export function motifForSeed(id: string, tools: string[]): BriefCoverMotif {
  if (tools.includes("github")) return "network";
  if (tools.includes("slack")) return "lattice";
  if (tools.includes("googlecalendar")) return "continuum";
  if (tools.includes("gmail")) return "wave";
  const random = seeded(id);
  const motifs: BriefCoverMotif[] = [
    "lattice",
    "network",
    "orbit",
    "wave",
    "schematic",
    "continuum",
  ];
  return motifs[Math.floor(random() * motifs.length)] ?? "orbit";
}
