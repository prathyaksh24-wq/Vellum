(function () {
  var client = window.VellumApi.client;
  window.VellumApi.conversations = {
    list: function () { return client.request("/api/conversations"); },
    library: function () { return client.request("/api/conversations/library"); },
    search: function (query, filters) {
      var params = new URLSearchParams();
      params.set("q", query || "");
      Object.keys(filters || {}).forEach(function (key) {
        var value = filters[key];
        if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
      });
      return client.request("/api/conversations/search?" + params.toString());
    },
    get: function (id) { return client.request("/api/conversations/" + encodeURIComponent(id)); },
    save: function (conversation) {
      return client.request("/api/conversations/" + encodeURIComponent(conversation.id), client.jsonOptions("PUT", conversation));
    },
    patch: function (id, patch) {
      return client.request("/api/conversations/" + encodeURIComponent(id), client.jsonOptions("PATCH", patch));
    },
    organize: function (id, patch) {
      return client.request("/api/conversations/" + encodeURIComponent(id) + "/organization", client.jsonOptions("PATCH", patch));
    },
    rebuildOrganization: function () {
      return client.request("/api/conversations/organization/rebuild", { method: "POST" });
    },
    remove: function (id) {
      return client.request("/api/conversations/" + encodeURIComponent(id), { method: "DELETE" });
    },
    context: function (id) {
      return client.request("/api/conversations/" + encodeURIComponent(id) + "/context");
    },
    attachContext: function (id, body) {
      return client.request("/api/conversations/" + encodeURIComponent(id) + "/context", client.jsonOptions("POST", body));
    },
    removeContext: function (id, attachmentId) {
      return client.request("/api/conversations/" + encodeURIComponent(id) + "/context/" + encodeURIComponent(attachmentId), { method: "DELETE" });
    },
  };
})();
