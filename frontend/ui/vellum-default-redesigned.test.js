import { describe, expect, test } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, "Vellum Default Re-designed.html"), "utf8");

describe("Vellum default redesigned frontend", () => {
  test("loads the modular frontend API bridge used by backend integrations", () => {
    expect(html).toContain('<script src="api/client.js"></script>');
    expect(html).toContain('<script src="api/chat.js"></script>');
    expect(html).toContain('<script src="api/conversations.js"></script>');
    expect(html).toContain('<script src="api/plugins.js"></script>');
    expect(html).toContain('<script src="api/settings.js?v=20260702-llm-routing"></script>');
    expect(html).toContain('<script src="api/runtimes.js"></script>');
  });

  test("keeps the approved web UI shell instead of the old desktop chrome", () => {
    expect(html).toContain("galaxy-container");
    expect(html).toContain("AppBackground");
    expect(html).toContain("dock-layer");
    expect(html).toContain("Show dock");
    expect(html).toContain("Dock position");
    expect(html).not.toContain('class="titlebar"');
  });

  test("includes Spotify plugin controls and player API integration", () => {
    expect(html).toContain("const SpotifyAPI");
    expect(html).toContain("/api/plugins/spotify/status");
    expect(html).toContain("/api/plugins/spotify/oauth/start");
    expect(html).toContain("/api/plugins/spotify/player/action");
    expect(html).toContain("SpotifyPlayer");
  });

  test("includes routing, OpenRouter, memory, and Hermes-compatible plugin surfaces", () => {
    expect(html).toContain("OpenRouter");
    expect(html).toContain("OpenRouter provider fallback");
    expect(html).toContain("memoryDreamingRun");
    expect(html).toContain("Portable plugins are loaded through Vellum's Hermes-compatible");
    expect(html).toContain("/api/agent-runtime/departments");
    expect(html).toContain("/api/agent-runtime/tasks");
  });
});
