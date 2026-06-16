(function () {
  var client = window.VellumApi.client;
  window.VellumApi.runtimes = {
    subagents: function () { return client.request("/api/subagents"); },
    computerUseStatus: function () { return client.request("/api/computer-use/status"); },
    enableComputerUse: function (threadId, task) {
      return client.request("/api/computer-use/enable", client.jsonOptions("POST", { thread_id: threadId || null, source: "ui", task: task || null }));
    },
    disableComputerUse: function () {
      return client.request("/api/computer-use/disable", client.jsonOptions("POST", { source: "ui" }));
    },
  };
})();
