(function () {
  var client = window.VellumApi.client;
  window.VellumApi.settings = {
    get: function () { return client.request("/api/settings"); },
    models: function () { return client.request("/api/models"); },
    memorySummary: function () { return client.request("/api/memory/summary"); },
    memoryRecent: function () {
      return window.VellumApi.settings.memorySummary().then(function (body) {
        var facts = [];
        if (body.global_summary) facts.push(body.global_summary);
        (body.saved_memories || []).forEach(function (item) {
          if (item && item.text) facts.push(item.text);
        });
        var entries = (body.saved_memories || []).slice();
        (body.recent_context || []).forEach(function (item) {
          if (item && item.content) {
            entries.push({
              id: "recent-" + (item.id || entries.length),
              kind: "recent",
              scope: "global",
              text: item.content,
              created_at: item.created,
              updated_at: item.created,
              source_thread_id: item.thread_id,
            });
          }
        });
        return { facts: facts, entries: entries, summary: body };
      });
    },
    memorySaved: function () {
      return client.request("/api/memory/saved").then(function (body) {
        var memories = body.memories || [];
        return { memories: memories, entries: memories };
      });
    },
    memoryEntries: function () {
      return client.request("/api/memory/archived").then(function (body) {
        var memories = body.memories || [];
        return { memories: memories, entries: memories };
      });
    },
    memoryDreamingStatus: function () { return client.request("/api/memory/dreaming/status"); },
    memoryDreamingRun: function () { return client.request("/api/memory/dreaming/run", client.jsonOptions("POST")); },
    memoryImportConversations: function () { return client.request("/api/memory/import-conversations", client.jsonOptions("POST")); },
    createMemory: function (payload) { return client.request("/api/memory", client.jsonOptions("POST", payload)); },
    updateMemory: function (id, payload) { return client.request("/api/memory/" + encodeURIComponent(id) + "/update", client.jsonOptions("POST", payload)); },
    archiveMemory: function (id) { return client.request("/api/memory/" + encodeURIComponent(id) + "/archive", client.jsonOptions("POST")); },
    deleteMemory: function (id) { return client.request("/api/memory/" + encodeURIComponent(id) + "/delete", client.jsonOptions("POST")); },
    pinMemory: function (id, pinned) { return client.request("/api/memory/" + encodeURIComponent(id) + "/pin", client.jsonOptions("POST", { pinned: !!pinned })); },
    memorySettings: function () { return client.request("/api/memory/settings"); },
    updateMemorySettings: function (patch) { return client.request("/api/memory/settings", client.jsonOptions("POST", patch)); },
    setActiveModel: function (model) {
      return client.request("/api/settings/active-model", client.jsonOptions("POST", { model: model }));
    },
    setProviderKey: function (provider, apiKey) {
      return client.request("/api/settings/provider-key", client.jsonOptions("POST", { provider: provider, api_key: apiKey }));
    },
  };
})();
