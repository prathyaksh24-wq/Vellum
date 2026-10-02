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

function surfaceReceipt({
  source = "nlp",
  reference,
  presentation,
  baseRevision,
  revision,
  persistence = "device",
  replace = false,
  surfaces,
  actionId = "ui.surface.configure",
}) {
  const patchSurfaces = surfaces || { [reference]: presentation };
  return {
    receipt_id: source + "-receipt-" + revision,
    request_id: source + "-request-" + revision,
    action_id: actionId,
    action_version: "1",
    source,
    status: "applied",
    authorization: { decision: "allowed", access_class: "write", confirmation_required: false, agent_name: source === "nlp" ? "VellumAgent" : "VellumUI" },
    target: { kind: replace ? "workspace_layout" : "ui_surface", id: replace ? "workspace-layout" : reference, revision },
    result: {
      changed: true,
      target_reference: replace ? "workspace-layout" : reference,
      workspace_layout_patch: {
        version: 1,
        base_revision: baseRevision,
        revision,
        persistence,
        replace,
        surfaces: patchSurfaces,
      },
    },
    message: "Interface updated.",
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
    document.body.innerHTML = "";
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
    expect(client.dispatch.mock.calls[0][1].adaptive_learning_signal).toBe(false);

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

  test("persists registered surface changes across runtime reloads", async () => {
    const AppActions = await loadRuntime();
    const storage = memoryStorage();
    const runtime = AppActions.createWorkspaceLayoutRuntime({ storage, client: {} });

    runtime.applyReceipt(surfaceReceipt({
      reference: "workspace",
      presentation: { visible: true, location: "application", properties: { theme: "light" } },
      baseRevision: 0,
      revision: 1,
    }));
    runtime.applyReceipt(surfaceReceipt({
      reference: "composer.send",
      presentation: { visible: true, location: "composer-action", properties: { label: "Run", size: "large" } },
      baseRevision: 1,
      revision: 2,
    }));

    const reloaded = AppActions.createWorkspaceLayoutRuntime({ storage, client: {} });
    expect(reloaded.snapshot()).toMatchObject({
      revision: 2,
      surfaces: {
        workspace: { properties: { theme: "light" } },
        "composer.send": { properties: { label: "Run", size: "large" } },
      },
    });
  });

  test("keeps explicit session changes out of device storage", async () => {
    const AppActions = await loadRuntime();
    const storage = memoryStorage();
    const runtime = AppActions.createWorkspaceLayoutRuntime({ storage, client: {} });

    runtime.applyReceipt(surfaceReceipt({
      reference: "settings",
      presentation: { visible: true, location: "overlay", properties: {} },
      baseRevision: 0,
      revision: 1,
      persistence: "session",
    }));

    expect(runtime.snapshot().surfaces.settings.visible).toBe(true);
    expect(JSON.parse(storage.value(AppActions.STORAGE_KEY)).surfaces.settings.visible).toBe(false);
    const reloaded = AppActions.createWorkspaceLayoutRuntime({ storage, client: {} });
    expect(reloaded.snapshot().surfaces.settings.visible).toBe(false);
  });

  test("reset replaces device state with defaults and clears session overrides", async () => {
    const AppActions = await loadRuntime();
    const storage = memoryStorage();
    const runtime = AppActions.createWorkspaceLayoutRuntime({ storage, client: {} });
    runtime.applyReceipt(surfaceReceipt({
      reference: "settings",
      presentation: { visible: true, location: "overlay", properties: {} },
      baseRevision: 0,
      revision: 1,
      persistence: "session",
    }));

    runtime.applyReceipt(surfaceReceipt({
      baseRevision: 1,
      revision: 2,
      replace: true,
      actionId: "ui.workspace.reset",
      surfaces: AppActions.SURFACE_DEFAULTS,
    }));

    const expected = {
      version: 1,
      revision: 2,
      surfaces: AppActions.SURFACE_DEFAULTS,
      adaptive_ui: { revision: 0, rules: [], signals: [], suppressions: [], last_rule_id: "" },
    };
    expect(runtime.snapshot()).toEqual(expected);
    const reloaded = AppActions.createWorkspaceLayoutRuntime({ storage, client: {} });
    expect(reloaded.snapshot()).toEqual(expected);
  });

  test("migrates the legacy theme preference into the workspace surface", async () => {
    const AppActions = await loadRuntime();
    const storage = memoryStorage({ "vellum-theme": "light" });

    const runtime = AppActions.createWorkspaceLayoutRuntime({ storage, client: {} });

    expect(runtime.snapshot().surfaces.workspace.properties.theme).toBe("light");
    expect(storage.removeItem).toHaveBeenCalledWith("vellum-theme");
  });

  test("dispatches visible controls through the generic surface action", async () => {
    const AppActions = await loadRuntime();
    const next = surfaceReceipt({
      source: "ui",
      reference: "composer",
      presentation: { visible: true, location: "bottom", properties: { size: "large" } },
      baseRevision: 0,
      revision: 1,
    });
    const client = { dispatch: vi.fn(async () => next) };
    const runtime = AppActions.createWorkspaceLayoutRuntime({ storage: memoryStorage(), client, requestIdFactory: () => "surface-request" });

    await runtime.dispatchSurface("composer", { properties: { size: "large" } }, { conversationId: "chat-1" });

    expect(client.dispatch).toHaveBeenCalledWith(
      {
        request_id: "surface-request",
        action_id: "ui.surface.configure",
        action_version: "1",
        arguments: { reference: "composer", properties: { size: "large" } },
      },
      expect.objectContaining({ source: "ui", invocation_conversation_id: "chat-1" }),
    );
    expect(runtime.snapshot().surfaces.composer.properties.size).toBe("large");
  });

  test("adds focused, selected, and visible UI references to action context", async () => {
    const AppActions = await loadRuntime();
    document.body.innerHTML = `
      <main data-ui-reference="workspace"></main>
      <textarea data-ui-reference="composer"></textarea>
      <button data-ui-reference="composer.send" data-ui-selected="true">Send</button>
      <aside data-ui-reference="right-panel" aria-hidden="true"></aside>
    `;
    document.querySelector("textarea").focus();
    const runtime = AppActions.createWorkspaceLayoutRuntime({ storage: memoryStorage(), client: {} });

    const context = runtime.context("nlp", "chat-1");

    expect(context.focused_ui_reference).toBe("composer");
    expect(context.selected_ui_reference).toBe("composer.send");
    expect(context.visible_ui_references).toEqual(expect.arrayContaining(["workspace", "composer", "composer.send"]));
    expect(context.visible_ui_references).not.toContain("right-panel");
  });

  test("marks deliberate presentation controls as learning signals", async () => {
    const AppActions = await loadRuntime();
    const client = { dispatch: vi.fn(async () => receipt({
      source: "ui", visible: false, previous: true, baseRevision: 0, revision: 1,
    })) };
    const runtime = AppActions.createWorkspaceLayoutRuntime({ storage: memoryStorage(), client });

    await runtime.dispatchSidebar(false, { learn: true });

    expect(client.dispatch.mock.calls[0][1].adaptive_learning_signal).toBe(true);
  });

  test("persists learned rules and applies only in the matching live context", async () => {
    const AppActions = await loadRuntime();
    const storage = memoryStorage();
    let projectId = "project-other";
    const rule = {
      id: "adaptive_project", signature: "sig-hidden", arguments: { reference: "sidebar", visible: false },
      scope: "project", scope_id: "project-match", origin: "inferred", evidence_count: 3,
      enabled: true, suppressed: false, explained: false,
    };
    const initial = { revision: 1, rules: [rule], signals: [], suppressions: [], last_rule_id: "" };
    const applied = receipt({ source: "ui", visible: false, previous: true, baseRevision: 0, revision: 1 });
    applied.action_id = "ui.adaptive.apply";
    applied.result.adaptive_ui_patch = {
      base_revision: 1, revision: 2,
      state: { ...initial, revision: 2, last_rule_id: rule.id, rules: [{ ...rule, explained: true }] },
    };
    applied.result.adaptive_rule = { id: rule.id, first_use: true, explanation: "Learned from 3 changes." };
    const client = { dispatch: vi.fn(async () => applied) };
    const runtime = AppActions.createWorkspaceLayoutRuntime({ storage, client, contextResolver: () => ({ project_id: projectId }) });
    runtime.applyReceipt({ status: "applied", result: { adaptive_ui_patch: { base_revision: 0, revision: 1, state: initial } } });

    await runtime.maybeApply();
    expect(client.dispatch).not.toHaveBeenCalled();

    projectId = "project-match";
    const onReceipt = vi.fn();
    await runtime.maybeApply({ onReceipt });
    expect(client.dispatch).toHaveBeenCalledWith(
      expect.objectContaining({ action_id: "ui.adaptive.apply", arguments: { rule_id: rule.id } }),
      expect.objectContaining({ project_id: "project-match" }),
    );
    expect(onReceipt).toHaveBeenCalledWith(applied);
    expect(runtime.snapshot().surfaces.sidebar.visible).toBe(false);
    expect(runtime.snapshot().adaptive_ui.rules[0].explained).toBe(true);
    const reloaded = AppActions.createWorkspaceLayoutRuntime({ storage, client: {} });
    expect(reloaded.snapshot().adaptive_ui).toEqual(runtime.snapshot().adaptive_ui);
    await runtime.maybeApply();
    expect(client.dispatch).toHaveBeenCalledTimes(1);
  });

  test("does not override a temporary presentation choice with an adaptive rule", async () => {
    const AppActions = await loadRuntime();
    const client = { dispatch: vi.fn() };
    const runtime = AppActions.createWorkspaceLayoutRuntime({ storage: memoryStorage(), client, windowId: "window-a" });
    const rule = {
      id: "adaptive_window", signature: "sig-hidden", arguments: { reference: "sidebar", visible: false },
      scope: "window", scope_id: "window-a", origin: "inferred", evidence_count: 3,
      enabled: true, suppressed: false, explained: false,
    };
    runtime.applyReceipt({ status: "applied", result: { adaptive_ui_patch: {
      base_revision: 0, revision: 1,
      state: { revision: 1, rules: [rule], signals: [], suppressions: [], last_rule_id: "" },
    } } });
    runtime.applyReceipt(surfaceReceipt({
      reference: "sidebar", presentation: { visible: true, location: "left", properties: {} },
      baseRevision: 0, revision: 1, persistence: "session",
    }));

    await runtime.maybeApply();

    expect(client.dispatch).not.toHaveBeenCalled();
  });

  test("rejects stale adaptive rule receipts", async () => {
    const AppActions = await loadRuntime();
    const runtime = AppActions.createWorkspaceLayoutRuntime({ storage: memoryStorage(), client: {} });
    const state = { revision: 1, rules: [], signals: [], suppressions: [], last_rule_id: "" };
    runtime.applyReceipt({ status: "applied", result: { adaptive_ui_patch: { base_revision: 0, revision: 1, state } } });

    expect(() => runtime.applyReceipt({ status: "applied", result: {
      adaptive_ui_patch: { base_revision: 0, revision: 2, state: { ...state, revision: 2 } },
    } })).toThrow("STALE_ADAPTIVE_UI_RECEIPT");
  });
});

describe("Conversation session-control receipts", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.VellumUI = {};
  });

  test("UI dispatch and NLP receipts apply the same client state patch", async () => {
    const AppActions = await loadRuntime();
    const applied = [];
    const uiReceipt = {
      request_id: "ui-model",
      action_id: "model.select",
      status: "applied",
      result: { session_control_patch: { model_id: "google/gemma-4-31b-it" } },
      target: { kind: "conversation_runtime", id: "chat-1" },
    };
    const client = { dispatch: vi.fn(async () => uiReceipt) };
    const runtime = AppActions.createConversationActionRuntime({
      client,
      requestIdFactory: () => "ui-model",
      applySessionControl: (patch, receipt) => applied.push({ patch, target: receipt.target.id }),
    });

    await runtime.dispatch("model.select", { model_id: "google/gemma-4-31b-it" }, { conversationId: "chat-1" });
    runtime.applyReceipt({
      ...uiReceipt,
      request_id: "nlp-memory",
      action_id: "memory.conversation.set",
      source: "nlp",
      result: { session_control_patch: { store_to_memory: false } },
    });

    expect(client.dispatch).toHaveBeenCalledWith(
      expect.objectContaining({ action_id: "model.select", arguments: { model_id: "google/gemma-4-31b-it" } }),
      expect.objectContaining({ source: "ui", invocation_conversation_id: "chat-1" }),
    );
    expect(applied).toEqual([
      { patch: { model_id: "google/gemma-4-31b-it" }, target: "chat-1" },
      { patch: { store_to_memory: false }, target: "chat-1" },
    ]);
  });
});

describe("Device Settings App Action adapter", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  test("migrates existing device preferences into one revisioned owner", async () => {
    const AppActions = await loadRuntime();
    const storage = memoryStorage({
      "vellum-background": "aurora",
      "vellum-accent": "blue-eclipse",
      "vellum-dock-position": "left",
      "vellum-dock-locked": "1",
      "vellum-pers": JSON.stringify({ warm: "more", memory: false }),
    });

    const runtime = AppActions.createDeviceSettingsRuntime({ storage, client: {} });

    expect(runtime.snapshot()).toMatchObject({
      version: 1,
      revision: 0,
      values: {
        background: "aurora",
        accent: "blue-eclipse",
        dock_position: "left",
        dock_locked: true,
        personalization: { warm: "more" },
      },
    });
    expect(runtime.snapshot().values.personalization).not.toHaveProperty("memory");
    expect(storage.value("vellum-background")).toBeUndefined();
    expect(JSON.parse(storage.value(AppActions.DEVICE_SETTINGS_STORAGE_KEY)).values.accent).toBe("blue-eclipse");
  });

  test("visible controls and NLP receipts converge on the same persisted state", async () => {
    const AppActions = await loadRuntime();
    const storage = memoryStorage();
    const applied = {
      request_id: "device-1",
      action_id: "settings.device.update",
      status: "applied",
      result: {
        changed: true,
        device_settings_patch: {
          version: 1,
          base_revision: 0,
          revision: 1,
          values: { accent: "matrix", personalization: { webSearch: false } },
        },
      },
    };
    const client = { dispatch: vi.fn(async () => applied) };
    const runtime = AppActions.createDeviceSettingsRuntime({ storage, client, requestIdFactory: () => "device-1" });

    await runtime.dispatch({ accent: "matrix", personalization: { webSearch: false } }, { conversationId: "chat-1" });

    expect(client.dispatch).toHaveBeenCalledWith(
      {
        request_id: "device-1",
        action_id: "settings.device.update",
        action_version: "1",
        arguments: { patch: { accent: "matrix", personalization: { webSearch: false } } },
      },
      expect.objectContaining({
        source: "ui",
        invocation_conversation_id: "chat-1",
        device_settings: expect.objectContaining({ revision: 0 }),
      }),
    );
    expect(runtime.snapshot()).toMatchObject({
      revision: 1,
      values: { accent: "matrix", personalization: { webSearch: false } },
    });
    const reloaded = AppActions.createDeviceSettingsRuntime({ storage, client: {} });
    expect(reloaded.snapshot()).toEqual(runtime.snapshot());
  });

  test("rejects stale device receipts instead of overwriting newer choices", async () => {
    const AppActions = await loadRuntime();
    const runtime = AppActions.createDeviceSettingsRuntime({ storage: memoryStorage(), client: {} });

    expect(() => runtime.applyReceipt({
      status: "applied",
      result: { device_settings_patch: { version: 1, base_revision: 7, revision: 8, values: { accent: "matrix" } } },
    })).toThrow("STALE_DEVICE_SETTINGS_RECEIPT");
    expect(runtime.snapshot().values.accent).toBe("default");
  });

  test("keeps the previous device state when an action fails", async () => {
    const AppActions = await loadRuntime();
    const client = {
      dispatch: vi.fn(async () => ({
        action_id: "settings.device.update",
        status: "failed",
        error_code: "INVALID_ACTION_ARGUMENTS",
        result: {},
      })),
    };
    const runtime = AppActions.createDeviceSettingsRuntime({ storage: memoryStorage(), client });

    const receipt = await runtime.dispatch({ accent: "not-a-palette" });

    expect(receipt.status).toBe("failed");
    expect(runtime.snapshot()).toMatchObject({ revision: 0, values: { accent: "default" } });
  });
});
