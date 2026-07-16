import { describe, expect, test } from "vitest";
import fs from "node:fs";
import path from "node:path";

const htmlPath = path.resolve("../design/Velllum/uploads/Vellum Default Re-designed.html");
const settingsClientPath = path.resolve("../design/Velllum/uploads/api/settings.js");

describe("Vellum default activity status", () => {
  test("shows complete live activity labels with semantic loaders and no typing loop", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("isThinkingActivity");
    expect(html).toContain("activityVisualKind");
    expect(html).toContain("ActivityLoader");
    expect(html).toContain("activity-text fx-spotlight");
    expect(html).toContain('aria-atomic="true"');
    expect(html).not.toContain("THINKING_ROTATION_LABELS");
    expect(html).not.toContain("Cooking up your answer");
    expect(html).not.toContain("typingLabel");
    expect(html).not.toContain("typingText");
  });

  test("composer exposes stop answering control and abort plumbing", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("onStop");
    expect(html).toContain("stopActiveTurn");
    expect(html).toContain("controller.abort()");
    expect(html).toContain("title=\"Stop answering\"");
    expect(html).toContain("IcStop");
  });

  test("chat row menu uses a viewport clamped position helper", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("clampMenuPosition");
    expect(html).toContain("Math.max(12");
    expect(html).toContain("Math.min(preferredX");
    expect(html).toContain("clampMenuPosition(pos, 230, 260)");
    expect(html).toContain(".ctx-menu{position:fixed;z-index:1000");
    expect(html).toContain("portal className=\"ctx-menu\"");
  });

  test("casual greetings suppress the full activity ceremony until a real tool runs", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("isCasualGreetingPrompt");
    expect(html).toContain("suppressActivity");
    expect(html).toContain("isQuietAnswerActivity");
    expect(html).toContain("items.every(isQuietAnswerActivity)");
  });

  test("settings memory surfaces load live backend memory instead of static-only data", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("mockMemory: false");
    expect(html).toContain("memoryData");
    expect(html).toContain("API.settings.memoryEntries()");
    expect(html).toContain("MemorySummaryCard");
    expect(html).toContain("SavedMemoriesCard");
  });

  test("memory summary controls persist through the live memory API", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("API.settings.createMemory({text");
    expect(html).toContain("API.settings.memoryImportConversations()");
    expect(html).toContain("API.settings.memoryDreamingRun()");
    expect(html).toContain('value={draft}');
    expect(html).toContain('onChange={e => setDraft(e.target.value)}');
    expect(html).not.toContain("Updated 8 hours ago");
  });

  test("saved memories surface saved, old, and recent backend records", () => {
    const html = fs.readFileSync(htmlPath, "utf8");
    const settingsClient = fs.readFileSync(settingsClientPath, "utf8");

    expect(html).toContain("API.settings.memorySaved()");
    expect(html).toContain("API.settings.archiveMemory(m.id)");
    expect(html).toContain("API.settings.deleteMemory(m.id)");
    expect(html).toContain("API.settings.updateMemory(m.id");
    expect(html).toContain("Saved (");
    expect(html).toContain("Old (");
    expect(html).toContain("Recent (");
    expect(settingsClient).toContain("memorySaved: function");
    expect(settingsClient).toContain("memoryImportConversations: function");
    expect(settingsClient).toContain("createMemory: function");
    expect(settingsClient).toContain("recent_context");
  });

  test("memory surfaces format backend records instead of dumping raw transcripts", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("buildMemorySummarySections");
    expect(html).toContain("parseRecentMemoryRecord");
    expect(html).toContain("MemorySummaryDocument");
    expect(html).toContain("MemoryListRow");
    expect(html).toContain('className="mem-doc-section"');
    expect(html).toContain('className="sm-item-title"');
    expect(html).toContain('className="sm-item-body"');
    expect(html).toContain('className="sm-item-details"');
    expect(html).toContain("visibleSaved");
    expect(html).toContain("isMemoryOperationalNoise");
    expect(html).not.toContain('<span className="sm-item-text">{m.content}</span>');
    expect(html).not.toContain('<span className="sm-item-text">{m.text}</span>');
  });

  test("collapsed sidebar chat menus open inward beside the flyout", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("preferLeft");
    expect(html).toContain("pos.x - width - 10");
    expect(html).toContain("preferLeft: true");
  });

  test("dreaming console triggers the backend consolidation job", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("API.settings.memoryDreamingRun()");
    expect(html).toContain("refreshMemoryData");
    expect(html).not.toContain("setTimeout(() => {\n      setDreams");
  });

  test("memory toggles persist through backend settings", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("API.settings.memorySettings()");
    expect(html).toContain("API.settings.updateMemorySettings");
    expect(html).toContain("setMemoryToggle('memory', 'memory_enabled'");
    expect(html).toContain("setMemoryToggle('refHistory', 'reference_history_enabled'");
    expect(html).toContain("setMemoryToggle('dreaming', 'dreaming_enabled'");
  });
});
