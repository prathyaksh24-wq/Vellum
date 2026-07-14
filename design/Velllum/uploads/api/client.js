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
        if (detail && typeof detail === "object") detail = detail.message || detail.code || JSON.stringify(detail);
      } catch (_) {}
      var error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    if (response.status === 204) return null;
    var text = await response.text();
    if (!text) return null;
    return JSON.parse(text);
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
