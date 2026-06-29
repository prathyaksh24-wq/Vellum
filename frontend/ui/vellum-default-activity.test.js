import { describe, expect, test } from "vitest";
import fs from "node:fs";
import path from "node:path";

const htmlPath = path.resolve("../design/Velllum/uploads/Vellum Default Re-designed.html");
const settingsClientPath = path.resolve("../design/Velllum/uploads/api/settings.js");

describe("Vellum default activity status", () => {
  test("rotates thinking copy in the visible activity row while waiting", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("THINKING_ROTATION_LABELS");
    expect(html).toContain("isThinkingActivity");
    expect(html).toContain("setInterval(() => setThinkingIndex");
    expect(html).toContain("clearInterval(id)");
    expect(html).toContain("Cooking up your answer");
    expect(html).toContain("typingLabel");
    expect(html).toContain("typingText");
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
