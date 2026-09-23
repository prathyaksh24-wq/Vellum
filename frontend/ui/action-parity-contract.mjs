import {createHash} from "node:crypto";
import {existsSync, readFileSync} from "node:fs";
import {createRequire} from "node:module";
import {dirname, resolve} from "node:path";

// Vite's React plugin already depends on Babel. Parse the *served* JSX, not a
// hand-maintained list of controls or the obsolete preview HTML files.
const require = createRequire(import.meta.url);
const babel = createRequire(require.resolve("@vitejs/plugin-react"))("@babel/core");
function findRoot() {
  let directory = process.cwd();
  while (!existsSync(resolve(directory, "frontend", "ui", "action-parity.inventory.json"))) {
    const parent = dirname(directory);
    if (parent === directory) throw new Error("Could not find Action Parity inventory");
    directory = parent;
  }
  return directory;
}

export const root = findRoot();
export const SOURCE_FILES = [
  "design/Velllum/uploads/Vellum Default Re-designed.html",
  "design/Velllum/uploads/vellum-workspace.html",
  "design/Velllum/uploads/components/v-select.jsx",
  "design/Velllum/uploads/components/books-view.jsx",
];

export function jsxSource(path, content) {
  if (!path.endsWith(".html")) return content;
  const scripts = [...content.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)]
    .filter(match => /\btype\s*=\s*["']text\/babel["']/i.test(match[1]) && !/\bsrc\s*=/i.test(match[1]));
  if (scripts.length !== 1) throw new Error(`Expected one reviewed inline React script in ${path}; found ${scripts.length}`);
  return scripts[0][2];
}

function visit(node, parent, callback) {
  if (!node || typeof node !== "object") return;
  if (Array.isArray(node)) {
    for (const child of node) visit(child, parent, callback);
    return;
  }
  if (typeof node.type !== "string") return;
  callback(node, parent);
  for (const [key, value] of Object.entries(node)) {
    if (key === "loc" || key === "comments" || key === "tokens" || key === "extra") continue;
    if (value && typeof value === "object") visit(value, node, callback);
  }
}

export function visualHandlers(path, content) {
  const source = jsxSource(path, content);
  const parsed = babel.parseSync(source, {
    babelrc: false,
    configFile: false,
    parserOpts: {sourceType: "unambiguous", plugins: ["jsx"]},
  });
  const handlers = [];
  visit(parsed, null, (node, parent) => {
    if (node.type !== "JSXAttribute" || !/^on[A-Z]/.test(node.name?.name || "")) return;
    if (node.value?.type !== "JSXExpressionContainer") return;
    const tag = parent?.name?.name || parent?.name?.property?.name || "unknown";
    const expression = source.slice(node.value.start, node.value.end).replace(/\s+/g, " ").trim();
    handlers.push(`${tag}|${node.name.name}|${expression}`);
  });
  return handlers.sort();
}

export function fingerprint(path, content) {
  const handlers = visualHandlers(path, content);
  return {
    count: handlers.length,
    sha256: createHash("sha256").update(handlers.join("\n")).digest("hex"),
  };
}

export function servedSources() {
  return Object.fromEntries(SOURCE_FILES.map(path => [path, readFileSync(resolve(root, path), "utf8")]));
}

export function validateParityInventory(inventory, sources = servedSources()) {
  const errors = [];
  const servedExternalSources = new Set();
  for (const path of SOURCE_FILES.filter(item => item.endsWith(".html"))) {
    const html = sources[path];
    for (const match of html.matchAll(/<script\b([^>]*)>/gi)) {
      if (!/\btype\s*=\s*["']text\/babel["']/i.test(match[1])) continue;
      const source = match[1].match(/\bsrc\s*=\s*["']([^"']+)["']/i)?.[1];
      if (!source) continue;
      const referenced = resolve(root, "design/Velllum/uploads", source).replaceAll("\\", "/");
      const expected = resolve(root, "design/Velllum/uploads").replaceAll("\\", "/") + "/";
      const relative = "design/Velllum/uploads/" + referenced.slice(expected.length);
      if (!referenced.startsWith(expected) || !SOURCE_FILES.includes(relative)) {
        errors.push(`${path}: unreviewed served React source ${source}`);
      } else {
        servedExternalSources.add(relative);
      }
    }
  }
  for (const path of SOURCE_FILES.filter(item => item.endsWith(".jsx"))) {
    if (!servedExternalSources.has(path)) errors.push(`${path}: reviewed React source is no longer served`);
  }
  for (const path of SOURCE_FILES) {
    const expected = inventory.handlerFingerprints[path];
    if (!expected) {
      errors.push(`${path}: missing handler fingerprint`);
      continue;
    }
    const actual = fingerprint(path, sources[path]);
    if (actual.count !== expected.count || actual.sha256 !== expected.sha256) {
      errors.push(`${path}: visual handlers changed (${expected.count} -> ${actual.count}); review each added/changed control for App Action parity, then update the inventory`);
    }
  }
  for (const path of Object.keys(inventory.handlerFingerprints)) {
    if (!SOURCE_FILES.includes(path)) errors.push(`${path}: no longer a served JSX source`);
  }
  for (const control of inventory.covered) {
    if (!control.surface || !control.name || !control.actionId || !control.probe?.path || !control.probe?.text) {
      errors.push(`Incomplete covered control ${JSON.stringify(control)}`);
      continue;
    }
    const content = sources[control.probe.path] ?? readFileSync(resolve(root, control.probe.path), "utf8");
    if (!content.includes(control.probe.text)) {
      errors.push(`${control.surface}/${control.name}: missing source probe ${JSON.stringify(control.probe.text)}`);
    }
  }
  return errors;
}
