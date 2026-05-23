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
    expect(html).toContain("/api/voice/transcribe");
    expect(html).toContain("/api/voice/speak");
  });

  test("dictates transcript into the composer and speaks after final response", () => {
    expect(html).toContain("insertVoiceTranscript");
    expect(html).toContain("pendingVoiceDraft");
    expect(html).toContain("if (shouldSpeakResponse) void speakText(answer)");
    expect(html).toContain("cancelActiveVoice");
  });
});
