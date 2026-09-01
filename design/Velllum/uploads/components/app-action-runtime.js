(function () {
  var STORAGE_KEY = "vellum-workspace-layout-v1";
  var LEGACY_SIDEBAR_KEY = "vellum-sb-open";
  var SIDEBAR_ACTION_ID = "ui.sidebar.set";

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function defaultLayout() {
    return {
      version: 1,
      revision: 0,
      surfaces: { sidebar: { visible: true, properties: {} } },
    };
  }

  function safeGet(storage, key) {
    try { return storage && storage.getItem(key); } catch (_) { return null; }
  }

  function safeSet(storage, key, value) {
    try { if (storage) storage.setItem(key, value); } catch (_) {}
  }

  function safeRemove(storage, key) {
    try { if (storage) storage.removeItem(key); } catch (_) {}
  }

  function normalizeLayout(value) {
    var defaults = defaultLayout();
    var source = value && typeof value === "object" ? value : {};
    var surfaces = source.surfaces && typeof source.surfaces === "object" ? source.surfaces : {};
    var sidebar = surfaces.sidebar && typeof surfaces.sidebar === "object" ? surfaces.sidebar : {};
    return {
      version: Number.isInteger(source.version) && source.version > 0 ? source.version : defaults.version,
      revision: Number.isInteger(source.revision) && source.revision >= 0 ? source.revision : defaults.revision,
      surfaces: Object.assign({}, surfaces, {
        sidebar: Object.assign({}, defaults.surfaces.sidebar, sidebar, {
          visible: typeof sidebar.visible === "boolean" ? sidebar.visible : defaults.surfaces.sidebar.visible,
          properties: sidebar.properties && typeof sidebar.properties === "object" ? sidebar.properties : {},
        }),
      }),
    };
  }

  function loadLayout(storage) {
    var stored = safeGet(storage, STORAGE_KEY);
    if (stored) {
      try { return normalizeLayout(JSON.parse(stored)); } catch (_) {}
    }
    var legacy = safeGet(storage, LEGACY_SIDEBAR_KEY);
    if (legacy === "0" || legacy === "1") {
      var migrated = defaultLayout();
      migrated.surfaces.sidebar.visible = legacy === "1";
      safeSet(storage, STORAGE_KEY, JSON.stringify(migrated));
      safeRemove(storage, LEGACY_SIDEBAR_KEY);
      return migrated;
    }
    return defaultLayout();
  }

  function receiptPatch(receipt) {
    return receipt && receipt.result && receipt.result.workspace_layout_patch;
  }

  function sameSidebarState(layout, patch) {
    var visible = patch && patch.surfaces && patch.surfaces.sidebar && patch.surfaces.sidebar.visible;
    return patch && patch.revision === layout.revision && visible === layout.surfaces.sidebar.visible;
  }

  function createWorkspaceLayoutRuntime(options) {
    options = options || {};
    var storage = options.storage === undefined ? window.localStorage : options.storage;
    var client = options.client || (window.VellumApi && window.VellumApi.appActions);
    var requestIdFactory = options.requestIdFactory || function () {
      return "ui_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 10);
    };
    var state = loadLayout(storage);
    var listeners = [];

    function snapshot() {
      return clone(state);
    }

    function persist() {
      safeSet(storage, STORAGE_KEY, JSON.stringify(state));
    }

    function emit() {
      var value = snapshot();
      listeners.slice().forEach(function (listener) { listener(value); });
    }

    function context(source, conversationId) {
      return {
        source: source || "ui",
        invocation_conversation_id: conversationId || "",
        device_id: "local-device",
        workspace_layout: snapshot(),
      };
    }

    function applyReceipt(receipt) {
      if (!receipt || ["applied", "undone"].indexOf(receipt.status) < 0) return receipt;
      var patch = receiptPatch(receipt);
      if (!patch || !patch.surfaces || !patch.surfaces.sidebar) return receipt;
      if (patch.version !== state.version) throw new Error("WORKSPACE_LAYOUT_VERSION_MISMATCH");
      if (patch.base_revision !== state.revision) {
        if (sameSidebarState(state, patch)) return receipt;
        throw new Error("STALE_WORKSPACE_LAYOUT_RECEIPT");
      }
      var sidebarPatch = patch.surfaces.sidebar;
      state = normalizeLayout(Object.assign({}, state, {
        revision: patch.revision,
        surfaces: Object.assign({}, state.surfaces, {
          sidebar: Object.assign({}, state.surfaces.sidebar, sidebarPatch),
        }),
      }));
      persist();
      emit();
      return receipt;
    }

    async function dispatch(actionId, args, dispatchOptions) {
      if (!client || typeof client.dispatch !== "function") throw new Error("APP_ACTIONS_UNREACHABLE");
      dispatchOptions = dispatchOptions || {};
      var request = {
        request_id: requestIdFactory(),
        action_id: actionId,
        action_version: "1",
        arguments: args || {},
      };
      var receipt = await client.dispatch(
        request,
        context(dispatchOptions.source || "ui", dispatchOptions.conversationId || ""),
      );
      return applyReceipt(receipt);
    }

    function dispatchSidebar(visible, dispatchOptions) {
      return dispatch(SIDEBAR_ACTION_ID, { visible: !!visible }, dispatchOptions);
    }

    async function undo(receipt, undoOptions) {
      if (!receipt || !receipt.undo || !receipt.undo.token) throw new Error("UNDO_UNAVAILABLE");
      if (!client || typeof client.undo !== "function") throw new Error("APP_ACTIONS_UNREACHABLE");
      undoOptions = undoOptions || {};
      var undone = await client.undo(
        receipt.undo.token,
        context(undoOptions.source || "ui", undoOptions.conversationId || ""),
      );
      return applyReceipt(undone);
    }

    function subscribe(listener) {
      listeners.push(listener);
      return function () { listeners = listeners.filter(function (item) { return item !== listener; }); };
    }

    return {
      snapshot: snapshot,
      context: context,
      applyReceipt: applyReceipt,
      dispatch: dispatch,
      dispatchSidebar: dispatchSidebar,
      undo: undo,
      subscribe: subscribe,
    };
  }

  window.VellumUI = window.VellumUI || {};
  window.VellumUI.AppActions = {
    STORAGE_KEY: STORAGE_KEY,
    SIDEBAR_ACTION_ID: SIDEBAR_ACTION_ID,
    createWorkspaceLayoutRuntime: createWorkspaceLayoutRuntime,
  };
})();
