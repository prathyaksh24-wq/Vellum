// Validates the embedded React/JSX in Vellum Default Re-designed.html compiles.
// Usage: node check-default.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const esbuild = await import(pathToFileURL(join(here, "../../../frontend/node_modules/esbuild/lib/main.js")).href);
const html = readFileSync(join(here, "Vellum Default Re-designed.html"), "utf8");
const clientApi = readFileSync(join(here, "api/client.js"), "utf8");
const settingsApi = readFileSync(join(here, "api/settings.js"), "utf8");

const m = html.match(/<script type="text\/babel"[^>]*>([\s\S]*?)<\/script>/);
if (!m) { console.error("FAIL: no <script type=text/babel> block found"); process.exit(1); }

try {
  await esbuild.transform(m[1], { loader: "jsx", jsx: "transform" });
  const requiredUi = [
    "galaxy-container",
    "Spotify connector",
    "Provider routing, fallback models, and credential pools are managed by Vellum's backend.",
    "api/client.js?v=20260710-routing-actions",
    "api/settings.js?v=20260710-backend-routing",
  ];
  for (const marker of requiredUi) {
    if (!html.includes(marker)) throw new Error(`missing routing UI marker: ${marker}`);
  }
  if (/localStorage\.setItem\([^\n]*(credential|api.?key)/i.test(html)) {
    throw new Error("credential secrets must not be stored in localStorage");
  }
  if (html.includes('<select className="agent-select"')) {
    throw new Error("routing dropdowns must reuse VSelect instead of native selects");
  }
  for (const marker of ["Provider optimization", "Fallback chain", "Credential pools", "routingStatus", "setGlobalRoutingPolicy", "setCredentialStrategy"]) {
    if (html.includes(marker) || settingsApi.includes(marker)) {
      throw new Error(`routing controls must stay backend-owned, found frontend marker: ${marker}`);
    }
  }
  for (const legacyId of ["deepseek/deepseek-chat", "minimax/minimax-01", "google/gemma-3-27b-it"]) {
    if (html.includes(`id: '${legacyId}'`) || html.includes(`id:"${legacyId}"`)) {
      throw new Error(`legacy fallback model id remains in static picker: ${legacyId}`);
    }
  }
  if (!clientApi.includes("response.status === 204")) {
    throw new Error("API client must handle 204 No Content responses");
  }
  console.log("OK: re-designed JSX and routing integration compile");
} catch (err) {
  console.error("FAIL: JSX did not compile");
  console.error(err.message || err);
  process.exit(1);
}
