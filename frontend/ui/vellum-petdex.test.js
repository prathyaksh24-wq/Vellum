import { describe, expect, test } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(resolve(here, "../../design/Velllum/uploads/Vellum Default Re-designed.html"), "utf8");

describe("Vellum Petdex companion", () => {
  test("fetches the live manifest with a localStorage cache", () => {
    expect(html).toContain("const PETDEX_MANIFEST = 'https://petdex.dev/api/manifest';");
    expect(html).toContain("PETDEX_MANIFEST_TTL");
    expect(html).toContain("fetch(PETDEX_MANIFEST)");
    expect(html).toContain("vellum-pet-manifest");
    expect(html).toContain("vellum-pet-manifest-at");
    expect(html).toContain("setPetError(cached ? 'Gallery unreachable.");
  });

  test("falls back to the bundled boba sprite offline", () => {
    expect(html).toContain("assets/pets/boba.webp");
    expect(html).toContain("PETDEX_FALLBACK");
    expect(html).toContain("slug === 'boba'");
  });

  test("ships the five curated collections", () => {
    for (const id of ["pokemon", "anime-heroes", "meme-lords", "jojo", "coders-club"]) {
      expect(html).toContain(`{id: '${id}'`);
    }
    expect(html).toContain("All pets");
  });

  test("maps activity states to atlas rows with frame counts", () => {
    expect(html).toContain("idle: {row: 0, frames: 6, ms: 1100}");
    expect(html).toContain("'running-right': {row: 1, frames: 8, ms: 1060}");
    expect(html).toContain("waving: {row: 3, frames: 4, ms: 700}");
    expect(html).toContain("jumping: {row: 4, frames: 5, ms: 840}");
    expect(html).toContain("failed: {row: 5, frames: 8, ms: 1220}");
    expect(html).toContain("waiting: {row: 6, frames: 6, ms: 1010}");
    expect(html).toContain("review: {row: 8, frames: 6, ms: 1030}");
    expect(html).toContain("steps(calc(var(--px-frames) - 1))");
    expect(html).toContain("--px-row");
    expect(html).toContain("--px-frames");
  });

  test("reacts to streaming, thinking, tool activity, and errors", () => {
    expect(html).toContain("m.streaming && m.phase === 'thinking'");
    expect(html).toContain("a.status === 'in_progress'");
    expect(html).toContain("trigger('waving', 1400)");
    expect(html).toContain("trigger('failed', 2400)");
    expect(html).toContain("toolsBusy ? 'running'");
  });

  test("persists every pet preference to localStorage", () => {
    for (const key of ["vellum-pet-installed", "vellum-pet-active", "vellum-pet-hidden", "vellum-pet-size", "vellum-pet-pos"]) {
      expect(html).toContain(`'${key}'`);
    }
  });

  test("exposes Petdex as a Settings tab wired to the modal", () => {
    expect(html).toContain("{k: 'Petdex',");
    expect(html).toContain("{tab === 'Petdex' && (");
    expect(html).toContain("<PetdexTab manifest={petManifest}");
    expect(html).toContain("onPetToggleInstall={petToggleInstall}");
  });

  test("mounts a draggable floating pet with a hover menu", () => {
    expect(html).toContain("<PetFloater record={activePetRecord}");
    expect(html).toContain("setPetHidden(true)");
    expect(html).toContain("onPointerDown={onPointerDown}");
    expect(html).toContain("setPointerCapture");
    expect(html).toContain("Hide pet");
    expect(html).toContain("onJump()");
    expect(html).toContain("touch-action:none");
  });

  test("gallery supports search, filters, install, and size choices", () => {
    expect(html).toContain("placeholder=\"Search the gallery…\"");
    expect(html).toContain("onToggleInstall(p.slug)");
    expect(html).toContain("onSetActive(p.slug)");
    expect(html).toContain("px-size");
    expect(html).toContain("{id: 'sm', label: 'Small'}");
    expect(html).toContain("Nothing installed yet");
  });
});
