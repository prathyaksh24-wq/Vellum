(function () {
  var STORAGE_KEY = "vellum-workspace-layout-v1";
  var LEGACY_SIDEBAR_KEY = "vellum-sb-open";
  var LEGACY_THEME_KEY = "vellum-theme";
  var SIDEBAR_ACTION_ID = "ui.sidebar.set";
  var SURFACE_ACTION_ID = "ui.surface.configure";
  var RESET_ACTION_ID = "ui.workspace.reset";
  var CONVERSATION_NEW_ACTION_ID = "conversation.new";
  var CONVERSATION_OPEN_ACTION_ID = "conversation.open";
  var CONVERSATION_PIN_ACTION_ID = "conversation.pin";
  var CONVERSATION_UNPIN_ACTION_ID = "conversation.unpin";
  var CONVERSATION_RENAME_ACTION_ID = "conversation.rename";
  var CONVERSATION_SPACE_ACTION_ID = "conversation.space.set";
  var CONVERSATION_ARCHIVE_ACTION_ID = "conversation.archive";
  var CONVERSATION_RESTORE_ACTION_ID = "conversation.restore";
  var CONVERSATION_DELETE_ACTION_ID = "conversation.delete";

  var SURFACE_DEFAULTS = {
    workspace: { visible: true, location: "application", properties: { theme: "dark" } },
    sidebar: { visible: true, location: "left", properties: {} },
    settings: { visible: false, location: "overlay", properties: {} },
    "right-panel": { visible: false, location: "right", properties: {} },
    composer: { visible: true, location: "bottom", properties: { size: "comfortable" } },
    "composer.send": { visible: true, location: "composer-action", properties: { label: "Send", size: "medium" } },
  };

  var SURFACE_DEFINITIONS = [
    { reference: "workspace", title: "Workspace", supportedLocations: ["application"], configurableProperties: ["theme"], controlKernel: true },
    { reference: "sidebar", title: "Sidebar", supportedLocations: ["left"], configurableProperties: [], controlKernel: false },
    { reference: "settings", title: "Settings", supportedLocations: ["overlay"], configurableProperties: [], controlKernel: false },
    { reference: "right-panel", title: "Right panel", supportedLocations: ["right"], configurableProperties: [], controlKernel: false },
    { reference: "composer", title: "Composer", supportedLocations: ["bottom"], configurableProperties: ["size"], controlKernel: true },
    { reference: "composer.send", title: "Send button", supportedLocations: ["composer-action"], configurableProperties: ["label", "size"], controlKernel: true },
  ];

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function defaultLayout() {
    return { version: 1, revision: 0, surfaces: clone(SURFACE_DEFAULTS) };
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

  function normalizePresentation(reference, value) {
    var defaults = SURFACE_DEFAULTS[reference] || { visible: true, location: "", properties: {} };
    var source = value && typeof value === "object" ? value : {};
    return {
      visible: typeof source.visible === "boolean" ? source.visible : defaults.visible,
      location: typeof source.location === "string" && source.location ? source.location : defaults.location,
      properties: Object.assign({}, defaults.properties, source.properties && typeof source.properties === "object" ? source.properties : {}),
    };
  }

  function normalizeLayout(value) {
    var defaults = defaultLayout();
    var source = value && typeof value === "object" ? value : {};
    var sourceSurfaces = source.surfaces && typeof source.surfaces === "object" ? source.surfaces : {};
    var surfaces = {};
    Object.keys(SURFACE_DEFAULTS).forEach(function (reference) {
      surfaces[reference] = normalizePresentation(reference, sourceSurfaces[reference]);
    });
    Object.keys(sourceSurfaces).forEach(function (reference) {
      if (!surfaces[reference]) surfaces[reference] = normalizePresentation(reference, sourceSurfaces[reference]);
    });
    return {
      version: Number.isInteger(source.version) && source.version > 0 ? source.version : defaults.version,
      revision: Number.isInteger(source.revision) && source.revision >= 0 ? source.revision : defaults.revision,
      surfaces: surfaces,
    };
  }

  function loadLayout(storage) {
    var stored = safeGet(storage, STORAGE_KEY);
    var raw = null;
    if (stored) {
      try { raw = JSON.parse(stored); } catch (_) {}
    }
    var layout = normalizeLayout(raw);
    var migrated = !raw;
    var legacySidebar = safeGet(storage, LEGACY_SIDEBAR_KEY);
    if ((!raw || !raw.surfaces || !raw.surfaces.sidebar) && (legacySidebar === "0" || legacySidebar === "1")) {
      layout.surfaces.sidebar.visible = legacySidebar === "1";
      migrated = true;
    }
    var legacyTheme = safeGet(storage, LEGACY_THEME_KEY);
    if ((!raw || !raw.surfaces || !raw.surfaces.workspace) && (legacyTheme === "dark" || legacyTheme === "light")) {
      layout.surfaces.workspace.properties.theme = legacyTheme;
      migrated = true;
    }
    if (migrated || JSON.stringify(layout) !== JSON.stringify(raw)) {
      safeSet(storage, STORAGE_KEY, JSON.stringify(layout));
    }
    safeRemove(storage, LEGACY_SIDEBAR_KEY);
    safeRemove(storage, LEGACY_THEME_KEY);
    return layout;
  }

  function receiptPatch(receipt) {
    return receipt && receipt.result && receipt.result.workspace_layout_patch;
  }

  function patchMatches(layout, patch) {
    if (!patch || patch.revision !== layout.revision) return false;
    return Object.keys(patch.surfaces || {}).every(function (reference) {
      return JSON.stringify(normalizePresentation(reference, patch.surfaces[reference])) === JSON.stringify(layout.surfaces[reference]);
    });
  }

  function applySurfaces(layout, surfaces, revision) {
    var next = normalizeLayout(layout);
    Object.keys(surfaces || {}).forEach(function (reference) {
      next.surfaces[reference] = normalizePresentation(reference, surfaces[reference]);
    });
    next.revision = revision;
    return next;
  }

  function createWorkspaceLayoutRuntime(options) {
    options = options || {};
    var storage = options.storage === undefined ? window.localStorage : options.storage;
    var client = options.client || (window.VellumApi && window.VellumApi.appActions);
    var requestIdFactory = options.requestIdFactory || function () {
      return "ui_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 10);
    };
    var contextResolver = options.contextResolver || function () {
      var focused = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.uiReference || "";
      var selected = document.querySelector && document.querySelector('[data-ui-selected="true"]');
      var visible = document.querySelectorAll ? [...document.querySelectorAll("[data-ui-reference]")].filter(function (node) {
        return !node.hidden && node.getAttribute("aria-hidden") !== "true";
      }).map(function (node) { return node.dataset.uiReference; }) : [];
      return {
        focused_ui_reference: focused,
        selected_ui_reference: selected && selected.dataset.uiReference || "",
        visible_ui_references: [...new Set(visible.filter(Boolean))],
      };
    };
    var deviceState = loadLayout(storage);
    var sessionOverrides = {};
    var effectiveRevision = deviceState.revision;
    var listeners = [];

    function composeState() {
      var next = normalizeLayout(deviceState);
      Object.keys(sessionOverrides).forEach(function (reference) {
        next.surfaces[reference] = normalizePresentation(reference, sessionOverrides[reference]);
      });
      next.revision = effectiveRevision;
      return next;
    }

    var state = composeState();

    function snapshot() {
      return clone(state);
    }

    function persist() {
      safeSet(storage, STORAGE_KEY, JSON.stringify(deviceState));
    }

    function emit() {
      var value = snapshot();
      listeners.slice().forEach(function (listener) { listener(value); });
    }

    function context(source, conversationId) {
      return Object.assign({
        source: source || "ui",
        invocation_conversation_id: conversationId || "",
        device_id: "local-device",
        workspace_layout: snapshot(),
      }, contextResolver() || {});
    }

    function applyReceipt(receipt) {
      if (!receipt || ["applied", "undone"].indexOf(receipt.status) < 0) return receipt;
      var patch = receiptPatch(receipt);
      if (!patch || !patch.surfaces) return receipt;
      if (patch.version !== state.version) throw new Error("WORKSPACE_LAYOUT_VERSION_MISMATCH");
      if (patch.base_revision !== state.revision) {
        if (patchMatches(state, patch)) return receipt;
        throw new Error("STALE_WORKSPACE_LAYOUT_RECEIPT");
      }
      effectiveRevision = patch.revision;
      if (patch.replace) {
        deviceState = normalizeLayout({ version: patch.version, revision: patch.revision, surfaces: patch.surfaces });
        sessionOverrides = {};
        persist();
      } else if (patch.persistence === "session") {
        Object.keys(patch.surfaces).forEach(function (reference) {
          sessionOverrides[reference] = normalizePresentation(reference, patch.surfaces[reference]);
        });
      } else {
        deviceState = applySurfaces(deviceState, patch.surfaces, patch.revision);
        Object.keys(patch.surfaces).forEach(function (reference) { delete sessionOverrides[reference]; });
        persist();
      }
      state = composeState();
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
      dispatchOptions = dispatchOptions || {};
      var actionArguments = { visible: !!visible };
      if (dispatchOptions.persistence === "session") actionArguments.persistence = "session";
      return dispatch(SIDEBAR_ACTION_ID, actionArguments, dispatchOptions);
    }

    function dispatchSurface(reference, presentation, dispatchOptions) {
      dispatchOptions = dispatchOptions || {};
      var actionArguments = Object.assign({ reference: reference }, presentation || {});
      if (dispatchOptions.persistence === "session") actionArguments.persistence = "session";
      return dispatch(SURFACE_ACTION_ID, actionArguments, dispatchOptions);
    }

    function reset(dispatchOptions) {
      return dispatch(RESET_ACTION_ID, {}, dispatchOptions || {});
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
      dispatchSurface: dispatchSurface,
      reset: reset,
      undo: undo,
      subscribe: subscribe,
    };
  }

  function createConversationActionRuntime(options) {
    options = options || {};
    var client = options.client || (window.VellumApi && window.VellumApi.appActions);
    var getConversation = options.getConversation || function () { return null; };
    var upsertConversation = options.upsertConversation || function () {};
    var removeConversation = options.removeConversation || function () {};
    var navigate = options.navigate || function () {};
    var requestIdFactory = options.requestIdFactory || function () {
      return "ui_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 10);
    };
    var pendingConfirmations = new Map();
    var pendingRequests = new Map();
    var revisionActions = new Set([
      CONVERSATION_PIN_ACTION_ID,
      CONVERSATION_UNPIN_ACTION_ID,
      CONVERSATION_RENAME_ACTION_ID,
      CONVERSATION_SPACE_ACTION_ID,
      CONVERSATION_ARCHIVE_ACTION_ID,
      CONVERSATION_RESTORE_ACTION_ID,
      CONVERSATION_DELETE_ACTION_ID,
    ]);

    function context(source, conversationId) {
      return {
        source: source || "ui",
        invocation_conversation_id: conversationId || "",
      };
    }

    function rememberRequest(request) {
      if (!request || !request.request_id) return request;
      pendingRequests.set(request.request_id, request);
      return request;
    }

    function applyReceipt(receipt) {
      if (!receipt) return receipt;
      if (receipt.status === "confirmation_required") {
        var confirmation = receipt.confirmation || {};
        var request = pendingRequests.get(receipt.request_id);
        if (confirmation.token && request) pendingConfirmations.set(confirmation.token, request);
        return receipt;
      }
      pendingRequests.delete(receipt.request_id);
      if (["applied", "undone"].indexOf(receipt.status) < 0) return receipt;
      var result = receipt.result || {};
      if (result.deleted && result.conversation_id) {
        removeConversation(result.conversation_id);
      } else if (result.conversation && result.conversation.id) {
        upsertConversation(result.conversation);
      }
      if (result.navigation) navigate(result.navigation);
      return receipt;
    }

    async function dispatch(actionId, args, dispatchOptions) {
      if (!client || typeof client.dispatch !== "function") throw new Error("APP_ACTIONS_UNREACHABLE");
      dispatchOptions = dispatchOptions || {};
      var actionArguments = Object.assign({}, args || {});
      if (revisionActions.has(actionId) && actionArguments.target_revision === undefined) {
        var targetId = actionArguments.conversation_id || dispatchOptions.conversationId || "";
        var target = targetId && getConversation(targetId);
        if (target && Number.isInteger(target.revision)) actionArguments.target_revision = target.revision;
      }
      var request = {
        request_id: requestIdFactory(),
        action_id: actionId,
        action_version: "1",
        arguments: actionArguments,
      };
      rememberRequest(request);
      var actionContext = context(dispatchOptions.source || "ui", dispatchOptions.conversationId || "");
      var receipt = await client.dispatch(request, actionContext);
      if (receipt && receipt.status === "confirmation_required" && receipt.confirmation && receipt.confirmation.token) {
        pendingConfirmations.set(receipt.confirmation.token, request);
      }
      return applyReceipt(receipt);
    }

    async function confirm(receipt, confirmOptions) {
      if (!receipt || !receipt.confirmation || !receipt.confirmation.token) throw new Error("CONFIRMATION_UNAVAILABLE");
      if (!client || typeof client.confirm !== "function") throw new Error("APP_ACTIONS_UNREACHABLE");
      confirmOptions = confirmOptions || {};
      var token = receipt.confirmation.token;
      var request = pendingConfirmations.get(token);
      if (!request) throw new Error("CONFIRMATION_UNAVAILABLE");
      var confirmed = await client.confirm(
        token,
        request,
        context(confirmOptions.source || "ui", confirmOptions.conversationId || ""),
      );
      if (confirmed && confirmed.status !== "confirmation_required") pendingConfirmations.delete(token);
      return applyReceipt(confirmed);
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

    return {
      context: context,
      rememberRequest: rememberRequest,
      applyReceipt: applyReceipt,
      dispatch: dispatch,
      confirm: confirm,
      undo: undo,
    };
  }

  window.VellumUI = window.VellumUI || {};
  window.VellumUI.AppActions = {
    STORAGE_KEY: STORAGE_KEY,
    SIDEBAR_ACTION_ID: SIDEBAR_ACTION_ID,
    SURFACE_ACTION_ID: SURFACE_ACTION_ID,
    RESET_ACTION_ID: RESET_ACTION_ID,
    CONVERSATION_NEW_ACTION_ID: CONVERSATION_NEW_ACTION_ID,
    CONVERSATION_OPEN_ACTION_ID: CONVERSATION_OPEN_ACTION_ID,
    CONVERSATION_PIN_ACTION_ID: CONVERSATION_PIN_ACTION_ID,
    CONVERSATION_UNPIN_ACTION_ID: CONVERSATION_UNPIN_ACTION_ID,
    CONVERSATION_RENAME_ACTION_ID: CONVERSATION_RENAME_ACTION_ID,
    CONVERSATION_SPACE_ACTION_ID: CONVERSATION_SPACE_ACTION_ID,
    CONVERSATION_ARCHIVE_ACTION_ID: CONVERSATION_ARCHIVE_ACTION_ID,
    CONVERSATION_RESTORE_ACTION_ID: CONVERSATION_RESTORE_ACTION_ID,
    CONVERSATION_DELETE_ACTION_ID: CONVERSATION_DELETE_ACTION_ID,
    SURFACE_DEFAULTS: clone(SURFACE_DEFAULTS),
    SURFACE_DEFINITIONS: clone(SURFACE_DEFINITIONS),
    createWorkspaceLayoutRuntime: createWorkspaceLayoutRuntime,
    createConversationActionRuntime: createConversationActionRuntime,
  };
})();
