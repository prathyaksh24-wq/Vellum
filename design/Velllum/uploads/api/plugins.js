(function () {
  var client = window.VellumApi.client;
  window.VellumApi.plugins = {
    list: function () { return client.request("/api/plugins"); },
    skills: function () { return client.request("/api/skills"); },
    capabilities: function () { return client.request("/api/capabilities"); },
  };
})();
