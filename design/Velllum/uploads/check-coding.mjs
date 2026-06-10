// Validates the embedded React/JSX in vellum-coding.html compiles.
// Usage: node check-coding.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const esbuild = await import(pathToFileURL(join(here, "../../../frontend/node_modules/esbuild/lib/main.js")).href);
const html = readFileSync(join(here, "vellum-coding.html"), "utf8");

const m = html.match(/<script type="text\/babel"[^>]*>([\s\S]*?)<\/script>/);
if (!m) { console.error("FAIL: no <script type=text/babel> block found"); process.exit(1); }

try {
  await esbuild.transform(m[1], { loader: "jsx", jsx: "transform" });
  console.log("OK: JSX compiles");
} catch (err) {
  console.error("FAIL: JSX did not compile");
  console.error(err.message || err);
  process.exit(1);
}
