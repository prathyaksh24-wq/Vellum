// Validates the embedded React/JSX in Vellum Default Re-designed.html compiles.
// Usage: node check-default.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const esbuild = await import(pathToFileURL(join(here, "../../../frontend/node_modules/esbuild/lib/main.js")).href);
const html = readFileSync(join(here, "Vellum Default Re-designed.html"), "utf8");
const settingsApi = readFileSync(join(here, "api/settings.js"), "utf8");

const m = html.match(/<script type="text\/babel"[^>]*>([\s\S]*?)<\/script>/);
if (!m) { console.error("FAIL: no <script type=text/babel> block found"); process.exit(1); }

try {
  await esbuild.transform(m[1], { loader: "jsx", jsx: "transform" });
  const requiredUi = [
    "galaxy-container",
    "Spotify connector",
    "routingStatus",
    "Provider routing",
    "Fallback chain",
    "Credential pools",
    "Latest route",
  ];
  const requiredApi = ["setGlobalRoutingPolicy", "setFallbacks", "setCredentialStrategy", "resetCredentialPool", "addCredential", "removeCredential"];
  for (const marker of requiredUi) {
    if (!html.includes(marker)) throw new Error(`missing routing UI marker: ${marker}`);
  }
  for (const marker of requiredApi) {
    if (!settingsApi.includes(marker)) throw new Error(`missing routing API method: ${marker}`);
  }
  if (/localStorage\.setItem\([^\n]*(credential|api.?key)/i.test(html)) {
    throw new Error("credential secrets must not be stored in localStorage");
  }
  console.log("OK: re-designed JSX and routing integration compile");
} catch (err) {
  console.error("FAIL: JSX did not compile");
  console.error(err.message || err);
  process.exit(1);
}
