import { describe, expect, test } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(resolve(here, "../../design/Velllum/uploads/Vellum Default Re-designed.html"), "utf8");

describe("Vellum default redesigned frontend", () => {
  test("loads the modular frontend API bridge used by backend integrations", () => {
    expect(html).toMatch(/<script src="api\/client\.js(?:\?[^\"]+)?"><\/script>/);
    expect(html).toContain('<script src="api/chat.js"></script>');
    expect(html).toContain('<script src="api/conversations.js"></script>');
    expect(html).toContain('<script src="api/plugins.js"></script>');
    expect(html).toMatch(/<script src="api\/settings\.js(?:\?[^\"]+)?"><\/script>/);
    expect(html).toMatch(/<script src="api\/knowledge\.js(?:\?[^\"]+)?"><\/script>/);
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

  test("uses backend-owned YouTube OAuth without collecting credentials in the UI", () => {
    expect(html).toContain("const YouTubeAPI");
    expect(html).toContain("API.plugins.youtubeOAuthStart()");
    expect(html).toContain("API.plugins.youtubeSync");
    expect(html).toContain("API.plugins.youtubeDisconnect()");
    expect(html).not.toContain("clientSecret");
    expect(html).not.toContain("Email or phone");
    expect(html).not.toContain("Manage videos and drafts on your behalf");
  });

  test("does not contain unresolved Git conflict markers", () => {
    expect(html).not.toMatch(/^(<<<<<<<|=======|>>>>>>>)/m);
  });

  test("includes routing, OpenRouter, memory, and Hermes-compatible plugin surfaces", () => {
    expect(html).toContain("OpenRouter");
    expect(html).toContain("Provider routing, fallback models, and credential pools");
    expect(html).toContain("memoryDreamingRun");
    expect(html).toContain("Portable plugins are loaded through Vellum's Hermes-compatible");
    expect(html).toContain("API.runtimes.subagents()");
  });

  test("uses one live memory state and supports Vault or wiki chat context", () => {
    expect(html).toContain("<MemoryConsole page memoryData={memoryData} onRefresh={refreshMemoryData}");
    expect(html).toContain("Array.isArray(summary.sections)");
    expect(html).toContain("API.knowledge.search(value, scope, 20)");
    expect(html).toContain("New chat with context");
    expect(html).toContain("API.conversations.attachContext");
  });
});
