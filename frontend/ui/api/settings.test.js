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
  await import("./settings.js");
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
      };
    });
    const api = await loadSettingsApi(fetchImpl);

    const result = await api.memoryRecent();

    expect(result.facts).toEqual(["User is building Vellum.", "User prefers concise answers."]);
    expect(result.entries).toEqual([{ id: 1, text: "User prefers concise answers." }]);
  });

  test("reads archived memories and can trigger dreaming", async () => {
    const fetchImpl = vi.fn(async (path, options) => {
      if (path === "/api/memory/archived") return { memories: [{ id: 2, text: "Old memory." }] };
      if (path === "/api/memory/dreaming/run") {
        expect(options.method).toBe("POST");
        return { new_memories: [], global_summary: "Updated." };
      }
      throw new Error("unexpected path " + path);
    });
    const api = await loadSettingsApi(fetchImpl);

    await expect(api.memoryEntries()).resolves.toEqual({ entries: [{ id: 2, text: "Old memory." }] });
    await expect(api.memoryDreamingRun()).resolves.toMatchObject({ global_summary: "Updated." });
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
