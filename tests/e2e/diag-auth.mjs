/** Is the session actually present at the 6701 origin, and what does / render? */
import { chromium } from "playwright";
import { resolve } from "node:path";

const STATE = resolve(process.cwd(), "tests/e2e/.auth/state-6701.json");
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ storageState: STATE, viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();

await page.goto("http://localhost:6701/", { waitUntil: "domcontentloaded", timeout: 120_000 });
await page.waitForTimeout(8000);

const ls = await page.evaluate(() => {
  const out = {};
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    const v = localStorage.getItem(k) ?? "";
    out[k] = v.length > 24 ? `<${v.length} chars>` : v;   // never print a token
  }
  return out;
});
console.log("origin         :", page.url());
console.log("localStorage   :", JSON.stringify(ls));
console.log("root body text :", ((await page.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ").slice(0, 200));
console.log("root html len  :", (await page.content()).length);

// Does the app think we're logged in? Look for a nav landmark.
console.log("nav links      :", await page.locator("a[href*='/org/']").count());
await browser.close();
