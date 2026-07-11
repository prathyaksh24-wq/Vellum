// Deterministic contract check for the redesigned knowledge API client.
// Usage: node check-knowledge.mjs
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = fileURLToPath(new URL(".", import.meta.url));
const requests = [];
const fakeFetch = async (url, options = {}) => {
  const parsed = new URL(url);
  requests.push({path: parsed.pathname + parsed.search, method: options.method || "GET", body: options.body});
  let body = {};
  if (parsed.pathname === "/api/knowledge/query") body = {results: [{ref: "Knowledge/concept/example", title: "Example"}]};
  if (parsed.pathname === "/api/knowledge/pages/Knowledge%2Fconcept%2Fexample") body = {ref: "Knowledge/concept/example", title: "Example", content: "Content"};
  return {ok: true, status: 200, async json() { return body; }, async text() { return JSON.stringify(body); }};
};

const context = {
  window: {VellumApi: {}},
  localStorage: {getItem() { return "http://127.0.0.1:8000"; }},
  fetch: fakeFetch,
  URLSearchParams,
  encodeURIComponent,
};
vm.runInNewContext(readFileSync(join(here, "client.js"), "utf8"), context);
vm.runInNewContext(readFileSync(join(here, "knowledge.js"), "utf8"), context);

const api = context.window.VellumApi.knowledge;
await api.status();
await api.query("memory & wiki", 4);
await api.page("Knowledge/concept/example");
await api.lint(30);
await api.indexRebuild();

const paths = requests.map(request => request.path);
const methods = requests.map(request => request.method);
for (const required of [
  "/api/knowledge/status",
  "/api/knowledge/query?q=memory+%26+wiki&limit=4",
  "/api/knowledge/pages/Knowledge%2Fconcept%2Fexample",
  "/api/knowledge/lint",
  "/api/knowledge/rebuild-index",
]) {
  if (!paths.includes(required)) throw new Error(`missing request: ${required}`);
}
if (methods[3] !== "POST" || methods[4] !== "POST") throw new Error("knowledge mutations must use POST");
const lintRequest = requests.find(request => request.path === "/api/knowledge/lint");
if (JSON.parse(lintRequest.body).stale_days !== 30) throw new Error("lint stale_days was not forwarded");
console.log("OK: knowledge client contracts verified");
