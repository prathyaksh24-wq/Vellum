// Automated run-through of vellum-default.html (spec §9). Not part of the preview; dev verification only.
// Usage: node smoke-default.mjs
import { pathToFileURL, fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { execSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const npmRoot = execSync("npm root -g").toString().trim();
const { chromium } = await import(pathToFileURL(join(npmRoot, "@playwright/mcp/node_modules/playwright/index.mjs")).href);

const url = pathToFileURL(join(here, "vellum-default.html")).href;
let browser;
try { browser = await chromium.launch({ channel: "msedge" }); }
catch { browser = await chromium.launch({ channel: "chrome" }); }
const page = await browser.newPage();
const errors = [];
page.on("pageerror", e => errors.push("pageerror: " + e.message));
page.on("console", m => { if (m.type() === "error") errors.push("console: " + m.text()); });

let failed = 0;
const check = async (name, fn) => {
  try { await fn(); console.log("PASS  " + name); }
  catch (e) { failed++; console.log("FAIL  " + name + " — " + (e.message || e).split("\n")[0]); }
};

await page.goto(url);
await page.waitForSelector(".landing", { timeout: 20000 });

await check("landing: greeting + composer + chips", async () => {
  if (await page.locator(".land-greet").textContent() !== "What are you reading.") throw new Error("greeting wrong");
  await page.locator(".cpill textarea").waitFor();
  if (await page.locator(".chip").count() !== 3) throw new Error("chips != 3");
});

await check("sidebar: nav rows + recents + profile", async () => {
  for (const label of ["New chat", "Search chats", "Library", "Projects"])
    if (!(await page.locator(".sb-row", { hasText: label }).count())) throw new Error("missing " + label);
  if (await page.locator(".chat-row").count() < 5) throw new Error("recents missing");
  await page.locator(".profile-row .p-name").waitFor();
});

await check("excluded sections absent (Apps/Codex/GPTs/More)", async () => {
  for (const label of ["Apps", "Codex", "GPTs", "More"])
    if (await page.locator(".sidebar", { hasText: label }).count()) throw new Error(label + " present");
});

await check("send message → bubble + streamed reply + actions", async () => {
  await page.locator(".cpill textarea").fill("what should I read about stillness");
  await page.keyboard.press("Enter");
  await page.locator(".bubble").waitFor();
  await page.waitForFunction(() => {
    const el = document.querySelector(".areply");
    return el && !el.classList.contains("shimmer") && el.textContent.length > 40;
  }, { timeout: 15000 });
  await page.locator(".act-row").waitFor();
});

await check("new chat appears in recents with derived title", async () => {
  await page.locator(".chat-row", { hasText: "what should I read" }).first().waitFor();
});

await check("regenerate re-streams a different variant", async () => {
  const before = await page.locator(".areply").last().textContent();
  await page.locator(".act-btn[title='Regenerate']").last().click();
  await page.waitForFunction(() => {
    const el = document.querySelector(".areply");
    return el && !el.classList.contains("shimmer") && el.textContent.length > 40;
  }, { timeout: 15000 });
  const after = await page.locator(".areply").last().textContent();
  if (before === after) throw new Error("same text after regenerate");
});

await check("collapse → rail → expand", async () => {
  await page.locator(".tbtn[title='Collapse sidebar']").click();
  await page.locator(".rail").waitFor();
  await page.locator(".rail-logo").click();
  await page.locator(".sidebar").waitFor();
});

await check("search overlay filters and opens", async () => {
  await page.locator(".sb-row", { hasText: "Search chats" }).click();
  await page.locator(".search-input").fill("cult");
  await page.locator(".s-row", { hasText: "Cult UI Components" }).click();
  await page.locator(".chat-row.active", { hasText: "Cult UI" }).waitFor();
});

await check("recents menu: pin sorts to top", async () => {
  const row = page.locator(".chat-row", { hasText: "Usage boost" }).first();
  await row.hover();
  await row.locator(".chat-dots").click();
  await page.locator(".ctx-item", { hasText: "Pin chat" }).click();
  const titles = await page.locator(".chat-row").allTextContents();
  const pinnedIdx = titles.findIndex(t => t.includes("Usage boost"));
  const unpinnedIdx = titles.findIndex(t => t.includes("Prioritizing Vellum"));
  if (pinnedIdx === -1 || pinnedIdx > unpinnedIdx) throw new Error("pinned chat not above unpinned");
  if (!(await page.locator(".chat-row", { hasText: "Usage boost" }).first().locator(".chat-pin").count())) throw new Error("pin glyph missing");
});

await check("recents menu: rename inline", async () => {
  const row = page.locator(".chat-row", { hasText: "Live Streaming" }).first();
  await row.hover();
  await row.locator(".chat-dots").click();
  await page.locator(".ctx-item", { hasText: "Rename" }).click();
  await page.locator(".rename-input").fill("Streaming notes");
  await page.keyboard.press("Enter");
  await page.locator(".chat-row", { hasText: "Streaming notes" }).first().waitFor();
});

await check("recents menu: delete removes", async () => {
  const row = page.locator(".chat-row", { hasText: "Streaming notes" }).first();
  await row.hover();
  await row.locator(".chat-dots").click();
  await page.locator(".ctx-item.danger", { hasText: "Delete" }).click();
  if (await page.locator(".chat-row", { hasText: "Streaming notes" }).count()) throw new Error("still present");
});

await check("library: tabs + search + grid/list + note", async () => {
  await page.locator(".sb-row", { hasText: "Library" }).click();
  await page.locator(".page-title", { hasText: "Library" }).waitFor();
  if (await page.locator(".ltr").count() < 8) throw new Error("seed rows missing");
  await page.locator(".tab", { hasText: "Images" }).click();
  if (await page.locator(".ltr").count() !== 1) throw new Error("Images filter wrong");
  await page.locator(".tab", { hasText: "All" }).click();
  await page.locator(".lib-search input").fill("workspace");
  if (await page.locator(".ltr").count() !== 2) throw new Error("search filter wrong");
  await page.locator(".lib-search input").fill("");
  await page.locator(".icon-tgl[title='Grid view']").click();
  await page.locator(".ltile").first().waitFor();
  await page.locator(".icon-tgl[title='List view']").click();
  await page.locator(".new-btn").click();
  await page.locator(".ctx-item", { hasText: "Note" }).click();
  await page.locator(".rename-input").fill("a quiet note");
  await page.keyboard.press("Enter");
  await page.locator(".ltr", { hasText: "a quiet note" }).waitFor();
});

await check("projects: cards + new project", async () => {
  await page.locator(".sb-row", { hasText: "Projects" }).click();
  if (await page.locator(".pcard").count() < 3) throw new Error("seed cards missing");
  await page.locator(".new-btn", { hasText: "New project" }).click();
  await page.locator(".rename-input").fill("Default shell");
  await page.keyboard.press("Enter");
  await page.locator(".pcard h3", { hasText: "Default shell" }).waitFor();
});

await check("profile popover → edit profile → save updates sidebar", async () => {
  await page.locator(".profile-row").click();
  await page.locator(".pop").waitFor();
  await page.locator(".pop-row", { hasText: "Profile" }).last().click();
  await page.locator(".modal").waitFor();
  await page.locator(".m-field input").first().fill("Alex Smith");
  await page.locator(".btn.primary").click();
  await page.locator(".p-name", { hasText: "Alex Smith" }).waitFor();
  const av = await page.locator(".profile-row .avatar").textContent();
  if (av !== "AS") throw new Error("initials not updated: " + av);
});

await check("theme toggle → light + persists", async () => {
  await page.locator(".tbtn[title='Light mode']").click();
  await page.waitForFunction(() => document.documentElement.getAttribute("data-theme") === "light");
  await page.reload();
  await page.waitForSelector(".landing, .msgs, .page", { timeout: 20000 });
  if (await page.evaluate(() => document.documentElement.getAttribute("data-theme")) !== "light") throw new Error("did not persist");
});

if (errors.length) { failed++; console.log("FAIL  console clean — " + errors.join(" | ")); }
else console.log("PASS  console clean");

await browser.close();
console.log(failed === 0 ? "OK: smoke run-through passed" : `FAIL: ${failed} checks failed`);
process.exit(failed === 0 ? 0 : 1);
