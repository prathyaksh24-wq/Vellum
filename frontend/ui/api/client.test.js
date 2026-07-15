import { beforeEach, describe, expect, test, vi } from "vitest";

async function loadClient(search = "") {
  vi.resetModules();
  window.VellumApi = {};
  window.history.replaceState({}, "", "/" + search);
  localStorage.clear();
  await import("../../../design/Velllum/uploads/api/client.js");
  return window.VellumApi.client;
}

describe("Vellum API client backend selection", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    localStorage.clear();
  });

  test("accepts an explicit loopback backend for isolated local previews", async () => {
    const client = await loadClient("?backend=http%3A%2F%2F127.0.0.1%3A8015");
    expect(client.backendBase()).toBe("http://127.0.0.1:8015");
  });

  test("ignores non-loopback query overrides", async () => {
    const client = await loadClient("?backend=https%3A%2F%2Fexample.com");
    expect(client.backendBase()).toBe("http://127.0.0.1:8000");
  });
});
