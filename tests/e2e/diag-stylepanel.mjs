/** Why was no "Padding" select found? Dump the right panel's real structure. */
import { chromium } from "playwright";
import { resolve } from "node:path";

const STATE = resolve(process.cwd(), "tests/e2e/.auth/state-3000.json");
const URL = process.env.E2E_PROJECT_URL;

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ storageState: STATE, viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();

await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 120_000 });
const tab = page.locator('[aria-label="Editor"]').first();
await tab.waitFor({ state: "visible", timeout: 90_000 });
await tab.click();
await page.waitForSelector("[data-canvas-root]", { timeout: 90_000 });
await page.waitForTimeout(2500);

// Select an existing node via the layers tree (no mutation at all).
const overlaysBefore = await page.locator("[data-tentoro-selection-overlay]").count();
const treeBtns = page.locator("nav button, aside button").filter({ hasText: /^[A-Z][A-Za-z]+$/ });
console.log("tree buttons     :", await treeBtns.count());
if (await treeBtns.count()) { await treeBtns.nth(1).click().catch(() => {}); await page.waitForTimeout(800); }
console.log("overlays         :", overlaysBefore, "->", await page.locator("[data-tentoro-selection-overlay]").count());

const info = await page.evaluate(() => {
  const asides = Array.from(document.querySelectorAll("aside"));
  const right = asides.find((a) =>
    Array.from(a.querySelectorAll("button")).some((b) => /^props$/i.test((b.textContent ?? "").trim())));
  if (!right) return { rightPanel: false, asideCount: asides.length,
                       asideWidths: asides.map((a) => Math.round(a.getBoundingClientRect().width)) };
  const r = right.getBoundingClientRect();
  return {
    rightPanel: true,
    width: Math.round(r.width),
    tabs: Array.from(right.querySelectorAll("button")).map((b) => (b.textContent ?? "").trim()).filter(Boolean).slice(0, 10),
    selects: right.querySelectorAll("select").length,
    inputs: right.querySelectorAll("input").length,
    // every span/div that looks like a section label
    labels: Array.from(right.querySelectorAll("span, div"))
      .filter((e) => e.children.length === 0 && (e.textContent ?? "").trim().length > 0
                     && (e.textContent ?? "").trim().length < 20)
      .map((e) => `${e.tagName.toLowerCase()}:"${(e.textContent ?? "").trim()}"`)
      .slice(0, 30),
    text: (right.textContent ?? "").replace(/\s+/g, " ").slice(0, 220),
  };
});
console.log(JSON.stringify(info, null, 1));
await browser.close();
