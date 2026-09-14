/** Print the editor's real panel structure so the crawl can use true selectors. */
import { chromium } from "playwright";
import { resolve } from "node:path";

const STATE = resolve(process.cwd(), "tests/e2e/.auth/state.json");
const URL = process.env.E2E_PROJECT_URL;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ storageState: STATE, viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();
await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 60_000 });
await page.waitForTimeout(6000);

const info = await page.evaluate(() => {
  const asides = Array.from(document.querySelectorAll("aside")).map((a, i) => ({
    i,
    cls: (a.className || "").toString().slice(0, 120),
    rect: (({ x, y, width, height }) => ({ x: Math.round(x), y: Math.round(y), w: Math.round(width), h: Math.round(height) }))(a.getBoundingClientRect()),
    text: (a.innerText || "").trim().slice(0, 60).replace(/\s+/g, " "),
  }));
  const btnTexts = Array.from(document.querySelectorAll("button"))
    .map((b) => (b.textContent || "").trim())
    .filter((t) => t && t.length < 20);
  const nodes = document.querySelectorAll("[data-node-id]").length;
  const fixedTop = Array.from(document.querySelectorAll("*"))
    .filter((e) => getComputedStyle(e).position === "fixed")
    .slice(0, 12)
    .map((e) => ({
      tag: e.tagName.toLowerCase(),
      cls: (e.className || "").toString().slice(0, 90),
      z: getComputedStyle(e).zIndex,
    }));
  return { asides, btnTexts: Array.from(new Set(btnTexts)).slice(0, 40), nodes, fixedTop };
});

console.log(JSON.stringify(info, null, 1));
await browser.close();
