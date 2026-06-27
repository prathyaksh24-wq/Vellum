import { invoke } from "@tauri-apps/api/core";

const status = document.querySelector("#status");
const openVellum = document.querySelector("#openVellum");
const enableComputer = document.querySelector("#enableComputer");
const disableComputer = document.querySelector("#disableComputer");
let computerUseEnabled = false;

function withTimeout(promise, label, timeoutMs = 8000) {
  let timeoutId;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => reject(new Error(`${label} timed out`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timeoutId));
}

async function postJson(path, body, timeoutMs = 8000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  const response = await fetch(`http://127.0.0.1:8000${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: controller.signal,
  }).finally(() => clearTimeout(timeoutId));
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || `request failed: ${response.status}`);
  }
  return payload;
}

async function setComputerOverlay(enabled) {
  try {
    await withTimeout(invoke("set_overlay", { enabled }), enabled ? "show overlay" : "hide overlay", 3000);
    return true;
  } catch {
    return false;
  }
}

async function runButton(button, label, action) {
  const previous = status.textContent;
  button.disabled = true;
  status.textContent = label;
  let result;
  try {
    result = await action();
  } catch (err) {
    status.textContent = err && err.message ? err.message : "desktop action failed";
    return;
  } finally {
    button.disabled = false;
  }
  if (result && result.message) {
    status.textContent = result.message;
  } else if (status.textContent === label) {
    status.textContent = previous;
  }
  return result;
}

async function refreshHealth() {
  try {
    const body = await invoke("backend_health");
    if (computerUseEnabled) {
      if (!body.ok) {
        status.textContent = "backend unreachable";
        return;
      }
      const session = await fetch("http://127.0.0.1:8000/api/computer-use/session/status").then((res) => res.json());
      computerUseEnabled = !!session.enabled;
      const guard = session.input_guard || {};
      status.textContent = guard.lease_active ? "computer use ready · Ctrl+Alt+Esc to stop" : "computer use waiting";
    } else {
      status.textContent = body.ok ? "backend ready" : "backend unreachable";
    }
  } catch {
    status.textContent = "backend unreachable";
  }
}

openVellum.addEventListener("click", () => {
  runButton(openVellum, "opening vellum", () => withTimeout(invoke("open_vellum_window"), "open vellum"));
});

enableComputer.addEventListener("click", async () => {
  await runButton(enableComputer, "enabling computer use", async () => {
    const overlayReady = await setComputerOverlay(true);
    let result;
    try {
      result = await postJson("/api/computer-use/session/start", { source: "tauri" });
    } catch (err) {
      await setComputerOverlay(false);
      throw err;
    }
    computerUseEnabled = true;
    if (!overlayReady) {
      result.message = `${result.message} Overlay warning: desktop glow did not confirm.`;
    }
    return result;
  });
});

disableComputer.addEventListener("click", async () => {
  await runButton(disableComputer, "disabling computer use", async () => {
    const result = await postJson("/api/computer-use/session/stop", { source: "tauri" });
    await setComputerOverlay(false);
    computerUseEnabled = false;
    return result;
  });
});

refreshHealth();
setInterval(refreshHealth, 5000);
