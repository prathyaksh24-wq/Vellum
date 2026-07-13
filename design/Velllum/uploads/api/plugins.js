(function () {
  var client = window.VellumApi.client;
  window.VellumApi.plugins = {
    list: function () { return client.request("/api/plugins"); },
    skills: function () { return client.request("/api/skills"); },
    skillsOverview: function (signal) { return client.request("/api/skills/v2/overview", { signal: signal }); },
    skillsCatalog: function (params, signal) {
      var query = new URLSearchParams(params || {}).toString();
      return client.request("/api/skills/v2/catalog" + (query ? "?" + query : ""), { signal: signal });
    },
    skillDetail: function (name, signal) { return client.request("/api/skills/" + encodeURIComponent(name), { signal: signal }); },
    skillAction: function (body, signal) { return client.request("/api/skills/action", client.jsonOptions("POST", body, signal)); },
    pendingApprove: function (id) { return client.request("/api/skills/v2/pending/" + encodeURIComponent(id) + "/approve", client.jsonOptions("POST")); },
    pendingReject: function (id) { return client.request("/api/skills/v2/pending/" + encodeURIComponent(id) + "/reject", client.jsonOptions("POST")); },
    duplicateDecision: function (id, decision, reason) { return client.request("/api/skills/v2/duplicates/" + encodeURIComponent(id) + "/decision", client.jsonOptions("POST", {decision:decision, reason:reason || ""})); },
    hubSearch: function (body, signal) { return client.request("/api/skills/v2/hub/search", client.jsonOptions("POST", body, signal)); },
    hubInspect: function (identifier, signal) { return client.request("/api/skills/v2/hub/inspect", client.jsonOptions("POST", {identifier:identifier}, signal)); },
    hubMutation: function (action, body) { return client.request("/api/skills/v2/hub/" + action, client.jsonOptions("POST", body)); },
    learn: function (source, threadId, category) { return client.request("/api/skills/learn", client.jsonOptions("POST", {source:source, thread_id:threadId || "skills-hub", category:category || "community"})); },
    capabilities: function () { return client.request("/api/capabilities"); },
  };
})();
