(function () {
  var STORAGE_KEY = "vellum-workspace-layout-v1";
  var LEGACY_SIDEBAR_KEY = "vellum-sb-open";
  var LEGACY_THEME_KEY = "vellum-theme";
  var SIDEBAR_ACTION_ID = "ui.sidebar.set";
  var SURFACE_ACTION_ID = "ui.surface.configure";
  var RESET_ACTION_ID = "ui.workspace.reset";
  var ADAPTIVE_APPLY_ACTION_ID = "ui.adaptive.apply";
  var WINDOW_ID_KEY = "vellum-adaptive-window-id";
  var CONVERSATION_NEW_ACTION_ID = "conversation.new";
  var CONVERSATION_OPEN_ACTION_ID = "conversation.open";
  var CONVERSATION_PIN_ACTION_ID = "conversation.pin";
  var CONVERSATION_UNPIN_ACTION_ID = "conversation.unpin";
  var CONVERSATION_RENAME_ACTION_ID = "conversation.rename";
  var CONVERSATION_SPACE_ACTION_ID = "conversation.space.set";
  var CONVERSATION_ARCHIVE_ACTION_ID = "conversation.archive";
  var CONVERSATION_RESTORE_ACTION_ID = "conversation.restore";
  var CONVERSATION_DELETE_ACTION_ID = "conversation.delete";
  var CONVERSATION_FORK_ACTION_ID = "conversation.fork";
  var CONVERSATION_WINDOW_OPEN_ACTION_ID = "conversation.window.open";
  var CONVERSATION_SHARE_ACTION_ID = "conversation.share";
  var DEVICE_SETTINGS_STORAGE_KEY = "vellum-device-settings-v1";
  var DEVICE_SETTINGS_UPDATE_ACTION_ID = "settings.device.update";
  var DEVICE_SETTINGS_DEFAULTS = {
    background: "galaxy",
    accent: "default",
    dock_position: "auto",
    dock_locked: false,
    computer_use_preview: false,
    personalization: {
      baseStyle: "default", warm: "default", enthusiastic: "default", headers: "default", emoji: "default",
      fastAnswers: true, custom: "", nickname: "", occupation: "", about: "", recordHist: true,
      webSearch: true, canvas: true, voice: true, advVoice: true, connector: true,
    },
  };

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
    return { version: 1, revision: 0, surfaces: clone(SURFACE_DEFAULTS), adaptive_ui: defaultAdaptiveState() };
  }

  function defaultAdaptiveState() {
    return { revision: 0, rules: [], signals: [], suppressions: [], last_rule_id: "" };
  }

  function normalizeAdaptiveState(value) {
    var source = value && typeof value === "object" ? value : {};
    return {
      revision: Number.isInteger(source.revision) && source.revision >= 0 ? source.revision : 0,
      rules: Array.isArray(source.rules) ? clone(source.rules) : [],
      signals: Array.isArray(source.signals) ? clone(source.signals) : [],
      suppressions: Array.isArray(source.suppressions) ? clone(source.suppressions) : [],
      last_rule_id: typeof source.last_rule_id === "string" ? source.last_rule_id : "",
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
      adaptive_ui: normalizeAdaptiveState(source.adaptive_ui),
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
    var windowStorage = options.windowStorage === undefined ? window.sessionStorage : options.windowStorage;
    var windowId = options.windowId || safeGet(windowStorage, WINDOW_ID_KEY);
    if (!windowId) {
      windowId = "window_" + Math.random().toString(36).slice(2, 12);
      safeSet(windowStorage, WINDOW_ID_KEY, windowId);
    }
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
        window_id: windowId,
        workspace_layout: snapshot(),
      }, contextResolver() || {});
    }

    function applyReceipt(receipt) {
      if (!receipt || ["applied", "undone"].indexOf(receipt.status) < 0) return receipt;
      var patch = receiptPatch(receipt);
      var adaptivePatch = receipt.result && receipt.result.adaptive_ui_patch;
      if ((!patch || !patch.surfaces) && !adaptivePatch) return receipt;
      if (patch && patch.surfaces) {
        if (patch.version !== state.version) throw new Error("WORKSPACE_LAYOUT_VERSION_MISMATCH");
        if (patch.base_revision !== state.revision && !patchMatches(state, patch)) {
          throw new Error("STALE_WORKSPACE_LAYOUT_RECEIPT");
        }
      }
      if (adaptivePatch) {
        if (!adaptivePatch.state || !Number.isInteger(adaptivePatch.revision)) throw new Error("INVALID_ADAPTIVE_UI_RECEIPT");
        if (adaptivePatch.base_revision !== state.adaptive_ui.revision) {
          if (adaptivePatch.revision !== state.adaptive_ui.revision || JSON.stringify(normalizeAdaptiveState(adaptivePatch.state)) !== JSON.stringify(state.adaptive_ui)) {
            throw new Error("STALE_ADAPTIVE_UI_RECEIPT");
          }
        }
      }
      if (patch && patch.surfaces && patch.base_revision === state.revision) {
        effectiveRevision = patch.revision;
        if (patch.replace) {
          deviceState = normalizeLayout({
            version: patch.version, revision: patch.revision,
            surfaces: patch.surfaces, adaptive_ui: deviceState.adaptive_ui,
          });
          sessionOverrides = {};
        } else if (patch.persistence === "session") {
          Object.keys(patch.surfaces).forEach(function (reference) {
            sessionOverrides[reference] = normalizePresentation(reference, patch.surfaces[reference]);
          });
        } else {
          deviceState = applySurfaces(deviceState, patch.surfaces, patch.revision);
          Object.keys(patch.surfaces).forEach(function (reference) { delete sessionOverrides[reference]; });
        }
      }
      if (adaptivePatch && adaptivePatch.base_revision === state.adaptive_ui.revision) {
        deviceState.adaptive_ui = normalizeAdaptiveState(adaptivePatch.state);
      }
      state = composeState();
      if (adaptivePatch || (patch && patch.persistence !== "session")) persist();
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
        Object.assign(context(dispatchOptions.source || "ui", dispatchOptions.conversationId || ""), {
          adaptive_learning_signal: dispatchOptions.learn === true,
        }),
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

    function ruleMatches(rule, actionContext) {
      if (rule.scope === "global") return true;
      var field = {
        device: "device_id", agent: "active_agent", project: "project_id", window: "window_id",
      }[rule.scope];
      return !!field && !!rule.scope_id && rule.scope_id === actionContext[field];
    }

    function ruleNeedsChange(rule) {
      var args = rule.arguments || {};
      if (Object.prototype.hasOwnProperty.call(sessionOverrides, args.reference)) return false;
      var current = state.surfaces[args.reference];
      if (!current) return false;
      if (Object.prototype.hasOwnProperty.call(args, "visible")) return current.visible !== args.visible;
      var properties = args.properties || {};
      return Object.keys(properties).some(function (name) { return current.properties[name] !== properties[name]; });
    }

    var applying = null;
    async function maybeApply(applyOptions) {
      if (applying) {
        await applying;
        return maybeApply(applyOptions);
      }
      applyOptions = applyOptions || {};
      applying = (async function () {
        var actionContext = context("ui", applyOptions.conversationId || "");
        var rules = state.adaptive_ui.rules || [];
        var suppressions = new Set(state.adaptive_ui.suppressions || []);
        var priority = { project: 4, agent: 3, window: 2, device: 1, global: 0 };
        var selected = new Map();
        rules.forEach(function (rule, index) {
          if (!rule.enabled || rule.suppressed || suppressions.has(rule.signature) || !ruleMatches(rule, actionContext)) return;
          var args = rule.arguments || {};
          var field = Object.prototype.hasOwnProperty.call(args, "visible") ? "visible" : Object.keys(args.properties || {})[0];
          if (!field) return;
          var key = args.reference + ":" + field;
          var score = (rule.origin === "explicit" ? 100 : 0) + (priority[rule.scope] || 0) * 10 + index / 1000;
          if (!selected.has(key) || selected.get(key).score < score) selected.set(key, { rule: rule, score: score });
        });
        for (var candidate of selected.values()) {
          if (!ruleNeedsChange(candidate.rule)) continue;
          var receipt = await dispatch(ADAPTIVE_APPLY_ACTION_ID, { rule_id: candidate.rule.id }, applyOptions);
          if (typeof applyOptions.onReceipt === "function") applyOptions.onReceipt(receipt);
          if (!receipt || receipt.status !== "applied") break;
        }
      })();
      try { return await applying; } finally { applying = null; }
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
      maybeApply: maybeApply,
      undo: undo,
      subscribe: subscribe,
    };
  }

  function normalizeDeviceSettings(value) {
    var source = value && typeof value === "object" ? value : {};
    var rawValues = source.values && typeof source.values === "object" ? source.values : {};
    return {
      version: Number.isInteger(source.version) && source.version > 0 ? source.version : 1,
      revision: Number.isInteger(source.revision) && source.revision >= 0 ? source.revision : 0,
      values: Object.assign({}, DEVICE_SETTINGS_DEFAULTS, rawValues, {
        personalization: Object.assign({}, DEVICE_SETTINGS_DEFAULTS.personalization, rawValues.personalization || {}),
      }),
    };
  }

  function loadDeviceSettings(storage) {
    var stored = safeGet(storage, DEVICE_SETTINGS_STORAGE_KEY);
    var raw = null;
    if (stored) {
      try { raw = JSON.parse(stored); } catch (_) {}
    }
    if (raw) return normalizeDeviceSettings(raw);
    var values = clone(DEVICE_SETTINGS_DEFAULTS);
    var background = safeGet(storage, "vellum-background");
    var accent = safeGet(storage, "vellum-accent");
    var dockPosition = safeGet(storage, "vellum-dock-position");
    var dockLocked = safeGet(storage, "vellum-dock-locked");
    var personalization = safeGet(storage, "vellum-pers");
    if (background) values.background = background;
    if (accent) values.accent = accent;
    if (dockPosition) values.dock_position = dockPosition;
    if (dockLocked === "0" || dockLocked === "1") values.dock_locked = dockLocked === "1";
    if (personalization) {
      try {
        var parsed = JSON.parse(personalization);
        if (parsed && typeof parsed === "object") {
          Object.keys(DEVICE_SETTINGS_DEFAULTS.personalization).forEach(function (key) {
            if (parsed[key] !== undefined) values.personalization[key] = parsed[key];
          });
        }
      } catch (_) {}
    }
    var migrated = normalizeDeviceSettings({ version: 1, revision: 0, values: values });
    safeSet(storage, DEVICE_SETTINGS_STORAGE_KEY, JSON.stringify(migrated));
    ["vellum-background", "vellum-accent", "vellum-dock-position", "vellum-dock-locked", "vellum-pers"].forEach(function (key) {
      safeRemove(storage, key);
    });
    return migrated;
  }

  function createDeviceSettingsRuntime(options) {
    options = options || {};
    var storage = options.storage === undefined ? window.localStorage : options.storage;
    var client = options.client || (window.VellumApi && window.VellumApi.appActions);
    var requestIdFactory = options.requestIdFactory || function () {
      return "ui_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 10);
    };
    var contextResolver = options.contextResolver || function () { return {}; };
    var state = loadDeviceSettings(storage);
    var listeners = [];

    function snapshot() { return clone(state); }
    function persist() { safeSet(storage, DEVICE_SETTINGS_STORAGE_KEY, JSON.stringify(state)); }
    function emit() {
      var value = snapshot();
      listeners.slice().forEach(function (listener) { listener(value); });
    }
    function context(source, conversationId) {
      return Object.assign({
        source: source || "ui",
        invocation_conversation_id: conversationId || "",
        device_id: "local-device",
        device_settings: snapshot(),
      }, contextResolver() || {});
    }
    function applyReceipt(receipt) {
      if (!receipt || ["applied", "undone"].indexOf(receipt.status) < 0) return receipt;
      var patch = receipt.result && receipt.result.device_settings_patch;
      if (!patch || !patch.values) return receipt;
      if (patch.version !== state.version) throw new Error("DEVICE_SETTINGS_VERSION_MISMATCH");
      if (patch.base_revision !== state.revision) throw new Error("STALE_DEVICE_SETTINGS_RECEIPT");
      var nextValues = Object.assign({}, state.values, patch.values);
      if (patch.values.personalization) {
        nextValues.personalization = Object.assign({}, state.values.personalization, patch.values.personalization);
      }
      state = normalizeDeviceSettings({ version: patch.version, revision: patch.revision, values: nextValues });
      persist();
      emit();
      return receipt;
    }
    async function dispatch(patch, dispatchOptions) {
      if (!client || typeof client.dispatch !== "function") throw new Error("APP_ACTIONS_UNREACHABLE");
      dispatchOptions = dispatchOptions || {};
      var request = {
        request_id: requestIdFactory(),
        action_id: DEVICE_SETTINGS_UPDATE_ACTION_ID,
        action_version: "1",
        arguments: { patch: patch || {} },
      };
      var receipt = await client.dispatch(request, context(dispatchOptions.source || "ui", dispatchOptions.conversationId || ""));
      return applyReceipt(receipt);
    }
    function subscribe(listener) {
      listeners.push(listener);
      return function () { listeners = listeners.filter(function (item) { return item !== listener; }); };
    }
    return { snapshot: snapshot, context: context, applyReceipt: applyReceipt, dispatch: dispatch, subscribe: subscribe };
  }

  function createConversationActionRuntime(options) {
    options = options || {};
    var client = options.client || (window.VellumApi && window.VellumApi.appActions);
    var getConversation = options.getConversation || function () { return null; };
    var upsertConversation = options.upsertConversation || function () {};
    var removeConversation = options.removeConversation || function () {};
    var navigate = options.navigate || function () {};
    var openNativeWindow = options.openNativeWindow || function () {};
    var sideEffectError = options.sideEffectError || function () {};
    var applySessionControl = options.applySessionControl || function () {};
    var contextResolver = options.contextResolver || function () { return {}; };
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
      CONVERSATION_FORK_ACTION_ID,
      CONVERSATION_SHARE_ACTION_ID,
    ]);

    function context(source, conversationId) {
      return Object.assign({
        source: source || "ui",
        invocation_conversation_id: conversationId || "",
      }, contextResolver() || {});
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
      if (result.session_control_patch) applySessionControl(result.session_control_patch, receipt);
      if (result.deleted && result.conversation_id) {
        removeConversation(result.conversation_id);
      } else if (result.conversation && result.conversation.id) {
        upsertConversation(result.conversation);
      }
      if (result.navigation) navigate(result.navigation);
      if (result.native_window) {
        try { Promise.resolve(openNativeWindow(result.native_window)).catch(sideEffectError); }
        catch (error) { sideEffectError(error); }
      }
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

    async function cancel(receipt, cancelOptions) {
      if (!receipt || !receipt.confirmation || !receipt.confirmation.token) throw new Error("CONFIRMATION_UNAVAILABLE");
      if (!client || typeof client.cancel !== "function") throw new Error("APP_ACTIONS_UNREACHABLE");
      cancelOptions = cancelOptions || {};
      var token = receipt.confirmation.token;
      var cancelled = await client.cancel(
        token,
        context(cancelOptions.source || "ui", cancelOptions.conversationId || ""),
      );
      pendingConfirmations.delete(token);
      pendingRequests.delete(receipt.request_id);
      return applyReceipt(cancelled);
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
      cancel: cancel,
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
    CONVERSATION_FORK_ACTION_ID: CONVERSATION_FORK_ACTION_ID,
    CONVERSATION_WINDOW_OPEN_ACTION_ID: CONVERSATION_WINDOW_OPEN_ACTION_ID,
    CONVERSATION_SHARE_ACTION_ID: CONVERSATION_SHARE_ACTION_ID,
    DEVICE_SETTINGS_STORAGE_KEY: DEVICE_SETTINGS_STORAGE_KEY,
    DEVICE_SETTINGS_UPDATE_ACTION_ID: DEVICE_SETTINGS_UPDATE_ACTION_ID,
    DEVICE_SETTINGS_DEFAULTS: clone(DEVICE_SETTINGS_DEFAULTS),
    SURFACE_DEFAULTS: clone(SURFACE_DEFAULTS),
    SURFACE_DEFINITIONS: clone(SURFACE_DEFINITIONS),
    createWorkspaceLayoutRuntime: createWorkspaceLayoutRuntime,
    createDeviceSettingsRuntime: createDeviceSettingsRuntime,
    createConversationActionRuntime: createConversationActionRuntime,
  };
})();
