(function () {
  var client = window.VellumApi.client;

  // Read-only analytics: run summaries, traces and context-window shapes.
  // Everything here is metadata; no prompt or answer text is returned.
  window.VellumApi.observability = {
    summary: function (period) {
      return client.request("/api/observability/summary?period=" + encodeURIComponent(period || "7d"), {cache: "no-store"});
    },
    runs: function (limit) {
      return client.request("/api/observability/runs?limit=" + encodeURIComponent(limit || 40), {cache: "no-store"});
    },
    trace: function (responseId) {
      return client.request("/api/observability/runs/" + encodeURIComponent(responseId) + "/trace", {cache: "no-store"});
    },
    threadContext: function (threadId) {
      return client.request("/api/observability/context?thread_id=" + encodeURIComponent(threadId), {cache: "no-store"});
    },
    health: function () { return client.request("/api/health"); },
    models: function () { return client.request("/api/models"); },
    streamUrl: function (lastEventId) {
      return client.backendBase() + "/api/observability/stream?last_event_id=" + encodeURIComponent(lastEventId || 0);
    },
  };
})();
