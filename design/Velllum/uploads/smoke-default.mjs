// Automated run-through of vellum-default.html (spec §9). Not part of the preview; dev verification only.
// Usage: node smoke-default.mjs
import { pathToFileURL, fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { execSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { tmpdir } from "node:os";

const srcFile = join(tmpdir(), "vellum-smoke-source.txt");
writeFileSync(srcFile, "a quiet source");
const pngFile = join(tmpdir(), "vellum-smoke-image.png");
writeFileSync(pngFile, Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64"));

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
  if (await page.locator(".land-greet").textContent() !== "Ready when you are.") throw new Error("greeting wrong");
  await page.locator(".cpill textarea").waitFor();
  if (await page.locator(".chip").count() !== 3) throw new Error("chips != 3");
});

await check("model picker: search + select updates pill", async () => {
  if ((await page.locator(".model-num").first().textContent()) !== "DeepSeek V4 Pro") throw new Error("default model wrong");
  await page.locator(".model-pill").click();
  await page.locator(".model-drop").waitFor();
  await page.locator(".model-search").fill("claude");
  await page.locator(".drop-item", { hasText: "Claude 3.7 Sonnet" }).click();
  if ((await page.locator(".model-num").first().textContent()) !== "Claude 3.7 Sonnet") throw new Error("pill not updated");
});

await check("+ menu: attach from recent files", async () => {
  await page.locator(".cbtn[title='Add']").click();
  await page.locator(".plus-item", { hasText: "Add photos & files" }).waitFor();
  if (!(await page.locator(".plus-menu").getAttribute("class")).includes("down")) throw new Error("menu should drop down on landing");
  await page.locator(".plus-item", { hasText: "Recent files" }).hover();
  await page.locator(".plus-sub .recent-row").first().waitFor();
  const firstName = await page.locator(".plus-sub .recent-row .r-name").first().textContent();
  await page.locator(".plus-sub .recent-row").first().click();
  await page.locator(".backdrop").click().catch(() => {});
  const card = page.locator(".att-card", { hasText: firstName.slice(0, 12) });
  await card.waitFor();
  await card.locator(".att-x").click();
  if (await page.locator(".att-card").count()) throw new Error("attachment card not removed");
});

await check("add-from-library modal: search + attach", async () => {
  await page.locator(".cbtn[title='Add']").click();
  await page.locator(".plus-item", { hasText: "Recent files" }).hover();
  await page.locator(".plus-sub .plus-item", { hasText: "Add from library" }).click();
  await page.locator(".libpick .lp-head", { hasText: "Add from library" }).waitFor();
  await page.locator(".lp-search").fill("stillness");
  await page.locator(".libpick .recent-row", { hasText: "on stillness" }).click();
  const card = page.locator(".att-card", { hasText: "on stillness" });
  await card.waitFor();
  if (await page.locator(".libpick").count()) throw new Error("modal did not close after pick");
  await card.locator(".att-x").click();
});

await check("image attach → thumbnail → lightbox", async () => {
  await page.locator(".cpill input[type=file]").setInputFiles(pngFile);
  await page.locator(".att-img").waitFor();
  await page.locator(".att-img").click();
  await page.locator(".lightbox img").waitFor();
  await page.keyboard.press("Escape");
  if (await page.locator(".lightbox").count()) throw new Error("lightbox did not close");
  await page.locator(".att-img .att-x").click();
  if (await page.locator(".att-img").count()) throw new Error("image attachment not removed");
});

await check("apps: Finish Setup + toggle surface chips", async () => {
  await page.locator(".app-chip", { hasText: "Apps" }).click();
  await page.locator(".apps-drop").waitFor();
  await page.locator(".app-act", { hasText: "Finish Setup" }).click();
  await page.locator(".app-chip", { hasText: "GitHub" }).waitFor();
  await page.locator(".apps-drop .app-row", { hasText: "Airtable" }).locator(".sw").click();
  await page.locator(".app-chip", { hasText: "Airtable" }).waitFor();
  await page.locator(".apps-drop .app-row", { hasText: "Airtable" }).locator(".sw").click();
  if (await page.locator(".app-chip", { hasText: "Airtable" }).count()) throw new Error("Airtable chip not removed");
  await page.keyboard.press("Escape");
});

await check("sidebar: nav rows + projects section + recents + profile", async () => {
  for (const label of ["New chat", "Search chats", "Library", "New project"])
    if (!(await page.locator(".sb-row", { hasText: label }).count())) throw new Error("missing " + label);
  for (const sec of ["Projects", "Recents"])
    if (!(await page.locator(".sb-sec", { hasText: sec }).count())) throw new Error("missing section " + sec);
  if (await page.locator(".chat-row").count() < 8) throw new Error("project/recent rows missing");
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

await check("dark streaming: accent glow shimmer", async () => {
  await page.locator(".cpill textarea").fill("and what about patience");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => {
    const el = [...document.querySelectorAll(".areply")].pop();
    if (!el || !el.classList.contains("shimmer")) return false;
    const cs = getComputedStyle(el);
    return cs.filter.includes("drop-shadow") && cs.webkitTextFillColor === "rgba(0, 0, 0, 0)";
  }, { timeout: 5000 });
  await page.waitForFunction(() => {
    const el = [...document.querySelectorAll(".areply")].pop();
    return el && !el.classList.contains("shimmer") && el.textContent.length > 40;
  }, { timeout: 15000 });
});

await check("timeline: bars + history popup + jump", async () => {
  await page.locator(".timeline").waitFor();
  if (await page.locator(".tl-bar").count() !== 2) throw new Error("expected 2 bars");
  await page.locator(".timeline").hover();
  await page.locator(".tl-pop").waitFor();
  if (await page.locator(".tl-row").count() !== 2) throw new Error("expected 2 history rows");
  await page.locator(".tl-row").first().click();
  await page.locator(".bubble").first().waitFor();
  await page.mouse.move(400, 300);
});

await check("collapse → rail → expand via panel button", async () => {
  await page.locator(".tbtn[title='Collapse sidebar']").click();
  await page.locator(".rail").waitFor();
  await page.locator(".rail-btn[title='Expand sidebar']").click();
  await page.locator(".sidebar").waitFor();
});

await check("rail flyouts: last-10 recents + projects settings", async () => {
  await page.locator(".tbtn[title='Collapse sidebar']").click();
  await page.locator(".rail").waitFor();
  await page.locator(".rail-btn[title='Chats']").hover();
  await page.locator(".flyout .fly-head", { hasText: "Recents" }).waitFor();
  const rows = await page.locator(".flyout .chat-row").count();
  if (rows < 5 || rows > 10) throw new Error("recents flyout rows: " + rows);
  await page.locator(".rail-btn[title='Projects']").hover();
  await page.locator(".flyout .chat-row", { hasText: "New project" }).waitFor();
  await page.locator(".flyout .chat-row", { hasText: "Vellum Desktop" }).waitFor();
  await page.locator(".rail-logo").click();
  await page.locator(".sidebar").waitFor();
});

await check("create project via modal (project-only memory)", async () => {
  await page.locator(".sb-row", { hasText: "New project" }).click();
  await page.locator(".modal .m-title", { hasText: "Create project" }).waitFor();
  if (!(await page.locator(".btn.primary:disabled").count())) throw new Error("Create should be disabled when unnamed");
  await page.locator(".tbtn[title='Project memory']").click();
  await page.locator(".gp-item", { hasText: "Project-only" }).click();
  await page.locator(".m-field input").fill("Smoke project");
  await page.locator(".btn.primary", { hasText: "Create project" }).click();
  await page.locator(".proj-name", { hasText: "Smoke project" }).waitFor();
  await page.locator(".proj-mem", { hasText: "project-only memory" }).waitFor();
});

await check("new chat inside project + breadcrumb + nesting", async () => {
  await page.locator(".cpill textarea").fill("plan the smoke run");
  await page.keyboard.press("Enter");
  await page.locator(".crumb", { hasText: "Smoke project" }).waitFor();
  await page.waitForFunction(() => {
    const el = [...document.querySelectorAll(".areply")].pop();
    return el && !el.classList.contains("shimmer") && el.textContent.length > 40;
  }, { timeout: 15000 });
  await page.locator(".chat-row.nested", { hasText: "plan the smoke run" }).waitFor();
  if (await page.locator(".chat-row", { hasText: "plan the smoke run" }).count() !== 1)
    throw new Error("project chat leaked into Recents");
});

await check("folder icon toggles nested chats with animation state", async () => {
  const fold = page.locator(".chat-row", { hasText: "Smoke project" }).first().locator(".fold");
  if (!(await fold.getAttribute("class")).includes("on")) throw new Error("folder should be open after in-project chat");
  await fold.click();
  if (await page.locator(".chat-row.nested", { hasText: "plan the smoke run" }).count()) throw new Error("nested chat still visible after close");
  await fold.click();
  await page.locator(".chat-row.nested", { hasText: "plan the smoke run" }).waitFor();
});

await check("project page lists its chats + sources upload", async () => {
  await page.locator(".chat-row", { hasText: "Smoke project" }).first().click();
  const row = page.locator(".proj-chat-row", { hasText: "plan the smoke run" });
  await row.waitFor();
  if (!(await row.locator(".pcr-date").textContent())) throw new Error("date missing on project chat row");
  await row.hover();
  await row.locator(".pcr-dots").click();
  await page.locator(".ctx-item", { hasText: "Remove from Smoke project" }).waitFor();
  await page.keyboard.press("Escape");
  await page.locator(".tab", { hasText: "Sources" }).click();
  await page.locator(".src-title", { hasText: "Give Vellum more context" }).waitFor();
  await page.locator(".page input[type=file]").last().setInputFiles(srcFile);
  await page.locator(".src-row", { hasText: "vellum-smoke-source.txt" }).waitFor();
});

await check("remove from project → moves to Recents", async () => {
  await page.locator(".chat-row", { hasText: "Smoke project" }).first().click(); // re-expand folder (row click toggles)
  const row = page.locator(".chat-row.nested", { hasText: "plan the smoke run" }).first();
  await row.hover();
  await row.locator(".chat-dots").click();
  await page.locator(".ctx-item", { hasText: "Remove from Smoke project" }).click();
  if (await page.locator(".chat-row.nested", { hasText: "plan the smoke run" }).count()) throw new Error("still nested");
  await page.locator(".chat-row", { hasText: "plan the smoke run" }).first().waitFor();
});

await check("rename + delete project via menu", async () => {
  const row = page.locator(".chat-row", { hasText: "Smoke project" }).first();
  await row.hover();
  await row.locator(".chat-dots").click();
  await page.locator(".ctx-item", { hasText: "Rename project" }).click();
  await page.locator(".sidebar .rename-input").fill("Smoke renamed");
  await page.keyboard.press("Enter");
  const renamed = page.locator(".chat-row", { hasText: "Smoke renamed" }).first();
  await renamed.waitFor();
  await renamed.hover();
  await renamed.locator(".chat-dots").click();
  await page.locator(".ctx-item.danger", { hasText: "Delete project" }).click();
  if (await page.locator(".chat-row", { hasText: "Smoke renamed" }).count()) throw new Error("project still present");
  await page.locator(".chat-row", { hasText: "plan the smoke run" }).first().waitFor();
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

await check("recents section collapses and expands", async () => {
  await page.locator(".sb-sec", { hasText: "Recents" }).click();
  if (await page.locator(".chat-row", { hasText: "Self-Perception" }).count()) throw new Error("recents still visible after collapse");
  await page.locator(".sb-sec", { hasText: "Recents" }).click();
  await page.locator(".chat-row", { hasText: "Self-Perception" }).first().waitFor();
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

await check("coding row present, wired to workspace", async () => {
  const row = page.locator(".sb-row", { hasText: "Coding" });
  await row.waitFor();
  const title = await row.getAttribute("title");
  if (!title || !title.includes("workspace")) throw new Error("coding row not labeled for workspace");
});

await check("ledger view renders", async () => {
  await page.locator(".sb-row", { hasText: "Ledger" }).click();
  await page.locator(".page-title", { hasText: "Ledger" }).waitFor();
  await page.locator(".quiet-foot", { hasText: "Filed locally. Nothing sent." }).waitFor();
  if (await page.locator(".led-row").count() !== 3) throw new Error("model breakdown rows wrong");
});

await check("skills: approve → Active, retire → Retired", async () => {
  await page.locator(".sb-row", { hasText: "Skills" }).click();
  await page.locator(".tab", { hasText: "Proposed (2)" }).waitFor();
  await page.locator(".skill-card", { hasText: "Book summary" }).locator("button", { hasText: "Approve" }).click();
  await page.locator(".tab", { hasText: "Proposed (1)" }).waitFor();
  await page.locator(".tab", { hasText: "Active (3)" }).click();
  const card = page.locator(".skill-card", { hasText: "Book summary" });
  await card.waitFor();
  await card.locator("button", { hasText: "Retire" }).click();
  await page.locator(".tab", { hasText: "Retired (2)" }).waitFor();
});

await check("memory: forget removes a fact", async () => {
  await page.locator(".sb-row", { hasText: "Memory" }).click();
  if (await page.locator(".mem-row").count() !== 5) throw new Error("expected 5 facts");
  await page.locator(".mem-row .chat-dots").first().click();
  if (await page.locator(".mem-row").count() !== 4) throw new Error("forget did not remove");
});

await check("archive: restore round-trip", async () => {
  const row = page.locator(".chat-row", { hasText: "Cult UI Components" }).first();
  await row.hover();
  await row.locator(".chat-dots").click();
  await page.locator(".ctx-item", { hasText: "Archive" }).click();
  await page.locator(".sb-row", { hasText: "Archive" }).click();
  await page.locator(".arc-row", { hasText: "Cult UI Components" }).waitFor();
  await page.locator(".arc-row button", { hasText: "Restore" }).click();
  if (await page.locator(".arc-row").count()) throw new Error("archive not emptied");
  await page.locator(".chat-row", { hasText: "Cult UI Components" }).first().waitFor();
});

await check("settings modal: feeds toggle + computer use", async () => {
  await page.locator(".profile-row").click();
  await page.locator(".pop-row", { hasText: "Settings" }).click();
  await page.locator(".set-modal").waitFor();
  await page.locator(".set-item", { hasText: "Feeds" }).click();
  const sw = page.locator(".sw").first();
  if (!(await sw.getAttribute("class")).includes("on")) throw new Error("X feed should start on");
  await sw.click();
  if ((await sw.getAttribute("class")).includes("on")) throw new Error("toggle did not turn off");
  await page.locator(".set-item", { hasText: "Computer use" }).click();
  await page.locator(".set-body .btn.primary", { hasText: "Enable" }).click();
  await page.locator(".cu-pill.on", { hasText: "active" }).waitFor();
  await page.locator(".set-body .btn", { hasText: "Stand down" }).click();
  await page.locator(".cu-pill", { hasText: "standing down" }).waitFor();
  await page.keyboard.press("Escape");
  if (await page.locator(".set-modal").count()) throw new Error("Esc did not close settings");
});

await check("projects grid (via rail): cards open project page", async () => {
  await page.locator(".tbtn[title='Collapse sidebar']").click();
  await page.locator(".rail-btn[title='Projects']").click();
  await page.locator(".rail-logo").click();
  if (await page.locator(".pcard").count() < 3) throw new Error("seed cards missing");
  await page.locator(".pcard", { hasText: "Vellum Desktop" }).click();
  await page.locator(".proj-name", { hasText: "Vellum Desktop" }).waitFor();
  await page.locator(".proj-empty .pe-t", { hasText: "No chats yet" }).waitFor();
});

await check("projects header collapses section like recents", async () => {
  await page.locator(".sb-sec", { hasText: "Projects" }).click();
  if (await page.locator(".sb-row", { hasText: "New project" }).count()) throw new Error("section still open");
  await page.locator(".sb-sec", { hasText: "Projects" }).click();
  await page.locator(".sb-row", { hasText: "New project" }).waitFor();
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

await check("light streaming: plain text, no shimmer fill", async () => {
  // after reload above we are in light mode on the landing
  await page.locator(".cpill textarea").fill("a quiet thought for the morning");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => {
    const el = [...document.querySelectorAll(".areply")].pop();
    if (!el || !el.classList.contains("shimmer")) return false;
    const cs = getComputedStyle(el);
    return cs.webkitTextFillColor !== "rgba(0, 0, 0, 0)" && !cs.filter.includes("drop-shadow");
  }, { timeout: 5000 });
  await page.waitForFunction(() => {
    const el = [...document.querySelectorAll(".areply")].pop();
    return el && !el.classList.contains("shimmer") && el.textContent.length > 40;
  }, { timeout: 15000 });
});

await check("animated placeholder rotates", async () => {
  await page.locator(".sb-row", { hasText: "New chat" }).click();
  await page.locator(".ph-anim").waitFor();
  const first = await page.locator(".ph-anim").textContent();
  await page.waitForFunction(prev => {
    const el = document.querySelector(".ph-anim");
    return el && el.textContent !== prev;
  }, first, { timeout: 6000 });
});

if (errors.length) { failed++; console.log("FAIL  console clean — " + errors.join(" | ")); }
else console.log("PASS  console clean");

await browser.close();
console.log(failed === 0 ? "OK: smoke run-through passed" : `FAIL: ${failed} checks failed`);
process.exit(failed === 0 ? 0 : 1);
