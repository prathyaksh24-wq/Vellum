(function () {
  function backendBase() {
    var stored = "";
    try { stored = localStorage.getItem("vellum-backend-url") || ""; } catch (_) {}
    var base = stored || window.VELLUM_BACKEND_URL || "http://127.0.0.1:8000";
    return String(base).trim().replace(/\/+$/, "");
  }

  async function request(path, options) {
    var response = await fetch(backendBase() + path, options || {});
    if (!response.ok) {
      var detail = "HTTP " + response.status;
      try {
        var body = await response.json();
        detail = body.detail || body.message || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    return response.json();
  }

  function jsonOptions(method, body, signal) {
    return {
      method: method,
      signal: signal,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    };
  }

  window.VellumApi = window.VellumApi || {};
  window.VellumApi.client = { backendBase: backendBase, request: request, jsonOptions: jsonOptions };
})();
