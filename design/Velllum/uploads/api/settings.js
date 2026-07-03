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
        return { entries: body.memories || [] };
      });
    },
    memoryEntries: function () {
      return client.request("/api/memory/archived").then(function (body) {
        return { entries: body.memories || [] };
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
    routingStatus: function () { return client.request("/api/llm-routing/status"); },
    routingPolicies: function () { return client.request("/api/llm-routing/policies"); },
    setGlobalRoutingPolicy: function (policy) {
      return client.request("/api/llm-routing/policies/global", client.jsonOptions("PUT", policy));
    },
    routingFallbacks: function () { return client.request("/api/llm-routing/fallbacks"); },
    setFallbacks: function (targets) {
      return client.request("/api/llm-routing/fallbacks", client.jsonOptions("PUT", { targets: targets }));
    },
    routingCredentials: function () { return client.request("/api/llm-routing/credentials"); },
    addCredential: function (credential) {
      return client.request("/api/llm-routing/credentials", client.jsonOptions("POST", credential));
    },
    removeCredential: function (credentialId) {
      return client.request("/api/llm-routing/credentials/" + encodeURIComponent(credentialId), client.jsonOptions("DELETE"));
    },
    setCredentialStrategy: function (provider, strategy) {
      return client.request("/api/llm-routing/credentials/" + encodeURIComponent(provider) + "/strategy", client.jsonOptions("PUT", { strategy: strategy }));
    },
    resetCredentialPool: function (provider) {
      return client.request("/api/llm-routing/credentials/" + encodeURIComponent(provider) + "/reset", client.jsonOptions("POST"));
    },
    routingAttempts: function (limit, offset) {
      return client.request("/api/llm-routing/attempts?limit=" + encodeURIComponent(limit == null ? 50 : limit) + "&offset=" + encodeURIComponent(offset == null ? 0 : offset));
    },
  };
})();
