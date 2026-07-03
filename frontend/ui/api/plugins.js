(function () {
  var client = window.VellumApi.client;
  window.VellumApi.plugins = {
    list: function () { return client.request("/api/plugins"); },
    skills: function () { return client.request("/api/skills"); },
    skillAction: function (payload) {
      return client.request("/api/skills/action", client.jsonOptions("POST", payload));
    },
    skillLearn: function (source) {
      return client.request("/api/skills/learn", client.jsonOptions("POST", { source: source }));
    },
    skillBundle: function (payload) {
      return client.request("/api/skills/bundles", client.jsonOptions("POST", payload));
    },
    skillHub: function (payload) {
      return client.request("/api/skills/hub", client.jsonOptions("POST", payload));
    },
    skillCurator: function (payload) {
      return client.request("/api/skills/curator", client.jsonOptions("POST", payload));
    },
  };
})();
