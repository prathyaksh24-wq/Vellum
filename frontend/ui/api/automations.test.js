import { beforeEach, describe, expect, test, vi } from "vitest";

async function loadAutomationsApi(fetchImpl) {
  vi.resetModules();
  window.VellumApi = {
    client: {
      request: vi.fn(async (path, options) => {
        fetchImpl(path, options);
        return { ok: true };
      }),
      jsonOptions: (method, body) => ({ method, body: body === undefined ? undefined : JSON.stringify(body) }),
    },
  };
  await import("../../../design/Velllum/uploads/api/automations.js");
  return window.VellumApi.automations;
}

describe("Vellum automations API client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  test("lists automations", async () => {
    const calls = [];
    const api = await loadAutomationsApi((path, options) => calls.push({ path, options }));
    await api.list();
    expect(calls[0].path).toBe("/api/automations");
    expect(calls[0].options).toBeUndefined();
  });

  test("creates an automation with a JSON body", async () => {
    const calls = [];
    const api = await loadAutomationsApi((path, options) => calls.push({ path, options }));
    const payload = { name: "Morning", instructions: "Summarize", schedule: "0 9 * * *" };
    await api.create(payload);
    expect(calls[0].path).toBe("/api/automations");
    expect(calls[0].options.method).toBe("POST");
    expect(JSON.parse(calls[0].options.body)).toEqual(payload);
  });

  test("updates an automation by id", async () => {
    const calls = [];
    const api = await loadAutomationsApi((path, options) => calls.push({ path, options }));
    await api.update("automation-abc", { state: "paused" });
    expect(calls[0].path).toBe("/api/automations/automation-abc");
    expect(calls[0].options.method).toBe("PATCH");
    expect(JSON.parse(calls[0].options.body)).toEqual({ state: "paused" });
  });

  test("removes an automation by id", async () => {
    const calls = [];
    const api = await loadAutomationsApi((path, options) => calls.push({ path, options }));
    await api.remove("automation-abc");
    expect(calls[0].path).toBe("/api/automations/automation-abc");
    expect(calls[0].options.method).toBe("DELETE");
  });

  test("runs an automation now", async () => {
    const calls = [];
    const api = await loadAutomationsApi((path, options) => calls.push({ path, options }));
    await api.run("automation-abc");
    expect(calls[0].path).toBe("/api/automations/automation-abc/run");
    expect(calls[0].options.method).toBe("POST");
  });

  test("fetches run history for an automation", async () => {
    const calls = [];
    const api = await loadAutomationsApi((path) => calls.push(path));
    await api.runs("automation-abc");
    expect(calls[0]).toBe("/api/automations/automation-abc/runs");
  });

  test("fetches the chat-guided creation prompt", async () => {
    const calls = [];
    const api = await loadAutomationsApi((path) => calls.push(path));
    await api.createPrompt();
    expect(calls[0]).toBe("/api/automations/create-prompt");
  });

  test("URL-encodes ids with special characters", async () => {
    const calls = [];
    const api = await loadAutomationsApi((path) => calls.push(path));
    await api.update("automation a/b", { name: "X" });
    expect(calls[0]).toBe("/api/automations/automation%20a%2Fb");
  });
});
