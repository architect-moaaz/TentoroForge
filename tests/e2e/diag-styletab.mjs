/**
 * Drop a node, open the Style tab, and DUMP the panel. No guessing.
 * Restores the project afterwards via the drop being deleted again.
 */
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

// drop a Button (auto-selects)
await page.evaluate(() => {
  const root = document.querySelector("[data-canvas-root]");
  const dt = new DataTransfer();
  dt.setData("text/x-forge-component", "Button");
  const o = { bubbles: true, cancelable: true, composed: true, dataTransfer: dt };
  root.dispatchEvent(new DragEvent("dragenter", o));
  root.dispatchEvent(new DragEvent("dragover", o));
  root.dispatchEvent(new DragEvent("drop", o));
});
await page.waitForTimeout(900);
console.log("overlays after drop:", await page.locator("[data-tentoro-selection-overlay]").count());

// How many buttons named "Style" exist on the whole page, and where?
const styleButtons = await page.evaluate(() =>
  Array.from(document.querySelectorAll("button"))
    .map((b, i) => ({ i, text: (b.textContent ?? "").trim(), cls: String(b.className).slice(0, 50) }))
    .filter((b) => /^style$/i.test(b.text)));
console.log("buttons named 'Style':", JSON.stringify(styleButtons));

// Click the one inside the panel that also contains a "Props" button.
const clicked = await page.evaluate(() => {
  const asides = Array.from(document.querySelectorAll("aside"));
  const right = asides.find((a) =>
    Array.from(a.querySelectorAll("button")).some((b) => /^props$/i.test((b.textContent ?? "").trim())));
  if (!right) return "no right panel";
  const btn = Array.from(right.querySelectorAll("button"))
    .find((b) => /^style$/i.test((b.textContent ?? "").trim()));
  if (!btn) return "no Style button in right panel";
  btn.click();
  return "clicked";
});
console.log("style tab click:", clicked);
await page.waitForTimeout(1200);

const dump = await page.evaluate(() => {
  const asides = Array.from(document.querySelectorAll("aside"));
  const right = asides.find((a) =>
    Array.from(a.querySelectorAll("button")).some((b) => /^props$/i.test((b.textContent ?? "").trim())));
  if (!right) return { panel: false };
  return {
    panel: true,
    selects: right.querySelectorAll("select").length,
    inputs: right.querySelectorAll("input").length,
    spans: Array.from(right.querySelectorAll("span"))
      .filter((s) => s.children.length === 0 && (s.textContent ?? "").trim())
      .map((s) => (s.textContent ?? "").trim()).slice(0, 25),
    textStart: (right.textContent ?? "").replace(/\s+/g, " ").slice(0, 260),
  };
});
console.log(JSON.stringify(dump, null, 1));

// clean up: the node is still selected
await page.keyboard.press("Delete").catch(() => {});
await page.waitForTimeout(600);
await browser.close();
