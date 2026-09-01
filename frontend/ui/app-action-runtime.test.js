import { beforeEach, describe, expect, test, vi } from "vitest";

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: vi.fn((key) => values.has(key) ? values.get(key) : null),
    setItem: vi.fn((key, value) => values.set(key, String(value))),
    removeItem: vi.fn((key) => values.delete(key)),
    value: (key) => values.get(key),
  };
}

function receipt({ source, visible, previous, baseRevision, revision, status = "applied", undo = true }) {
  return {
    receipt_id: source + "-receipt",
    request_id: source + "-request",
    action_id: "ui.sidebar.set",
    action_version: "1",
    source,
    status,
    authorization: { decision: "allowed", access_class: "write", confirmation_required: false, agent_name: source === "nlp" ? "VellumAgent" : "VellumUI" },
    target: { kind: "ui_surface", id: "sidebar", revision },
    result: {
      changed: previous !== visible,
      visible,
      previous_visible: previous,
      workspace_layout_patch: {
        version: 1,
        base_revision: baseRevision,
        revision,
        surfaces: { sidebar: { visible } },
      },
    },
    undo: undo ? { token: source + "-undo", action_id: "ui.sidebar.set", arguments: { visible: previous }, target_revision: revision } : null,
    message: visible ? "Sidebar shown." : "Sidebar hidden.",
  };
}

async function loadRuntime() {
  vi.resetModules();
  window.VellumUI = {};
  window.VellumApi = { appActions: {} };
  await import("../../design/Velllum/uploads/components/app-action-runtime.js");
  return window.VellumUI.AppActions;
}

describe("Workspace Layout App Action adapter", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  test("visible control and NLP receipts produce the same persisted sidebar state", async () => {
    const AppActions = await loadRuntime();
    const uiStorage = memoryStorage();
    const nlpStorage = memoryStorage();
    const uiReceipt = receipt({ source: "ui", visible: false, previous: true, baseRevision: 0, revision: 1 });
    const nlpReceipt = receipt({ source: "nlp", visible: false, previous: true, baseRevision: 0, revision: 1 });
    const client = { dispatch: vi.fn(async () => uiReceipt) };
    const uiRuntime = AppActions.createWorkspaceLayoutRuntime({ storage: uiStorage, client, requestIdFactory: () => "ui-request" });
    const nlpRuntime = AppActions.createWorkspaceLayoutRuntime({ storage: nlpStorage, client: {} });

    const returned = await uiRuntime.dispatchSidebar(false, { conversationId: "chat-1" });
    nlpRuntime.applyReceipt(nlpReceipt);

    expect(returned).toBe(uiReceipt);
    expect(client.dispatch).toHaveBeenCalledWith(
      { request_id: "ui-request", action_id: "ui.sidebar.set", action_version: "1", arguments: { visible: false } },
      expect.objectContaining({ source: "ui", invocation_conversation_id: "chat-1" }),
    );
    expect(uiRuntime.snapshot()).toEqual(nlpRuntime.snapshot());
    expect(uiRuntime.snapshot()).toMatchObject({ revision: 1, surfaces: { sidebar: { visible: false } } });

    const reloaded = AppActions.createWorkspaceLayoutRuntime({ storage: uiStorage, client: {} });
    expect(reloaded.snapshot()).toMatchObject({ revision: 1, surfaces: { sidebar: { visible: false } } });
  });

  test("Undo applies the returned inverse receipt and restores visibility", async () => {
    const AppActions = await loadRuntime();
    const storage = memoryStorage();
    const hidden = receipt({ source: "ui", visible: false, previous: true, baseRevision: 0, revision: 1 });
    const restored = receipt({ source: "ui", visible: true, previous: false, baseRevision: 1, revision: 2, status: "undone", undo: false });
    const client = {
      dispatch: vi.fn(async () => hidden),
      undo: vi.fn(async () => restored),
    };
    const runtime = AppActions.createWorkspaceLayoutRuntime({ storage, client });

    const applied = await runtime.dispatchSidebar(false);
    await runtime.undo(applied);

    expect(client.undo).toHaveBeenCalledWith("ui-undo", expect.objectContaining({ source: "ui" }));
    expect(runtime.snapshot()).toMatchObject({ revision: 2, surfaces: { sidebar: { visible: true } } });
  });

  test("migrates the legacy sidebar preference into the versioned layout owner", async () => {
    const AppActions = await loadRuntime();
    const storage = memoryStorage({ "vellum-sb-open": "0" });

    const runtime = AppActions.createWorkspaceLayoutRuntime({ storage, client: {} });

    expect(runtime.snapshot().surfaces.sidebar.visible).toBe(false);
    expect(JSON.parse(storage.value(AppActions.STORAGE_KEY))).toMatchObject({ surfaces: { sidebar: { visible: false } } });
    expect(storage.removeItem).toHaveBeenCalledWith("vellum-sb-open");
  });
});
