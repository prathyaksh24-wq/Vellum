import { beforeEach, describe, expect, test, vi } from "vitest";

async function loadPluginsApi(fetchImpl) {
  vi.resetModules();
  window.VellumApi = {
    client: {
      request: async (path, options) => fetchImpl(path, options),
    },
  };
  await import("./plugins.js");
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
});
