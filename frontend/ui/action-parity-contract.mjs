import {createHash} from "node:crypto";
import {existsSync, readFileSync} from "node:fs";
import {createRequire} from "node:module";
import {dirname, resolve} from "node:path";
import {JSDOM} from "jsdom";

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
export const MODULE_SOURCE_FILES = [
  "design/Velllum/uploads/books-entry.js",
  "design/Velllum/uploads/components/book-upload-entry.jsx",
  "design/Velllum/uploads/components/attachment-upload.tsx",
  "design/Velllum/uploads/components/attachment-upload-support.jsx",
  "design/Velllum/uploads/components/bookshelf/VellumBookshelf.tsx",
  "design/Velllum/uploads/components/bookshelf/VellumRuntime.tsx",
  "design/Velllum/uploads/components/bookshelf/SuppliedBooksPage.tsx",
  "design/Velllum/uploads/components/bookshelf/components/BriefingBookshelf.tsx",
  "design/Velllum/uploads/components/bookshelf/components/BriefingOpenOverlay.tsx",
  "design/Velllum/uploads/components/bookshelf/components/ImportBooksDialog.tsx",
  "design/Velllum/uploads/components/bookshelf/reader/BookReader.tsx",
  "design/Velllum/uploads/components/bookshelf/components/ui/button.tsx",
  "design/Velllum/uploads/components/bookshelf/components/ui/dialog.tsx",
  "design/Velllum/uploads/components/bookshelf/components/ui/input.tsx",
  "design/Velllum/uploads/components/bookshelf/components/ui/label.tsx",
  "design/Velllum/uploads/components/bookshelf/components/ui/tabs.tsx",
  "design/Velllum/uploads/components/bookshelf/components/ui/textarea.tsx",
];
export const SOURCE_FILES = [
  ...MODULE_SOURCE_FILES,
  "design/Velllum/uploads/components/asana.jsx",
  "design/Velllum/uploads/components/swiggy.jsx",
  "design/Velllum/uploads/components/zomato.jsx",
  "design/Velllum/uploads/components/district.jsx",
  "design/Velllum/uploads/components/plugin-workspace.jsx",
  "design/Velllum/uploads/Vellum Default Re-designed.html",
  "design/Velllum/uploads/vellum-workspace.html",
  "design/Velllum/uploads/components/v-select.jsx",
  "design/Velllum/uploads/components/accounts.jsx",
  "design/Velllum/uploads/components/books-view.jsx",
  "design/Velllum/uploads/components/calendar-workspace.jsx",
  "design/Velllum/uploads/components/browser-panel.jsx",
  "design/Velllum/uploads/components/browser-settings.jsx",
  "design/Velllum/uploads/components/dictation-settings.jsx",
  "design/Velllum/uploads/components/plugin-add.jsx",
  "design/Velllum/uploads/components/product-hunt.jsx",
  "design/Velllum/uploads/components/linear.jsx",
  "design/Velllum/uploads/components/github.jsx",
  "design/Velllum/uploads/components/airtable.jsx",
  "design/Velllum/uploads/components/notion.jsx",
  "design/Velllum/uploads/components/firecrawl.jsx",
  "design/Velllum/uploads/components/apify.jsx",
  "design/Velllum/uploads/components/serpapi.jsx",
  "design/Velllum/uploads/components/supabase.jsx",
  "design/Velllum/uploads/components/vercel.jsx",
  "design/Velllum/uploads/components/clickup.jsx",
  "design/Velllum/uploads/components/hubspot.jsx",
  "design/Velllum/uploads/components/exa.jsx",
  "design/Velllum/uploads/components/tavily.jsx",
  "design/Velllum/uploads/components/web-search-settings.jsx",
  "design/Velllum/uploads/components/slack.jsx",
  "design/Velllum/uploads/components/google-connections.jsx",
  "design/Velllum/uploads/components/youtube-history.jsx",
  "design/Velllum/uploads/components/music-page.jsx",
  "design/Velllum/uploads/components/local-music.jsx",
  "design/Velllum/uploads/components/automation-notifications.jsx",
  "design/Velllum/uploads/components/PatternWaves.jsx",
  "design/Velllum/uploads/components/Particles.jsx",
  "design/Velllum/uploads/components/DvkMotionBackground.jsx",
  "design/Velllum/uploads/components/settings-overview.jsx",
  "design/Velllum/uploads/components/thinking-orbs.jsx",
  "design/Velllum/uploads/components/response-progress.js",
  "design/Velllum/uploads/components/agent-response.js",
  "design/Velllum/uploads/components/streaming-text.js",
  "design/Velllum/uploads/components/morphic-ui.js",
];

function reactScripts(content) {
  const document = new JSDOM(content).window.document;
  return [...document.querySelectorAll("script")]
    .filter(script => script.getAttribute("type")?.toLowerCase() === "text/babel");
}

export function jsxSource(path, content) {
  if (!path.endsWith(".html")) return content;
  const scripts = reactScripts(content).filter(script => !script.hasAttribute("src"));
  if (scripts.length !== 1) throw new Error(`Expected one reviewed inline React script in ${path}; found ${scripts.length}`);
  return scripts[0].textContent;
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
    parserOpts: {sourceType: "unambiguous", plugins: ["jsx", ...(path.endsWith('.tsx') ? ['typescript'] : [])]},
  });
  const handlers = [];
  visit(parsed, null, (node, parent) => {
    if (/(?:agent-response|streaming-text|morphic-ui)\.js$/.test(path) && node.type === 'ObjectProperty' && /^on[A-Z]/.test(node.key?.name || '')) {
      handlers.push(`createElement|${node.key.name}|${source.slice(node.value.start,node.value.end).replace(/\s+/g,' ').trim()}`);
      return;
    }
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
    for (const script of reactScripts(sources[path])) {
      const source = script.getAttribute("src")?.split(/[?#]/,1)[0];
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
  for (const path of SOURCE_FILES.filter(item => item.endsWith(".jsx") && !MODULE_SOURCE_FILES.includes(item))) {
    if (!servedExternalSources.has(path)) errors.push(`${path}: reviewed React source is no longer served`);
  }
  // The module-backed upload has the same handler review requirement as the
  // legacy Babel components. Lock its integration into the production entry.
  const moduleLinks = [
    ['design/Velllum/uploads/Vellum Default Re-designed.html', 'src="/books-entry.js"'],
    ['design/Velllum/uploads/books-entry.js', "import './components/book-upload-entry.jsx'"],
    ['design/Velllum/uploads/components/book-upload-entry.jsx', "import {AttachmentUpload} from './attachment-upload'"],
    ['design/Velllum/uploads/books-entry.js', "import './components/bookshelf/VellumBookshelf.tsx'"],
    ['design/Velllum/uploads/components/bookshelf/VellumBookshelf.tsx', "from './SuppliedBooksPage'"],
    ['design/Velllum/uploads/components/bookshelf/SuppliedBooksPage.tsx', 'from "./components/ImportBooksDialog"'],
    ['design/Velllum/uploads/components/bookshelf/SuppliedBooksPage.tsx', 'from "./components/BriefingOpenOverlay"'],
    ['design/Velllum/uploads/components/bookshelf/components/BriefingOpenOverlay.tsx', 'from "../reader/BookReader"'],
  ];
  for (const [path, reference] of moduleLinks) {
    if (!sources[path]?.includes(reference)) errors.push(`${path}: reviewed upload module is no longer served`);
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
