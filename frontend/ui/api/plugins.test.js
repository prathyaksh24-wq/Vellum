import { beforeEach, describe, expect, test, vi } from "vitest";

async function loadPluginsApi(fetchImpl) {
  vi.resetModules();
  window.VellumApi = {
    client: {
      request: async (path, options) => fetchImpl(path, options),
      jsonOptions: (method, body) => ({ method, body }),
    },
  };
  await import("../../../design/Velllum/uploads/api/plugins.js");
  return window.VellumApi.plugins;
}

describe("Vellum plugins API adapter", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  test("reads backend capability discovery through a stable adapter method", async () => {
    const fetchImpl = vi.fn(async (path) => {
      expect(path).toBe("/api/capabilities");
      return {
        api_version: "v1",
        features: {
          spotify: { enabled: true, contract: "v1", endpoints: { status: "/api/plugins/spotify/status" } },
        },
      };
    });
    const api = await loadPluginsApi(fetchImpl);

    await expect(api.capabilities()).resolves.toMatchObject({
      api_version: "v1",
      features: {
        spotify: { enabled: true },
      },
    });
  });

  test("owns the YouTube OAuth and synchronization contract", async () => {
    const fetchImpl = vi.fn(async (path, options) => ({ path, options }));
    const api = await loadPluginsApi(fetchImpl);

    await api.youtubeStatus();
    await api.youtubeOAuthStart();
    await api.youtubeSync("snapshot-1");
    await api.youtubeDisconnect();

    expect(fetchImpl.mock.calls[0][0]).toBe("/api/plugins/youtube/status");
    expect(fetchImpl.mock.calls[1][0]).toBe("/api/plugins/youtube/oauth/start");
    expect(fetchImpl.mock.calls[2][0]).toBe("/api/plugins/youtube/sync");
    expect(fetchImpl.mock.calls[3]).toEqual([
      "/api/plugins/youtube/connection",
      { method: "DELETE" },
    ]);
  });
});
