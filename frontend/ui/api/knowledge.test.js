import { beforeEach, describe, expect, test, vi } from "vitest";

async function loadKnowledgeApi(requestImpl) {
  vi.resetModules();
  window.VellumApi = {
    client: {
      request: requestImpl,
      jsonOptions: (method, body) => ({ method, body: JSON.stringify(body) }),
    },
  };
  await import("../../../design/Velllum/uploads/api/knowledge.js");
  return window.VellumApi.knowledge;
}

describe("Vellum personal intelligence API adapter", () => {
  beforeEach(() => vi.restoreAllMocks());

  test("keeps Personal Intelligence behind the existing knowledge namespace", async () => {
    const request = vi.fn(async () => ({ ready: true }));
    const api = await loadKnowledgeApi(request);

    await api.coreStatus();
    await api.coreSources("x_post", 20, 0);
    await api.corePreferences("youtube_channel", 10);
    await api.ingestionJobs("youtube", 5);
    await api.syncCursors("youtube", 5);
    await api.coreAnnotations("src-1", true, 20);

    expect(request).toHaveBeenNthCalledWith(1, "/api/knowledge/core/status");
    expect(request).toHaveBeenNthCalledWith(2, "/api/knowledge/core/sources?kind=x_post&limit=20&offset=0");
    expect(request).toHaveBeenNthCalledWith(3, "/api/knowledge/core/preferences?category=youtube_channel&limit=10");
    expect(request).toHaveBeenNthCalledWith(4, "/api/knowledge/core/ingestion-jobs?connector=youtube&limit=5");
    expect(request).toHaveBeenNthCalledWith(5, "/api/knowledge/core/sync-cursors?connector=youtube&limit=5");
    expect(request).toHaveBeenNthCalledWith(6, "/api/knowledge/core/annotations?target_id=src-1&requires_review=true&limit=20");
  });

  test("bootstrap preview cannot accidentally request an applying migration", async () => {
    const request = vi.fn(async () => ({ mode: "preview" }));
    const api = await loadKnowledgeApi(request);

    await api.bootstrapPreview({ conversations: true, apply: true });

    const [, options] = request.mock.calls[0];
    expect(request.mock.calls[0][0]).toBe("/api/knowledge/core/bootstrap");
    expect(JSON.parse(options.body)).toMatchObject({ conversations: true, apply: false });
  });
});
