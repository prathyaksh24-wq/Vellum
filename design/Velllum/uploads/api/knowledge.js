(function () {
  var client = window.VellumApi.client;

  function coreSources(kind, limit, offset) {
    var params = new URLSearchParams();
    if (kind) params.set("kind", String(kind));
    if (limit !== undefined) params.set("limit", String(limit));
    if (offset !== undefined) params.set("offset", String(offset));
    return client.request("/api/knowledge/core/sources?" + params.toString());
  }

  function coreObservations(origin, limit) {
    var params = new URLSearchParams();
    if (origin) params.set("origin", String(origin));
    if (limit !== undefined) params.set("limit", String(limit));
    return client.request("/api/knowledge/core/observations?" + params.toString());
  }

  function corePreferences(category, limit) {
    var params = new URLSearchParams();
    if (category) params.set("category", String(category));
    if (limit !== undefined) params.set("limit", String(limit));
    return client.request("/api/knowledge/core/preferences?" + params.toString());
  }

  window.VellumApi.knowledge = {
    coreStatus: function () { return client.request("/api/knowledge/core/status"); },
    coreOwnership: function () { return client.request("/api/knowledge/core/ownership"); },
    coreSources: coreSources,
    coreObservations: coreObservations,
    corePreferences: corePreferences,
    ingestionJobs: function (connector, limit) {
      var params = new URLSearchParams();
      if (connector) params.set("connector", String(connector));
      if (limit !== undefined) params.set("limit", String(limit));
      return client.request("/api/knowledge/core/ingestion-jobs?" + params.toString());
    },
    syncCursors: function (connector, limit) {
      var params = new URLSearchParams();
      if (connector) params.set("connector", String(connector));
      if (limit !== undefined) params.set("limit", String(limit));
      return client.request("/api/knowledge/core/sync-cursors?" + params.toString());
    },
    coreAnnotations: function (targetId, requiresReview, limit) {
      var params = new URLSearchParams();
      if (targetId) params.set("target_id", String(targetId));
      if (requiresReview !== undefined && requiresReview !== null) params.set("requires_review", String(Boolean(requiresReview)));
      if (limit !== undefined) params.set("limit", String(limit));
      return client.request("/api/knowledge/core/annotations?" + params.toString());
    },
    recordSignal: function (payload) {
      return client.request("/api/knowledge/core/signals", client.jsonOptions("POST", payload));
    },
    contextPack: function (payload) {
      return client.request("/api/knowledge/core/context-packs", client.jsonOptions("POST", payload));
    },
    bootstrapPreview: function (payload) {
      return client.request("/api/knowledge/core/bootstrap", client.jsonOptions("POST", Object.assign({}, payload || {}, {apply:false})));
    },
  };
})();
