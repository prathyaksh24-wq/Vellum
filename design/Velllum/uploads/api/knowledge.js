(function () {
  var client = window.VellumApi.client;

  function query(value, limit) {
    var params = new URLSearchParams();
    params.set("q", String(value || "").trim());
    if (limit !== undefined) params.set("limit", String(limit));
    return client.request("/api/knowledge/query?" + params.toString());
  }

  function search(value, scope, limit) {
    var params = new URLSearchParams();
    params.set("q", String(value || "").trim());
    params.set("scope", scope || "all");
    if (limit !== undefined) params.set("limit", String(limit));
    return client.request("/api/knowledge/search?" + params.toString());
  }

  function lint(staleDays) {
    return client.request("/api/knowledge/lint", client.jsonOptions("POST", {
      stale_days: staleDays === undefined ? 120 : staleDays,
    }));
  }

  function rebuildIndex() {
    return client.request("/api/knowledge/rebuild-index", { method: "POST" });
  }

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
    status: function () { return client.request("/api/knowledge/status"); },
    query: query,
    search: search,
    vaultNote: function (ref) { return client.request("/api/knowledge/vault-note?ref=" + encodeURIComponent(ref)); },
    page: function (ref) { return client.request("/api/knowledge/pages/" + encodeURIComponent(ref)); },
    lint: lint,
    indexRebuild: rebuildIndex,
    coreStatus: function () { return client.request("/api/knowledge/core/status"); },
    coreOwnership: function () { return client.request("/api/knowledge/core/ownership"); },
    coreSources: coreSources,
    coreObservations: coreObservations,
    corePreferences: corePreferences,
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
