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
    // -- About you, topics, growth, import/export -----------------------------
    memoryAboutYou: function () { return client.request("/api/memory/about-you"); },
    // Streams the About-you summary. onEvent(name, data) receives status, delta,
    // summary, error and done; resolves with the final summary (or null).
    memoryAboutYouStream: async function (options) {
      options = options || {};
      var onEvent = options.onEvent || function () {};
      var response = await fetch(client.backendBase() + "/api/memory/about-you/stream?force=" + (options.force ? "true" : "false"), {
        method: "POST", signal: options.signal, headers: { Accept: "text/event-stream" },
      });
      if (!response.ok || !response.body) {
        var failure = new Error("The summary could not be loaded. HTTP " + response.status);
        failure.status = response.status;
        throw failure;
      }
      var reader = response.body.getReader(), decoder = new TextDecoder(), buffer = "", summary = null;
      var dispatch = function (block) {
        var name = "message", data = "";
        block.split(/\r?\n/).forEach(function (line) {
          if (line.indexOf("event:") === 0) name = line.slice(6).trim();
          else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
        });
        var payload = {};
        try { payload = data ? JSON.parse(data) : {}; } catch (_) { return; }
        if (name === "summary") summary = payload.summary || null;
        onEvent(name, payload);
      };
      for (;;) {
        var chunk = await reader.read();
        buffer += chunk.done ? decoder.decode() : decoder.decode(chunk.value, { stream: true });
        var blocks = buffer.split(/\r?\n\r?\n/);
        buffer = chunk.done ? "" : blocks.pop();
        blocks.forEach(function (block) { if (block.trim()) dispatch(block); });
        if (chunk.done) break;
      }
      return summary;
    },
    memoryCorrect: function (payload) { return client.request("/api/memory/about-you/correct", client.jsonOptions("POST", payload)); },
    memorySuppress: function (payload) { return client.request("/api/memory/suppress", client.jsonOptions("POST", payload)); },
    memoryFeedback: function (memoryId, relevant) {
      return client.request("/api/memory/feedback", client.jsonOptions("POST", { memory_id: memoryId, relevant: !!relevant }));
    },
    memoryUndoSave: function (text, threadId) {
      return client.request("/api/memory/undo-save", client.jsonOptions("POST", { text: text, thread_id: threadId || "" }));
    },
    memoryAsk: function (text) { return client.request("/api/memory/ask", client.jsonOptions("POST", { text: text })); },
    memoryTopics: function () { return client.request("/api/memory/topics"); },
    memoryGrowth: function () { return client.request("/api/memory/growth"); },
    memoryImportPrompt: function () { return client.request("/api/memory/import/prompt"); },
    memoryImportPlan: function (text) { return client.request("/api/memory/import/plan", client.jsonOptions("POST", { text: text })); },
    // Returns 428 until the user confirms; the page applies imports through the
    // memory.import.apply App Action, which carries that confirmation.
    memoryImportApply: function (items) { return client.request("/api/memory/import/apply", client.jsonOptions("POST", { items: items })); },
    memoryExport: async function () {
      var response = await fetch(client.backendBase() + "/api/memory/export");
      if (!response.ok) throw new Error("The export could not be created. HTTP " + response.status);
      var disposition = response.headers.get("Content-Disposition") || "";
      var match = disposition.match(/filename="?([^";]+)"?/);
      return { blob: await response.blob(), filename: match ? match[1] : "vellum-memory.zip" };
    },
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
