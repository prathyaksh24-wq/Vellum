// `npm audit --audit-level=high`, except for advisories reviewed in
// .github/npm-audit-exceptions.txt (which must carry an unexpired date).
// Run from a package directory: node ../.github/scripts/npm-audit.mjs
import {execSync} from "node:child_process";
import {readFileSync} from "node:fs";
import {dirname, resolve} from "node:path";
import {fileURLToPath} from "node:url";

const exceptionsFile = resolve(dirname(fileURLToPath(import.meta.url)), "../npm-audit-exceptions.txt");
const lines = readFileSync(exceptionsFile, "utf8").split(/\r?\n/);
const expires = (lines.find(line => line.startsWith("# expires=")) || "").slice("# expires=".length).trim();
const today = new Date().toISOString().slice(0, 10);
if (!/^\d{4}-\d{2}-\d{2}$/.test(expires) || today > expires) {
  console.error(`npm audit exceptions expired or have no expiry: ${expires || "(none)"}`);
  process.exit(1);
}
const allowed = new Set(lines.map(line => line.trim()).filter(line => line && !line.startsWith("#")));

let report;
try {
  report = execSync("npm audit --json", {encoding: "utf8", maxBuffer: 64 * 1024 * 1024});
} catch (error) {
  report = error.stdout; // npm audit exits non-zero when it finds anything
}
const vulnerabilities = JSON.parse(report || "{}").vulnerabilities || {};
const blocking = new Map();
const excepted = new Set();
for (const [name, entry] of Object.entries(vulnerabilities)) {
  for (const via of entry.via || []) {
    if (typeof via !== "object" || !["high", "critical"].includes(via.severity)) continue;
    const id = String(via.url || "").split("/").pop();
    if (allowed.has(id)) excepted.add(id);
    else blocking.set(`${id || via.source} ${name}`, `${via.severity}: ${via.title} (${via.url})`);
  }
}
for (const id of excepted) console.log(`Allowed by .github/npm-audit-exceptions.txt: ${id}`);
if (blocking.size) {
  for (const [key, detail] of blocking) console.error(`${key} — ${detail}`);
  console.error(`${blocking.size} high or critical advisory finding(s) not covered by an exception.`);
  process.exit(1);
}
console.log("No high or critical advisories outside the reviewed exceptions.");
