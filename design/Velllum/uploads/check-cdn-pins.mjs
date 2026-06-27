// Fails when static HTML previews load mutable CDN build tools.
// Usage: node check-cdn-pins.mjs
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const roots = [
  join(process.cwd(), "frontend", "ui"),
  join(process.cwd(), "design", "Velllum", "uploads"),
];

const mutablePatterns = [
  "https://unpkg.com/react@18/umd/",
  "https://unpkg.com/react-dom@18/umd/",
  "https://unpkg.com/@babel/standalone/babel.min.js",
];

function htmlFiles(root) {
  const files = [];
  for (const name of readdirSync(root)) {
    const path = join(root, name);
    const stat = statSync(path);
    if (stat.isDirectory()) files.push(...htmlFiles(path));
    else if (name.endsWith(".html")) files.push(path);
  }
  return files;
}

const failures = [];
for (const root of roots) {
  for (const file of htmlFiles(root)) {
    const html = readFileSync(file, "utf8");
    for (const pattern of mutablePatterns) {
      if (html.includes(pattern)) failures.push(`${file}: mutable CDN URL ${pattern}`);
    }
  }
}

if (failures.length) {
  console.error("FAIL: static previews must pin React/Babel CDN versions");
  for (const failure of failures) console.error(failure);
  process.exit(1);
}

console.log("OK: static preview CDN build tools are pinned");
