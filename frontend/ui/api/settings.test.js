import { beforeEach, describe, expect, test, vi } from "vitest";

async function loadSettingsApi(fetchImpl) {
  vi.resetModules();
  window.VellumApi = {
    client: {
      request: async (path, options) => fetchImpl(path, options),
      jsonOptions: (method, body) => ({
        method,
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    },
  };
  await import("../../../design/Velllum/uploads/api/settings.js");
  return window.VellumApi.settings;
}

describe("Vellum settings API memory endpoints", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  test("reads orchestrator summary as facts and entries", async () => {
    const fetchImpl = vi.fn(async (path) => {
      expect(path).toBe("/api/memory/summary");
      return {
        global_summary: "User is building Vellum.",
        saved_memories: [{ id: 1, text: "User prefers concise answers." }],
        recent_context: [{ id: 9, content: "Q: older chat\nA: remembered detail", created: "2026-06-26", thread_id: "old-chat" }],
      };
    });
    const api = await loadSettingsApi(fetchImpl);

    const result = await api.memoryRecent();

    expect(result.facts).toEqual(["User is building Vellum.", "User prefers concise answers."]);
    expect(result.entries).toEqual([
      { id: 1, text: "User prefers concise answers." },
      {
        id: "recent-9",
        kind: "recent",
        scope: "global",
        text: "Q: older chat\nA: remembered detail",
        created_at: "2026-06-26",
        updated_at: "2026-06-26",
        source_thread_id: "old-chat",
      },
    ]);
  });

  test("reads archived memories and can trigger dreaming", async () => {
    const fetchImpl = vi.fn(async (path, options) => {
      if (path === "/api/memory/saved") return { memories: [{ id: 1, text: "Saved memory." }] };
      if (path === "/api/memory/archived") return { memories: [{ id: 2, text: "Old memory." }] };
      if (path === "/api/memory/dreaming/run") {
        expect(options.method).toBe("POST");
        return { new_memories: [], global_summary: "Updated." };
      }
      throw new Error("unexpected path " + path);
    });
    const api = await loadSettingsApi(fetchImpl);

    await expect(api.memorySaved()).resolves.toEqual({ memories: [{ id: 1, text: "Saved memory." }], entries: [{ id: 1, text: "Saved memory." }] });
    await expect(api.memoryEntries()).resolves.toEqual({ memories: [{ id: 2, text: "Old memory." }], entries: [{ id: 2, text: "Old memory." }] });
    await expect(api.memoryDreamingRun()).resolves.toMatchObject({ global_summary: "Updated." });
  });

  test("creates and mutates saved memories through backend endpoints", async () => {
    const calls = [];
    const fetchImpl = vi.fn(async (path, options) => {
      calls.push([path, options && options.method, options && options.body]);
      if (path === "/api/memory") return { memory: { id: 7, text: "Remember this." } };
      if (path === "/api/memory/7/update") return { memory: { id: 7, text: "Updated." } };
      if (path === "/api/memory/7/pin") return { memory: { id: 7, pinned: true } };
      if (path === "/api/memory/7/archive") return { memory: { id: 7, status: "archived" } };
      if (path === "/api/memory/7/delete") return { ok: true };
      if (path === "/api/memory/import-conversations") return { indexed_turns: 3 };
      throw new Error("unexpected path " + path);
    });
    const api = await loadSettingsApi(fetchImpl);

    await expect(api.createMemory({ text: "Remember this." })).resolves.toMatchObject({ memory: { id: 7 } });
    await expect(api.updateMemory(7, { text: "Updated." })).resolves.toMatchObject({ memory: { text: "Updated." } });
    await expect(api.pinMemory(7, true)).resolves.toMatchObject({ memory: { pinned: true } });
    await expect(api.archiveMemory(7)).resolves.toMatchObject({ memory: { status: "archived" } });
    await expect(api.deleteMemory(7)).resolves.toEqual({ ok: true });
    await expect(api.memoryImportConversations()).resolves.toEqual({ indexed_turns: 3 });
    expect(calls).toEqual([
      ["/api/memory", "POST", JSON.stringify({ text: "Remember this." })],
      ["/api/memory/7/update", "POST", JSON.stringify({ text: "Updated." })],
      ["/api/memory/7/pin", "POST", JSON.stringify({ pinned: true })],
      ["/api/memory/7/archive", "POST", undefined],
      ["/api/memory/7/delete", "POST", undefined],
      ["/api/memory/import-conversations", "POST", undefined],
    ]);
  });

  test("reads and updates memory settings", async () => {
    const fetchImpl = vi.fn(async (path, options) => {
      if (path === "/api/memory/settings" && !options) {
        return { settings: { memory_enabled: true, dreaming_enabled: true } };
      }
      if (path === "/api/memory/settings") {
        expect(options.method).toBe("POST");
        expect(JSON.parse(options.body)).toEqual({ dreaming_enabled: false });
        return { settings: { memory_enabled: true, dreaming_enabled: false } };
      }
      throw new Error("unexpected path " + path);
    });
    const api = await loadSettingsApi(fetchImpl);

    await expect(api.memorySettings()).resolves.toEqual({ settings: { memory_enabled: true, dreaming_enabled: true } });
    await expect(api.updateMemorySettings({ dreaming_enabled: false })).resolves.toEqual({
      settings: { memory_enabled: true, dreaming_enabled: false },
    });
  });
});
