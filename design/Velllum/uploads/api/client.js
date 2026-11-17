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

  // --- Backend availability -------------------------------------------------
  // The window opens before the backend is ready, and the desktop host restarts
  // a backend that crashes or hangs. Reads wait for it instead of failing, so
  // nothing ends up empty because it was requested a moment too early.
  function backendWaitMs() {
    if (typeof window.VELLUM_BACKEND_WAIT_MS === "number") return window.VELLUM_BACKEND_WAIT_MS;
    return /jsdom/i.test(navigator.userAgent || "") ? 0 : 120000;
  }
  var online = null; // null: not yet known, true: answering, false: unreachable
  var probe = null;

  function emit(name, detail) {
    try { window.dispatchEvent(new CustomEvent(name, { detail: detail })); } catch (_) {}
  }

  function markOnline() {
    var wasOffline = online === false;
    online = true;
    if (wasOffline) emit("vellum:backend-online");
  }

  function sleep(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }

  function waitForBackend(signal) {
    if (!probe) {
      probe = (async function () {
        var deadline = Date.now() + backendWaitMs();
        var pause = 250;
        while (Date.now() < deadline) {
          try {
            var response = await fetch(backendBase() + "/health", { cache: "no-store", signal: AbortSignal.timeout(3000) });
            if (response.ok) { markOnline(); return true; }
          } catch (_) {}
          await sleep(pause);
          pause = Math.min(pause * 2, 2000);
        }
        return false;
      })().finally(function () { probe = null; });
    }
    if (!signal) return probe;
    return Promise.race([probe, new Promise(function (_, reject) {
      if (signal.aborted) reject(signal.reason);
      signal.addEventListener("abort", function () { reject(signal.reason); }, { once: true });
    })]);
  }

  function isNetworkFailure(error) {
    return Boolean(error) && error.name === "TypeError";
  }

  function methodOf(options) {
    return String((options && options.method) || "GET").toUpperCase();
  }

  async function send(path, options) {
    var reads = methodOf(options) === "GET" || methodOf(options) === "HEAD";
    for (var attempt = 0; ; attempt++) {
      // Writes are held until the backend answers rather than sent into a
      // closed port; they are never re-sent once they may have arrived.
      if (online === false && backendWaitMs() > 0) {
        if (!(await waitForBackend(options && options.signal))) break;
      }
      try {
        var response = await fetch(backendBase() + path, options || {});
        markOnline();
        return response;
      } catch (error) {
        if (!isNetworkFailure(error) || backendWaitMs() <= 0) throw error;
        online = false;
        if (!reads || attempt >= 3) throw error;
        if (!(await waitForBackend(options && options.signal))) throw error;
      }
    }
    throw new TypeError("The Vellum backend is not reachable.");
  }

  async function parse(response) {
    if (!response.ok) {
      var detail = "HTTP " + response.status;
      var errorDetail = null;
      try {
        var body = await response.json();
        errorDetail = body.detail || body.message || null;
        detail = errorDetail || detail;
        if (detail && typeof detail === "object") detail = detail.message || detail.code || JSON.stringify(detail);
      } catch (_) {}
      var error = new Error(detail);
      error.status = response.status;
      error.detail = errorDetail;
      throw error;
    }
    if (response.status === 204) return null;
    var text = await response.text();
    if (!text) return null;
    return JSON.parse(text);
  }

  // --- Last-known snapshots ---------------------------------------------------
  // The lists people see first are remembered on this device, so the app shows
  // chats, plugins, skills and music the moment it opens. Fresh data replaces
  // them as soon as the backend answers ("vellum:data-refreshed").
  var SNAPSHOT_PREFIX = "vellum-api-snapshot-v1:";
  var SNAPSHOT_PATHS = [
    /^\/api\/conversations$/,
    /^\/api\/conversations\/library(\?include_messages=false)?$/,
    /^\/api\/plugins$/,
    /^\/api\/skills$/,
    /^\/api\/skills\/v2\/catalog\?view=installed&/,
    /^\/api\/models$/,
    /^\/api\/settings$/,
    /^\/api\/subagents$/,
    /^\/api\/automations$/,
    /^\/api\/music\/local\/library$/,
    /^\/api\/accounts\/status$/,
    /^\/api\/app-actions\/catalog$/,
  ];
  var SNAPSHOT_GRACE_MS = 300;
  var MAX_SNAPSHOT_CHARS = 2000000;

  function snapshotable(path, options) {
    return methodOf(options) === "GET" && SNAPSHOT_PATHS.some(function (pattern) { return pattern.test(path); });
  }

  function snapshot(path) {
    try {
      var raw = localStorage.getItem(SNAPSHOT_PREFIX + path);
      return raw ? JSON.parse(raw).data : undefined;
    } catch (_) { return undefined; }
  }

  function remember(path, data) {
    try {
      var text = JSON.stringify({ saved_at: Date.now(), data: data });
      if (text.length <= MAX_SNAPSHOT_CHARS) localStorage.setItem(SNAPSHOT_PREFIX + path, text);
      else localStorage.removeItem(SNAPSHOT_PREFIX + path);
    } catch (_) {}
  }

  async function request(path, options) {
    if (!snapshotable(path, options)) return parse(await send(path, options));
    var live = send(path, options).then(parse).then(function (data) { remember(path, data); return data; });
    var cached = online === true ? undefined : snapshot(path);
    if (cached === undefined) return live;
    // Use the live answer when it is quick; otherwise show the last known data
    // now and announce the fresh copy when it arrives.
    var quick = live.then(function (data) { return { data: data }; }, function (error) { return { error: error }; });
    var first = await Promise.race([quick, sleep(SNAPSHOT_GRACE_MS).then(function () { return null; })]);
    if (first) {
      if (first.error && !isNetworkFailure(first.error)) throw first.error;
      if (!first.error) return first.data;
    }
    quick.then(function (result) {
      if (result && !result.error) emit("vellum:data-refreshed", { path: path });
    });
    return cached;
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
  window.VellumApi.client = {
    backendBase: backendBase,
    request: request,
    jsonOptions: jsonOptions,
    snapshot: snapshot,
    waitForBackend: waitForBackend,
    get online() { return online; },
  };
})();
