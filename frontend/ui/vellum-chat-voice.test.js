import { describe, expect, test } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, "vellum-chat.html"), "utf8");

describe("vellum voice UI wiring", () => {
  test("pins local desktop API calls to loopback backend", () => {
    expect(html).toContain("function resolveApiBase");
    expect(html).toContain("return 'http://127.0.0.1:8000';");
  });

  test("keeps full model picker available when model API is unreachable", () => {
    expect(html).toContain("Claude Opus 4.7");
    expect(html).toContain("GPT 5.5");
    expect(html).toContain("DeepSeek V4 Pro");
    expect(html).toContain("Qwen 3.5 35B A3B");
  });

  test("shows the attempted API origin when fetch fails", () => {
    expect(html).toContain("function enrichFetchError");
    expect(html).toContain("api:");
  });

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

  test("computer-use voice mode sends instructions to the agent", () => {
    expect(html).toContain("computerUseState.enabled ? sendVoice(wav) : transcribeVoice(wav)");
    expect(html).toContain("/api/voice/turn");
    expect(html).toContain("playBase64Wav");
  });

  test("computer-use toggle speaks its acknowledgement", () => {
    expect(html).toContain("speakText(payload.message)");
  });

  test("computer-use toggle uses session endpoints", () => {
    expect(html).toContain("session/start");
    expect(html).toContain("session/stop");
  });

  test("browser UI does not draw the laptop-wide aura inside the tab", () => {
    expect(html).toContain(".computer-use-aura");
    expect(html).toContain("display: none");
  });

  test("computer-use status polling keeps the exclusive-control heartbeat alive", () => {
    expect(html).toContain("setInterval(loadComputerUseStatus, 5000)");
  });

  test("computer-use mode listens after the spoken acknowledgement", () => {
    expect(html).toContain("startComputerUseVoiceAutoStop");
    expect(html).toContain("startVoiceRecording();");
  });

  test("computer-use mode preflights microphone before locking input", () => {
    expect(html).toContain("ensureVoicePermission");
    expect(html).toContain("await ensureVoicePermission();");
    expect(html.indexOf("await ensureVoicePermission();")).toBeLessThan(html.indexOf("fetch(`${API_BASE}/api/computer-use/${endpoint}`"));
  });

  test("computer-use voice re-arms after each voice turn", () => {
    expect(html).toContain("queueComputerUseListening");
    expect(html).toContain("if (computerUseState.enabled && !computerUseState.paused) queueComputerUseListening();");
  });

  test("computer-use voice does not refocus the text input while laptop control is locked", () => {
    expect(html).toContain("if (!computerUseState.enabled) chatInput.focus();");
  });

  test("computer-use feed recognizes workspace actions", () => {
    expect(html).toContain("workspace_action");
    expect(html).toContain("Workspace");
    expect(html).toContain("computer-use-workspace");
  });
});
