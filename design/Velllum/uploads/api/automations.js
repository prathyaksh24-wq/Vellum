(function () {
  var client = window.VellumApi.client;
  function withId(id) { return "/api/automations/" + encodeURIComponent(id); }
  window.VellumApi.automations = {
    list: function () { return client.request("/api/automations"); },
    create: function (payload) { return client.request("/api/automations", client.jsonOptions("POST", payload)); },
    update: function (id, payload) { return client.request(withId(id), client.jsonOptions("PATCH", payload)); },
    remove: function (id) { return client.request(withId(id), client.jsonOptions("DELETE")); },
    run: function (id) { return client.request(withId(id) + "/run", client.jsonOptions("POST")); },
    runs: function (id) { return client.request(withId(id) + "/runs"); },
    createPrompt: function () { return client.request("/api/automations/create-prompt"); },
  };
})();
