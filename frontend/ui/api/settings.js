(function () {
  var client = window.VellumApi.client;
  window.VellumApi.settings = {
    get: function () { return client.request("/api/settings"); },
    models: function () { return client.request("/api/models"); },
    memoryRecent: function () {
      return client.request("/api/memory/summary").then(function (body) {
        var facts = [];
        if (body.global_summary) facts.push(body.global_summary);
        (body.saved_memories || []).forEach(function (item) {
          if (item && item.text) facts.push(item.text);
        });
        return { facts: facts, entries: body.saved_memories || [], summary: body };
      });
    },
    memoryEntries: function () {
      return client.request("/api/memory/archived").then(function (body) {
        return { entries: body.memories || [] };
      });
    },
    memoryDreamingStatus: function () { return client.request("/api/memory/dreaming/status"); },
    memoryDreamingRun: function () { return client.request("/api/memory/dreaming/run", client.jsonOptions("POST")); },
    setActiveModel: function (model) {
      return client.request("/api/settings/active-model", client.jsonOptions("POST", { model: model }));
    },
    setProviderKey: function (provider, apiKey) {
      return client.request("/api/settings/provider-key", client.jsonOptions("POST", { provider: provider, api_key: apiKey }));
    },
  };
})();
