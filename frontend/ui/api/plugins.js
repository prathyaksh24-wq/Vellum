(function () {
  var client = window.VellumApi.client;
  window.VellumApi.plugins = {
    capabilities: function () { return client.request("/api/capabilities"); },
    list: function () { return client.request("/api/plugins"); },
    skills: function () { return client.request("/api/skills"); },
  };
})();
