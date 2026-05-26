import { invoke } from "@tauri-apps/api/core";

const status = document.querySelector("#status");
const openVellum = document.querySelector("#openVellum");
const enableComputer = document.querySelector("#enableComputer");
const testComputer = document.querySelector("#testComputer");
const disableComputer = document.querySelector("#disableComputer");

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
    status.textContent = body.ok ? "backend ready" : "backend unreachable";
  } catch {
    status.textContent = "backend unreachable";
  }
}

openVellum.addEventListener("click", () => {
  runButton(openVellum, "opening vellum", () => withTimeout(invoke("open_vellum_window"), "open vellum"));
});

enableComputer.addEventListener("click", async () => {
  await runButton(enableComputer, "enabling computer use", async () => {
    return postJson("/api/computer-use/enable", { source: "tauri" });
  });
});

testComputer.addEventListener("click", async () => {
  await runButton(testComputer, "starting visible control test", async () => {
    await postJson("/api/computer-use/enable", { source: "tauri", task: "visible desktop control test" });
    return postJson("/api/computer-use/desktop/demo", { source: "tauri", confirm: true });
  });
});

disableComputer.addEventListener("click", async () => {
  await runButton(disableComputer, "disabling computer use", async () => {
    return postJson("/api/computer-use/disable", { source: "tauri" });
  });
});

refreshHealth();
setInterval(refreshHealth, 5000);
