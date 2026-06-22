(function () {
  var client = window.VellumApi.client;
  window.VellumApi.settings = {
    get: function () { return client.request("/api/settings"); },
    models: function () { return client.request("/api/models"); },
    memoryRecent: function (limit) { return client.request("/api/memory/recent?limit=" + encodeURIComponent(limit || 15)); },
    memoryEntries: function (limit) { return client.request("/api/memory/entries?limit=" + encodeURIComponent(limit || 30)); },
    setActiveModel: function (model) {
      return client.request("/api/settings/active-model", client.jsonOptions("POST", { model: model }));
    },
    setProviderKey: function (provider, apiKey) {
      return client.request("/api/settings/provider-key", client.jsonOptions("POST", { provider: provider, api_key: apiKey }));
    },
  };
})();
