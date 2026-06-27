// Validates vellum-workspace.html compiles and handles backend agent events.
// Usage: node check-workspace.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const esbuild = await import(pathToFileURL(join(here, "../../../frontend/node_modules/esbuild/lib/main.js")).href);
const html = readFileSync(join(here, "vellum-workspace.html"), "utf8");

const m = html.match(/<script type="text\/babel"[^>]*>([\s\S]*?)<\/script>/);
if (!m) {
  console.error("FAIL: no <script type=text/babel> block found");
  process.exit(1);
}

const script = m[1];
const required = [
  'ev==="tool"',
  'ev==="activity"',
  'ev==="source"',
  "mergeSourceList(sources, j)",
  "activity.concat([{label:j.label",
  "status:\"running\"",
];

for (const needle of required) {
  if (!script.includes(needle)) {
    console.error(`FAIL: missing workspace backend event handling: ${needle}`);
    process.exit(1);
  }
}

try {
  await esbuild.transform(script, { loader: "jsx", jsx: "transform" });
  console.log("OK: workspace JSX compiles and backend events are wired");
} catch (err) {
  console.error("FAIL: workspace JSX did not compile");
  console.error(err.message || err);
  process.exit(1);
}
