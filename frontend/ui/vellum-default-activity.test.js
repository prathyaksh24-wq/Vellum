import { describe, expect, test } from "vitest";
import fs from "node:fs";
import path from "node:path";

const htmlPath = path.resolve("../design/Velllum/uploads/Vellum Default Re-designed.html");
const settingsClientPath = path.resolve("../design/Velllum/uploads/api/settings.js");
const memoryPagePath = path.resolve("../design/Velllum/uploads/components/memory-page.jsx");

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
    expect(html).toContain("<window.VellumUI.MemorySettings settings={memoryData && memoryData.settings}");
    // The old summary and saved-memories modals were replaced by the Memory page.
    expect(html).not.toContain("MemorySummaryCard");
    expect(html).not.toContain("SavedMemoriesCard");
    expect(html).not.toContain("MemoryConsole");
  });

  test("the memory page edits memory through App Actions and the live memory API", () => {
    const page = fs.readFileSync(memoryPagePath, "utf8");

    expect(page).toContain("onMemoryAction('memory.correction.create', {correction:chip.draft.trim(), selection:chip.text})");
    expect(page).toContain("api().memorySuppress({selection:chip.text})");
    expect(page).toContain("api().memoryAboutYouStream({force");
    expect(page).toContain("api().memoryAsk(value)");
    expect(page).toContain("act('memory.conversations.import', {})");
    expect(page).toContain("act('memory.dreaming.run', {})");
    expect(page).not.toContain("Updated 8 hours ago");
  });

  test("topic items can be edited, paused, archived and deleted, and imports are reviewed first", () => {
    const page = fs.readFileSync(memoryPagePath, "utf8");
    const settingsClient = fs.readFileSync(settingsClientPath, "utf8");

    expect(page).toContain("onMemoryAction('memory.entry.update', {memory_id:item.id");
    expect(page).toContain("run('memory.entry.suppress', {memory_id:item.id, suppressed:!item.suppressed})");
    expect(page).toContain("run('memory.entry.archive', {memory_id:item.id})");
    expect(page).toContain("run('memory.entry.delete', {memory_id:item.id})");
    expect(page).toContain("onMemoryAction('memory.import.apply', {items:plan.items}, {confirmedFromUi:true})");
    for (const method of ["memoryAboutYou", "memoryAboutYouStream", "memoryCorrect", "memorySuppress", "memoryFeedback",
      "memoryUndoSave", "memoryAsk", "memoryTopics", "memoryGrowth", "memoryImportPrompt", "memoryImportPlan",
      "memoryImportApply", "memoryExport"]) {
      expect(settingsClient).toContain(method + ": ");
    }
  });

  test("suppressed and archived memories stay visible but marked", () => {
    const page = fs.readFileSync(memoryPagePath, "utf8");

    expect(page).toContain("(item.suppressed || archived ? ' is-dim' : '')");
    expect(page).toContain('<span className="mp-flag">Not used</span>');
    expect(page).toContain('<span className="mp-flag">Archived</span>');
    expect(page).toContain('className="mp-origin"');
  });

  test("sidebar chat menus clamp to the viewport with off-canvas navigation", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("preferLeft");
    expect(html).toContain("pos.x - width - 10");
    expect(html).toContain('className="main-sidebar-slot"');
    expect(html).toContain('data-collapsible="offcanvas"');
  });

  test("the memory page triggers the backend consolidation job", () => {
    const html = fs.readFileSync(htmlPath, "utf8");
    const page = fs.readFileSync(memoryPagePath, "utf8");

    expect(page).toContain("act('memory.dreaming.run', {})");
    expect(html).toContain("refreshMemoryData");
    expect(html).not.toContain("setTimeout(() => {\n      setDreams");
  });

  test("memory toggles persist through backend settings", () => {
    const html = fs.readFileSync(htmlPath, "utf8");

    expect(html).toContain("API.settings.memorySettings()");
    expect(html).toContain("onMemorySettings={onMemorySettings}");
    const page = fs.readFileSync(memoryPagePath, "utf8");
    expect(page).toContain("onMemorySettings({[key]: next})");
    for (const key of ["memory_enabled", "reference_history_enabled", "save_new_memories", "include_sensitive", "auto_archive_enabled"]) {
      expect(page).toContain("['" + key + "', ");
    }
  });
});
