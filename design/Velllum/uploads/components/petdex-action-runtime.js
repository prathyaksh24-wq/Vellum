(function () {
  var VERSION = 1;

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function normalize(raw) {
    var source = raw && typeof raw === "object" ? raw : {};
    var installed = Array.isArray(source.installed) ? source.installed.filter(Boolean).map(String) : [];
    var available = Array.isArray(source.available) ? source.available.filter(Boolean).map(String) : [];
    var position = source.position && typeof source.position === "object" ? source.position : {};
    return {
      revision: Number.isInteger(source.revision) && source.revision >= 0 ? source.revision : 0,
      installed: [...new Set(installed)],
      available: [...new Set(available)],
      active: String(source.active || ""),
      hidden: !!source.hidden,
      size: ["sm", "md", "lg"].includes(source.size) ? source.size : "md",
      position: clone(position),
    };
  }

  function sameState(left, right) {
    var keys = ["installed", "active", "hidden", "size", "position"];
    return keys.every(function (key) { return JSON.stringify(left[key]) === JSON.stringify(right[key]); });
  }

  function applyReceipt(current, receipt) {
    var state = normalize(current);
    if (!receipt || !["applied", "undone"].includes(receipt.status)) return state;
    var patch = receipt.result && receipt.result.petdex_patch;
    if (!patch) return state;
    if (patch.version !== VERSION) throw new Error("PETDEX_VERSION_MISMATCH");
    var incoming = normalize(Object.assign({}, patch.state || {}, {revision: patch.revision, available: state.available}));
    if (patch.base_revision !== state.revision) {
      if (patch.revision === state.revision && sameState(incoming, state)) return state;
      throw new Error("STALE_PETDEX_RECEIPT");
    }
    return incoming;
  }

  function context(state) {
    return normalize(state);
  }

  function positionStyle(position, viewport) {
    var pos = position && typeof position === "object" ? position : {};
    var width = Math.max(0, Number(viewport && viewport.width) || 0);
    var height = Math.max(0, Number(viewport && viewport.height) || 0);
    var right = Math.max(0, width - 190);
    var bottom = Math.max(0, height - 250);
    var anchors = {
      "top-left": {left: 20, top: 20},
      "top-right": {left: right, top: 20},
      "bottom-left": {left: 20, top: bottom},
      "bottom-right": {left: right, top: bottom},
    };
    if (anchors[pos.anchor]) return anchors[pos.anchor];
    return {
      left: pos.x != null ? pos.x : right,
      top: pos.y != null ? pos.y : bottom,
    };
  }

  window.VellumUI = window.VellumUI || {};
  window.VellumUI.PetdexActions = {
    applyReceipt: applyReceipt,
    context: context,
    normalize: normalize,
    positionStyle: positionStyle,
  };
})();
