/** What is actually in the served HTML / client DOM on 6701? */
import { chromium } from "playwright";
import { resolve } from "node:path";

const STATE = resolve(process.cwd(), "tests/e2e/.auth/state-6701.json");
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ storageState: STATE, viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();
const logs = [];
page.on("console", (m) => logs.push(`${m.type()}: ${m.text().slice(0, 200)}`));
page.on("pageerror", (e) => logs.push(`PAGEERROR: ${e.message.slice(0, 300)}`));

await page.goto("http://localhost:6701/", { waitUntil: "networkidle", timeout: 120_000 }).catch(() => {});
await page.waitForTimeout(6000);

const info = await page.evaluate(() => {
  const b = document.body;
  return {
    bodyChildren: b.children.length,
    bodyClass: b.className.slice(0, 120),
    firstChildren: Array.from(b.children).slice(0, 6).map((c) => ({
      tag: c.tagName.toLowerCase(),
      id: c.id,
      cls: String(c.className).slice(0, 60),
      kids: c.children.length,
      text: (c.textContent ?? "").trim().slice(0, 60),
    })),
    nextData: !!document.querySelector("#__next, #__next_error__"),
    hasErrorOverlay: !!document.querySelector("nextjs-portal"),
  };
});
console.log(JSON.stringify(info, null, 1));
console.log("\nconsole/pageerrors:");
for (const l of logs.slice(0, 15)) console.log("  ", l);
await browser.close();
