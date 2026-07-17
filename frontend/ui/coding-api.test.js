import { describe, expect, test, vi } from "vitest";
import { createCodingApi, parseSseBlocks } from "./coding-api.js";

describe("parseSseBlocks", () => {
  test("parses named SSE events", () => {
    const blocks = parseSseBlocks('event: assistant_final\ndata: {"payload":{"text":"ok"}}\n\n');
    expect(blocks).toEqual([{ event: "assistant_final", data: { payload: { text: "ok" } } }]);
  });

  test("parses CRLF blocks and multiline data", () => {
    const blocks = parseSseBlocks('event: assistant_delta\r\ndata: {"payload":\r\ndata: {"text":"ok"}}\r\n\r\n');
    expect(blocks).toEqual([{ event: "assistant_delta", data: { payload: { text: "ok" } } }]);
  });
});

describe("createCodingApi", () => {
  test("loads provider health", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      json: async () => ({ providers: [{ provider: "codex", available: true }] }),
    }));
    const api = createCodingApi({ apiBase: "http://127.0.0.1:8000", fetchImpl });

    const health = await api.health();

    expect(health.providers[0].provider).toBe("codex");
    expect(fetchImpl).toHaveBeenCalledWith("http://127.0.0.1:8000/api/coding/health");
  });

  test("streams turn events across chunk boundaries", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('event: assistant_delta\ndata: {"payload":{"text":"he'));
        controller.enqueue(encoder.encode('llo"}}\n\n'));
        controller.close();
      },
    });
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      body: stream,
    }));
    const events = [];
    const api = createCodingApi({ apiBase: "http://127.0.0.1:8000", fetchImpl });

    await api.runTurn("code 1", "hello", (event) => events.push(event));

    expect(events).toEqual([{ event: "assistant_delta", data: { payload: { text: "hello" } } }]);
    expect(fetchImpl).toHaveBeenCalledWith("http://127.0.0.1:8000/api/coding/sessions/code%201/turns/stream", {
      method: "POST",
      signal: undefined,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: "hello", max_runtime_seconds: 1800, max_provider_events: 10000 }),
    });
  });

  test("supports replay, file reads, and provider stop", async () => {
    const fetchImpl = vi.fn(async () => ({ ok: true, json: async () => ({ ok: true }) }));
    const api = createCodingApi({ fetchImpl });

    await api.events("code 1", 17);
    await api.projectFile("D:\\Vellum", "src/app.py");
    await api.stop("code 1");

    expect(fetchImpl.mock.calls[0][0]).toContain("code%201/events?after_sequence=17");
    expect(fetchImpl.mock.calls[1][0]).toContain("root=D%3A%5CVellum&path=src%2Fapp.py");
    expect(fetchImpl.mock.calls[2]).toEqual([
      "http://127.0.0.1:8000/api/coding/sessions/code%201/stop",
      { method: "POST" },
    ]);
  });

  test("closes an isolated coding session with an explicit discard decision", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      json: async () => ({ id: "code 1", status: "closed" }),
    }));
    const api = createCodingApi({ fetchImpl });

    await api.close("code 1", { discardChanges: true });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/coding/sessions/code%201/close",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ discard_changes: true }),
      }),
    );
  });

  test("parses text fallback when response body is unavailable", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      body: null,
      text: async () => 'event: assistant_final\ndata: {"payload":{"text":"done"}}\n\n',
    }));
    const events = [];
    const api = createCodingApi({ fetchImpl });

    await api.runTurn("code_1", "hello", (event) => events.push(event));

    expect(events).toEqual([{ event: "assistant_final", data: { payload: { text: "done" } } }]);
  });

  test("throws backend detail for failed stream requests", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ detail: "Codex SDK is not installed." }),
    }));
    const api = createCodingApi({ fetchImpl });

    await expect(api.runTurn("code_1", "hello", () => {})).rejects.toThrow("Codex SDK is not installed.");
  });
});
