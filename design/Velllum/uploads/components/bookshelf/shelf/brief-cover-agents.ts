import {
  isAutoAgentLogoSrc,
  resolveAgentIconSrc,
} from "../lib/agent-stubs";
import { belongsInBringYourOwnAgent } from "../lib/agent-stubs";
import { resolveAgentVisualIdentity } from "../lib/agent-visual-identity";
import type { CoverAgent } from "./brief-cover-meta";

const imageCache = new Map<string, HTMLImageElement | null>();

export type CoverAgentPortrait = CoverAgent & {
  portrait?: HTMLImageElement | null;
  brandLogo?: HTMLImageElement | null;
};

function loadImage(url: string): Promise<HTMLImageElement | null> {
  const cached = imageCache.get(url);
  if (cached !== undefined) return Promise.resolve(cached);

  return new Promise((resolve) => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => {
      imageCache.set(url, image);
      resolve(image);
    };
    image.onerror = () => {
      imageCache.set(url, null);
      resolve(null);
    };
    image.src = url;
  });
}

/**
 * Preload assets needed to paint agent marks the same way rooms do:
 * custom photo → brand logo (BYO) → generative fluid identity.
 */
export async function preloadCoverAgentPortraits(
  agents: CoverAgent[],
): Promise<Map<string, { portrait: HTMLImageElement | null; brandLogo: HTMLImageElement | null }>> {
  const entries = await Promise.all(
    agents.map(async (agent) => {
      let portrait: HTMLImageElement | null = null;
      let brandLogo: HTMLImageElement | null = null;

      if (agent.pictureUrl && !isAutoAgentLogoSrc(agent.pictureUrl)) {
        portrait = await loadImage(agent.pictureUrl);
      } else if (belongsInBringYourOwnAgent(agent.model)) {
        const brandSrc = resolveAgentIconSrc({
          model: agent.model ?? undefined,
          logoSrc: agent.pictureUrl ?? undefined,
        });
        brandLogo = await loadImage(brandSrc);
      }

      return [agent.id, { portrait, brandLogo }] as const;
    }),
  );

  return new Map(entries);
}

/** Soft organic fluid mark — open silhouette like GenerativeAgentIcon / AgentOrb. */
export function drawAgentOrb(
  ctx: CanvasRenderingContext2D,
  agent: CoverAgentPortrait,
  x: number,
  y: number,
  radius: number,
) {
  const identity = resolveAgentVisualIdentity(agent.agentColor, agent.id);
  const [deep, main, light] = identity.colors;

  ctx.save();

  if (agent.portrait) {
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.closePath();
    ctx.clip();
    ctx.drawImage(
      agent.portrait,
      x - radius,
      y - radius,
      radius * 2,
      radius * 2,
    );
    ctx.restore();
    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(255,255,255,0.35)";
    ctx.lineWidth = Math.max(1.2, radius * 0.07);
    ctx.stroke();
    ctx.restore();
    return;
  }

  if (agent.brandLogo) {
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(245,245,245,0.96)";
    ctx.fill();
    const logoSize = radius * 1.15;
    ctx.drawImage(
      agent.brandLogo,
      x - logoSize / 2,
      y - logoSize / 2,
      logoSize,
      logoSize,
    );
    ctx.restore();
    return;
  }

  // Open fluid silhouette (no hard circular crop) — matches room AgentOrb.
  for (const blob of identity.blobs.slice(0, 4)) {
    const bx = x + (blob.x / 100 - 0.5) * radius * 1.55;
    const by = y + (blob.y / 100 - 0.5) * radius * 1.55;
    const br = radius * (blob.w / 100) * 1.05;
    const color = identity.colors[blob.colorIndex] ?? main;
    const gradient = ctx.createRadialGradient(bx, by, 0, bx, by, br);
    gradient.addColorStop(0, `${color}dd`);
    gradient.addColorStop(0.55, `${color}88`);
    gradient.addColorStop(1, `${color}00`);
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.ellipse(
      bx,
      by,
      br * (0.85 + blob.phase * 0.25),
      br * (0.7 + (1 - blob.phase) * 0.35),
      blob.rotate * (Math.PI / 180),
      0,
      Math.PI * 2,
    );
    ctx.fill();
  }

  const core = ctx.createRadialGradient(
    x - radius * 0.15,
    y - radius * 0.2,
    radius * 0.05,
    x,
    y,
    radius * 0.95,
  );
  core.addColorStop(0, `${light}99`);
  core.addColorStop(0.45, `${main}55`);
  core.addColorStop(1, `${deep}00`);
  ctx.fillStyle = core;
  ctx.beginPath();
  ctx.arc(x, y, radius * 0.92, 0, Math.PI * 2);
  ctx.fill();

  ctx.restore();
}

export function drawAgentOrbRow(
  ctx: CanvasRenderingContext2D,
  agents: CoverAgentPortrait[],
  x: number,
  y: number,
  radius: number,
  gap: number,
) {
  const visible = agents.slice(0, 4);
  visible.forEach((agent, index) => {
    drawAgentOrb(ctx, agent, x + index * (radius * 2 + gap), y, radius);
  });
}
