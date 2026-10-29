(function () {
  "use strict";

  var OPEN_ACTION_ID = "observability.open";
  var STATUS_ACTION_ID = "observability.status";
  var STREAM_SET_ACTION_ID = "observability.stream.set";
  var REFRESH_ACTION_ID = "observability.refresh";

  function initialState() {
    return {
      streaming: true,
      reconnectRevision: 0,
      snapshot: null,
    };
  }

  function normalize(current) {
    var value = current && typeof current === "object" ? current : {};
    return {
      streaming: value.streaming !== false,
      reconnectRevision: Number.isInteger(value.reconnectRevision) ? value.reconnectRevision : 0,
      snapshot: value.snapshot && typeof value.snapshot === "object" ? value.snapshot : null,
    };
  }

  function applyReceipt(current, receipt) {
    var state = normalize(current);
    if (!receipt || ["applied", "undone"].indexOf(receipt.status) < 0) return state;
    var result = receipt.result || {};
    var patch = result.observability_control_patch;
    if (patch) {
      if (patch.version !== 1 || typeof patch.streaming !== "boolean") {
        throw new Error("INVALID_OBSERVABILITY_CONTROL_PATCH");
      }
      state.streaming = patch.streaming;
      if (patch.reconnect) state.reconnectRevision += 1;
    }
    if (result.observability_snapshot && typeof result.observability_snapshot === "object") {
      state.snapshot = result.observability_snapshot;
    }
    return state;
  }

  window.VellumUI = window.VellumUI || {};
  window.VellumUI.ObservabilityActions = {
    OPEN_ACTION_ID: OPEN_ACTION_ID,
    STATUS_ACTION_ID: STATUS_ACTION_ID,
    STREAM_SET_ACTION_ID: STREAM_SET_ACTION_ID,
    REFRESH_ACTION_ID: REFRESH_ACTION_ID,
    initialState: initialState,
    normalize: normalize,
    applyReceipt: applyReceipt,
  };
})();
