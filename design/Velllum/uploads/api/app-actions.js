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

  function confirm(token, request, context) {
    return client.request(
      "/api/app-actions/confirm",
      client.jsonOptions("POST", { token: token, request: request, context: context }),
    );
  }

  function cancel(token, context) {
    return client.request(
      "/api/app-actions/cancel",
      client.jsonOptions("POST", { token: token, context: context }),
    );
  }

  function prepareAttachments(uploads, existingDigests) {
    return client.request(
      "/api/app-actions/attachments/prepare",
      client.jsonOptions("POST", { uploads: uploads, existing_digests: existingDigests || [] }),
    );
  }

  window.VellumApi.appActions = {
    catalog: catalog,
    dispatch: dispatch,
    confirm: confirm,
    cancel: cancel,
    undo: undo,
    prepareAttachments: prepareAttachments,
  };
})();

// How agent terminal commands are approved (changed with terminal.approval.set).
(function () {
  var client = window.VellumApi.client;
  window.VellumApi.terminal = Object.assign(window.VellumApi.terminal || {}, {
    approval: function () { return client.request("/api/terminal/approval", {cache: "no-store"}); },
  });
})();
