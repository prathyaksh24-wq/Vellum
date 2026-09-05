import { beforeEach, describe, expect, test, vi } from "vitest";

async function loadApi(request) {
  vi.resetModules();
  window.VellumApi = {
    client: {
      request,
      jsonOptions: (method, body) => ({ method, body: JSON.stringify(body) }),
    },
  };
  await import("../../../design/Velllum/uploads/api/app-actions.js");
  return window.VellumApi.appActions;
}

describe("Vellum App Action API adapter", () => {
  beforeEach(() => vi.restoreAllMocks());

  test("uses the catalog, dispatch, confirmation, and Undo endpoints", async () => {
    const request = vi.fn(async (_path, options) => options ? JSON.parse(options.body) : { actions: [] });
    const api = await loadApi(request);
    const action = { request_id: "r1", action_id: "ui.sidebar.set", arguments: { visible: false } };
    const context = { source: "ui", workspace_layout: { version: 1, revision: 0, surfaces: { sidebar: { visible: true } } } };

    await api.catalog();
    await api.dispatch(action, context);
    await api.confirm("confirm-1", action, context);
    await api.undo("undo-1", context);

    expect(request.mock.calls[0]).toEqual(["/api/app-actions/catalog"]);
    expect(request.mock.calls[1][0]).toBe("/api/app-actions/dispatch");
    expect(JSON.parse(request.mock.calls[1][1].body)).toEqual({ request: action, context });
    expect(request.mock.calls[2][0]).toBe("/api/app-actions/confirm");
    expect(JSON.parse(request.mock.calls[2][1].body)).toEqual({ token: "confirm-1", request: action, context });
    expect(request.mock.calls[3][0]).toBe("/api/app-actions/undo");
    expect(JSON.parse(request.mock.calls[3][1].body)).toEqual({ token: "undo-1", context });
  });
});
