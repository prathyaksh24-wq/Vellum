(function () {
  var client = window.VellumApi.client;

  function catalog() {
    return client.request("/api/app-actions/catalog");
  }

  function dispatch(request, context) {
    return client.request(
      "/api/app-actions/dispatch",
      client.jsonOptions("POST", { request: request, context: context }),
    );
  }

  function undo(token, context) {
    return client.request(
      "/api/app-actions/undo",
      client.jsonOptions("POST", { token: token, context: context }),
    );
  }

  window.VellumApi.appActions = {
    catalog: catalog,
    dispatch: dispatch,
    undo: undo,
  };
})();
