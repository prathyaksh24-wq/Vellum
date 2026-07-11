import { pathToFileURL, fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { execSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const npmRoot = execSync("npm root -g").toString().trim();
const { chromium } = await import(pathToFileURL(join(npmRoot, "@playwright/mcp/node_modules/playwright/index.mjs")).href);
const url = process.env.VELLUM_UI_URL || "http://127.0.0.1:5173/design-uploads/Vellum%20Default%20Re-designed.html";
const screenshotPath = join(here, "smoke-memory-wiki.png");

let browser;
try { browser = await chromium.launch({ channel: "msedge", headless: true }); }
catch { browser = await chromium.launch({ channel: "chrome", headless: true }); }

const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const errors = [];
page.on("pageerror", error => errors.push("pageerror: " + error.message));
page.on("console", message => {
  if (message.type() === "error") {
    const location = message.location();
    errors.push("console: " + message.text() + (location && location.url ? " @ " + location.url : ""));
  }
});
page.on("response", response => { if (response.status() >= 400) errors.push("http " + response.status() + ": " + response.url()); });

const check = async (name, action) => {
  await action();
  console.log("PASS  " + name);
};

try {
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.locator(".stage").waitFor({ timeout: 30000 });

  await check("conversation sidebar survives reload", async () => {
    const rows = page.locator(".chat-row");
    await rows.first().waitFor();
    const title = await rows.first().locator(".chat-title").textContent();
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.locator(".stage").waitFor();
    await page.locator(".chat-row", { hasText: title || "" }).first().waitFor();
  });

  await check("memory summary and saved memories load from backend", async () => {
    await page.locator(".sb-row", { hasText: "Memory" }).click();
    await page.locator(".hc-card-page").waitFor();
    await page.locator(".hc-status", { hasText: "saved" }).waitFor();
    const summary = (await page.locator(".hc-body").textContent()) || "";
    if (!summary.trim() || summary.includes("Memory backend unavailable")) throw new Error("memory summary did not load");
    await page.locator(".hc-tab", { hasText: "Saved" }).click();
    if (await page.locator(".hc-empty", { hasText: "No saved memories" }).count()) throw new Error("saved memories are empty");
    await page.locator(".hc-tab", { hasText: "Old" }).click();
    await page.locator("input[placeholder='Filter old memories']").waitFor();
  });

  await check("dreaming runs and memory persists after refresh", async () => {
    await page.locator(".hc-tab", { hasText: "Dreaming" }).click();
    const run = page.locator(".hc-dream-btn", { hasText: "Run now" });
    await run.click();
    await page.locator(".hc-dream-btn", { hasText: "Run now" }).waitFor({ timeout: 60000 });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.locator(".sb-row", { hasText: "Memory" }).click();
    await page.locator(".hc-card-page").waitFor();
    if (await page.locator(".hc-status", { hasText: "0 saved" }).count()) throw new Error("saved memory disappeared after refresh");
  });

  await check("knowledge wiki searches and opens a real page", async () => {
    await page.locator(".sb-row", { hasText: "Knowledge graph" }).click();
    await page.locator("input[aria-label='Search knowledge wiki']").fill("memory");
    await page.keyboard.press("Enter");
    await page.locator(".wiki-result").first().waitFor({ timeout: 30000 });
    await page.locator(".wiki-result").first().click();
    await page.locator(".wiki-page-title").waitFor();
    const content = (await page.locator(".wiki-page-content").textContent()) || "";
    if (content.trim().length < 20) throw new Error("wiki page content is empty");
  });

  await check("knowledge health and rebuild actions complete", async () => {
    await page.locator("button", { hasText: "Check health" }).click();
    await page.locator(".wiki-report").waitFor({ timeout: 30000 });
    await page.locator("button", { hasText: "Rebuild index" }).click();
    await page.locator("button", { hasText: "Rebuild index" }).waitFor({ state: "visible", timeout: 30000 });
  });

  await check("recent-chat menu stays inside viewport", async () => {
    await page.locator("button", { hasText: "Back" }).click();
    const row = page.locator(".chat-row").first();
    await row.hover();
    const dots = row.locator(".chat-dots");
    await dots.click();
    const menu = page.locator(".ctx-menu");
    await menu.waitFor();
    const box = await menu.boundingBox();
    if (!box || box.x < 0 || box.y < 0 || box.x + box.width > 1440 || box.y + box.height > 960) throw new Error("chat menu is clipped");
    await page.keyboard.press("Escape");
  });

  await page.screenshot({ path: screenshotPath, fullPage: true });
  if (errors.length) throw new Error(errors.join("\n"));
  console.log("SCREENSHOT  " + screenshotPath);
} finally {
  await browser.close();
}
