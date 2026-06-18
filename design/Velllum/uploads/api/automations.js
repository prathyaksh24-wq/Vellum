(function () {
  var client = window.VellumApi.client;
  window.VellumApi.automations = {
    list: function () { return client.request("/api/automations"); },
  };
})();
