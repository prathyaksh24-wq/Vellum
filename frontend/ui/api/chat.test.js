import { beforeEach, describe, expect, test, vi } from "vitest";

function sseStream(chunks) {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
}

async function loadChatApi(fetchImpl) {
  vi.resetModules();
  window.VellumApi = {
    client: {
      backendBase: () => "http://127.0.0.1:8000",
      jsonOptions: (method, body, signal) => ({
        method,
        signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    },
  };
  globalThis.fetch = fetchImpl;
  await import("./chat.js");
  return window.VellumApi.chat;
}

describe("Vellum default chat stream trace", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  test("emits visible activity trace updates from semantic SSE events", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      body: sseStream([
        'event: response.created\ndata: {"thread_id":"t1","created_at":"2026-06-17T07:00:00Z"}\n\n',
        'event: response.output_item.added\ndata: {"item":{"id":"i1","type":"subagent_call","name":"SportsAgent","label":"Routed to SportsAgent","detail":"next f1 race","status":"in_progress"}}\n\n',
        'event: response.output_item.added\ndata: {"item":{"id":"i2","type":"source","source":{"url":"https://www.formula1.com/en/racing/2026","title":"F1 calendar","domain":"formula1.com","snippet":"Next round is Austria."}}}\n\n',
        'event: response.output_text.delta\ndata: {"delta":"Austria"}\n\n',
        'event: response.completed\ndata: {"response":{"thread_id":"t1","output_text":"Austria","tools":["sports_agent"],"sources":[{"url":"https://www.formula1.com/en/racing/2026","domain":"formula1.com"}]}}\n\n',
      ]),
    }));
    const traces = [];
    const api = await loadChatApi(fetchImpl);

    await api.stream(
      { message: "next f1 race", thread_id: "t1" },
      { trace: (trace) => traces.push(trace) },
    );

    expect(traces[0]).toMatchObject({ status: "thinking", steps: [{ label: "Thinking" }] });
    expect(traces.some((trace) => trace.steps.some((step) => step.label === "Routed to SportsAgent"))).toBe(true);
    expect(traces.some((trace) => trace.sources.some((source) => source.domain === "formula1.com"))).toBe(true);
    expect(traces.at(-1)).toMatchObject({
      status: "done",
      elapsedSeconds: expect.any(Number),
      sources: [{ url: "https://www.formula1.com/en/racing/2026", domain: "formula1.com" }],
      tools: ["sports_agent"],
    });
  });

  test("keeps final trace done when a late item completion arrives after response.completed", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      body: sseStream([
        'event: response.created\ndata: {"thread_id":"t1"}\n\n',
        'event: response.output_item.added\ndata: {"item":{"id":"tool-1","type":"tool_call","name":"web_search","label":"Searching web","status":"in_progress"}}\n\n',
        'event: response.output_text.delta\ndata: {"delta":"Answer"}\n\n',
        'event: response.completed\ndata: {"response":{"thread_id":"t1","output_text":"Answer","tools":["web_search"],"sources":[]}}\n\n',
        'event: response.output_item.done\ndata: {"item":{"id":"tool-1","type":"tool_call","name":"web_search","status":"completed"}}\n\n',
      ]),
    }));
    const traces = [];
    const done = [];
    const api = await loadChatApi(fetchImpl);

    await api.stream(
      { message: "search", thread_id: "t1" },
      {
        trace: (trace) => traces.push(trace),
        done: (final) => done.push(final),
      },
    );

    expect(done).toHaveLength(1);
    expect(traces.at(-1).status).toBe("done");
    expect(traces.at(-1).completedAt).toEqual(expect.any(Number));
  });

  test("emits activity updates for streamed function call arguments", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      body: sseStream([
        'event: response.created\ndata: {"thread_id":"t1"}\n\n',
        'event: response.output_item.added\ndata: {"item":{"id":"fn-1","type":"function_call","name":"web_search","label":"Preparing web_search","status":"in_progress","arguments":""}}\n\n',
        'event: response.function_call_arguments.delta\ndata: {"item_id":"fn-1","delta":"{\\"query\\":"}\n\n',
        'event: response.function_call_arguments.delta\ndata: {"item_id":"fn-1","delta":"\\"f1\\"}"}\n\n',
        'event: response.function_call_arguments.done\ndata: {"item_id":"fn-1","arguments":"{\\"query\\":\\"f1\\"}"}\n\n',
        'event: response.completed\ndata: {"response":{"thread_id":"t1","output_text":"Done","tools":["web_search"],"sources":[]}}\n\n',
      ]),
    }));
    const activities = [];
    const api = await loadChatApi(fetchImpl);

    await api.stream(
      { message: "search", thread_id: "t1" },
      { activity: (items) => activities.push(items) },
    );

    expect(activities.some((items) => items.some((item) => item.id === "fn-1" && item.detail.includes('"query"')))).toBe(true);
    expect(activities.at(-1).some((item) => item.id === "fn-1" && item.status === "completed")).toBe(true);
  });
});
