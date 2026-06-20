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

    expect(["Thinking", "One sec", "Checking context", "Working through it", "Cooking up your answer"]).toContain(traces[0].steps[0].label);
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

  test("routes agent activity lifecycle events to activity trace without changing text deltas", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      body: sseStream([
        'event: response.created\ndata: {"thread_id":"t1"}\n\n',
        'event: agent.activity\ndata: {"activity":{"id":"a1","type":"thinking_started","label":"Thinking...","status":"in_progress"}}\n\n',
        'event: agent.activity\ndata: {"activity":{"id":"a2","type":"tool_call_started","name":"web_search","label":"Using web_search...","detail":"f1 calendar","status":"in_progress"}}\n\n',
        'event: agent.activity\ndata: {"activity":{"id":"s1","type":"source_reading","label":"Reading Formula 1...","status":"in_progress","source":{"url":"https://www.formula1.com/en/racing/2026","domain":"formula1.com","provider_label":"Formula 1"}}}\n\n',
        'event: agent.activity\ndata: {"activity":{"id":"a3","type":"final_answer_started","label":"Writing answer...","status":"in_progress"}}\n\n',
        'event: response.output_text.delta\ndata: {"delta":"Austria"}\n\n',
        'event: response.completed\ndata: {"response":{"thread_id":"t1","output_text":"Austria","tools":["web_search"],"sources":[{"url":"https://www.formula1.com/en/racing/2026","domain":"formula1.com"}]}}\n\n',
      ]),
    }));
    const activities = [];
    const traces = [];
    const deltas = [];
    const api = await loadChatApi(fetchImpl);

    await api.stream(
      { message: "next f1 race", thread_id: "t1" },
      {
        activity: (items) => activities.push(items),
        trace: (trace) => traces.push(trace),
        delta: (text, delta) => deltas.push({ text, delta }),
      },
    );

    expect(deltas).toEqual([{ text: "Austria", delta: "Austria" }]);
    expect(activities.some((items) => items.some((item) => item.type === "tool_call_started" && item.label === "Searching the web"))).toBe(true);
    expect(activities.some((items) => items.some((item) => item.type === "source_reading" && item.source.domain === "formula1.com"))).toBe(true);
    expect(traces.some((trace) => trace.steps.some((step) => step.label === "Writing answer"))).toBe(true);
  });

  test("normalizes sub-agent, SerpAPI, notes, and Obsidian activity labels", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      body: sseStream([
        'event: response.created\ndata: {"thread_id":"t1"}\n\n',
        'event: agent.activity\ndata: {"activity":{"id":"yt","type":"sub_agent_started","name":"YoutubeAgent","status":"in_progress"}}\n\n',
        'event: agent.activity\ndata: {"activity":{"id":"x","type":"sub_agent_started","name":"XAgent","status":"in_progress"}}\n\n',
        'event: agent.activity\ndata: {"activity":{"id":"serp","type":"tool_call_started","name":"serpapi","status":"in_progress"}}\n\n',
        'event: agent.activity\ndata: {"activity":{"id":"notes","type":"tool_call_started","name":"search_my_notes","status":"in_progress"}}\n\n',
        'event: agent.activity\ndata: {"activity":{"id":"obs","type":"tool_call_started","name":"obsidian_api","status":"in_progress"}}\n\n',
        'event: response.completed\ndata: {"response":{"thread_id":"t1","output_text":"Done","tools":["youtube_agent","x_agent","serpapi","search_my_notes","obsidian_api"],"sources":[]}}\n\n',
      ]),
    }));
    const activities = [];
    const api = await loadChatApi(fetchImpl);

    await api.stream(
      { message: "test labels", thread_id: "t1" },
      { activity: (items) => activities.push(items) },
    );

    const labels = activities.flat().map((item) => item.label);
    expect(labels).toContain("Calling YouTube Agent");
    expect(labels).toContain("Calling X Agent");
    expect(labels).toContain("Searching with SerpAPI");
    expect(labels).toContain("Searching your notes");
    expect(labels).toContain("Reading Obsidian");
  });
});
