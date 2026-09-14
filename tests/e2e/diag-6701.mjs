/** Why did the editor not load on 6701? Print where we actually landed. */
import { chromium } from "playwright";
import { resolve } from "node:path";

const STATE = resolve(process.cwd(), "tests/e2e/.auth/state-3000.json");
const URL = process.env.E2E_PROJECT_URL;

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ storageState: STATE, viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();
const errs = [];
page.on("pageerror", (e) => errs.push(`pageerror: ${e.message}`));
page.on("response", (r) => { if (r.status() >= 400) errs.push(`${r.status()} ${r.url()}`); });
page.on("requestfailed", (r) => errs.push(`REQFAIL ${r.method()} ${r.url()} :: ${r.failure()?.errorText}`));

await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 90_000 }).catch((e) => errs.push(`goto: ${e.message}`));
await page.waitForTimeout(12_000);

console.log("landed URL :", page.url());
console.log("title      :", await page.title().catch(() => "?"));
const body = ((await page.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ").slice(0, 400);
console.log("body text  :", body);
console.log("editor tab :", await page.locator('[aria-label="Editor"]').count());
console.log("canvasRoot :", await page.locator("[data-canvas-root]").count());
console.log("canvasRoot :", await page.locator("[data-canvas-root]").count());
console.log("nodes      :", await page.locator("[data-node-id]").count());
console.log("errors     :", errs.slice(0, 12).join("\n             ") || "(none)");
await browser.close();
