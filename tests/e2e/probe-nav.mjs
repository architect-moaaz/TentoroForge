/** Find how to reach the visual editor: aria-labels, titles, links, tab roles. */
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
  const labelled = Array.from(document.querySelectorAll("button,a,[role=tab],[role=button]"))
    .map((e) => ({
      tag: e.tagName.toLowerCase(),
      role: e.getAttribute("role") || "",
      label: e.getAttribute("aria-label") || "",
      title: e.getAttribute("title") || "",
      href: e.href || "",
      text: (e.textContent || "").trim().slice(0, 30).replace(/\s+/g, " "),
      cls: (e.className || "").toString().slice(0, 60),
    }))
    .filter((e) => e.label || e.title || (e.text && e.text.length < 25) || e.role === "tab");
  return { count: labelled.length, labelled: labelled.slice(0, 60) };
});

console.log(JSON.stringify(info, null, 1));
await browser.close();
