(function () {
  function loopbackBackendOverride() {
    try {
      var loopback = ["localhost", "127.0.0.1", "::1", "[::1]"];
      if (loopback.indexOf(window.location.hostname.toLowerCase()) < 0) return "";
      var requested = new URLSearchParams(window.location.search).get("backend");
      if (!requested) return "";
      var target = new URL(requested);
      if (loopback.indexOf(target.hostname.toLowerCase()) < 0) return "";
      if (target.protocol !== "http:" && target.protocol !== "https:") return "";
      return target.origin;
    } catch (_) {
      return "";
    }
  }

  function backendBase() {
    var stored = "";
    try { stored = localStorage.getItem("vellum-backend-url") || ""; } catch (_) {}
    var base = loopbackBackendOverride() || stored || window.VELLUM_BACKEND_URL || "http://127.0.0.1:8000";
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
