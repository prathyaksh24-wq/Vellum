(function () {
  var client = window.VellumApi.client;

  function query(value, limit) {
    var params = new URLSearchParams();
    params.set("q", String(value || "").trim());
    if (limit !== undefined) params.set("limit", String(limit));
    return client.request("/api/knowledge/query?" + params.toString());
  }

  function lint(staleDays) {
    return client.request("/api/knowledge/lint", client.jsonOptions("POST", {
      stale_days: staleDays === undefined ? 120 : staleDays,
    }));
  }

  function rebuildIndex() {
    return client.request("/api/knowledge/rebuild-index", { method: "POST" });
  }

  window.VellumApi.knowledge = {
    status: function () { return client.request("/api/knowledge/status"); },
    query: query,
    page: function (ref) { return client.request("/api/knowledge/pages/" + encodeURIComponent(ref)); },
    lint: lint,
    indexRebuild: rebuildIndex,
  };
})();
