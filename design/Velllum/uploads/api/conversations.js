(function () {
  var client = window.VellumApi.client;
  window.VellumApi.conversations = {
    list: function () { return client.request("/api/conversations"); },
    get: function (id) { return client.request("/api/conversations/" + encodeURIComponent(id)); },
    save: function (conversation) {
      return client.request("/api/conversations/" + encodeURIComponent(conversation.id), client.jsonOptions("PUT", conversation));
    },
    patch: function (id, patch) {
      return client.request("/api/conversations/" + encodeURIComponent(id), client.jsonOptions("PATCH", patch));
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
