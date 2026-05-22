import { describe, expect, test } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, "vellum-chat.html"), "utf8");

describe("vellum voice UI wiring", () => {
  test("includes push-to-talk controls and voice endpoints", () => {
    expect(html).toContain('id="voiceBtn"');
    expect(html).toContain("MediaRecorder");
    expect(html).toContain("/api/voice/turn");
    expect(html).toContain("/api/voice/speak");
  });

  test("handles transcript and audio SSE events", () => {
    expect(html).toContain("event === 'transcript'");
    expect(html).toContain("event === 'audio'");
    expect(html).toContain("playBase64Wav");
    expect(html).toContain("cancelActiveVoice");
  });
});
