// Validates the redesigned default UI compiles and uses the API client layer.
// Usage: node check-redesigned-default.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const esbuild = await import(pathToFileURL(join(here, "../../../frontend/node_modules/esbuild/lib/main.js")).href);
const html = readFileSync(join(here, "Vellum Default Re-designed.html"), "utf8");

const requiredScripts = [
  "api/client.js",
  "api/chat.js",
  "api/conversations.js",
  "api/plugins.js",
  "api/automations.js",
  "api/settings.js",
  "api/runtimes.js",
];

for (const src of requiredScripts) {
  const escaped = src.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  if (!new RegExp(`src="${escaped}(?:\\?[^\"]*)?"`).test(html)) {
    console.error(`FAIL: missing API module script: ${src}`);
    process.exit(1);
  }
}

const m = html.match(/<script type="text\/babel"[^>]*>([\s\S]*?)<\/script>/);
if (!m) {
  console.error("FAIL: no <script type=text/babel> block found");
  process.exit(1);
}

const script = m[1];
const required = [
  "const API = window.VellumApi;",
  "API.chat.stream",
  "API.conversations.list",
  "API.conversations.save",
  "API.settings.models",
  "API.settings.setActiveModel",
  "API.plugins.list",
  "API.automations.list",
  "API.runtimes.subagents",
  "FEATURE_FLAGS",
];

for (const needle of required) {
  if (!script.includes(needle)) {
    console.error(`FAIL: redesigned default UI missing backend wiring: ${needle}`);
    process.exit(1);
  }
}

try {
  await esbuild.transform(script, { loader: "jsx", jsx: "transform" });
  console.log("OK: redesigned default JSX compiles and API layer is wired");
} catch (err) {
  console.error("FAIL: redesigned default JSX did not compile");
  console.error(err.message || err);
  process.exit(1);
}
