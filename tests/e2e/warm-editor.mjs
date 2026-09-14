/** Click into the Editor tab once and wait as long as it takes to compile. */
import { chromium } from "playwright";
import { resolve } from "node:path";

const STATE = resolve(process.cwd(), "tests/e2e/.auth/state-3000.json");
const URL = process.env.E2E_PROJECT_URL;

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ storageState: STATE, viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();
const errs = [];
page.on("pageerror", (e) => errs.push(`pageerror: ${e.message.slice(0, 200)}`));
page.on("requestfailed", (r) => {
  const u = r.url();
  if (/_rsc=/.test(u)) return;            // Next RSC prefetch aborts are noise
  errs.push(`REQFAIL ${u.slice(0, 110)} :: ${r.failure()?.errorText}`);
});
page.on("response", (r) => { if (r.status() >= 400) errs.push(`${r.status()} ${r.url().slice(0, 110)}`); });

await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 120_000 });
await page.waitForTimeout(6000);

const tab = page.locator('[aria-label="Editor"]').first();
await tab.waitFor({ state: "visible", timeout: 60_000 });
console.log("[warm] clicking Editor…");
await tab.click();

const DEADLINE = Date.now() + 5 * 60_000;
let last = "";
while (Date.now() < DEADLINE) {
  await page.waitForTimeout(3000);
  const canvas = await page.locator("[data-canvas-root]").count();
  const nodes = await page.locator("[data-node-id]").count();
  const asides = await page.locator("aside").count();
  const state = `canvasRoot=${canvas} nodes=${nodes} asides=${asides}`;
  if (state !== last) { console.log(`[warm] ${Math.round((Date.now() - (DEADLINE - 300000)) / 1000)}s :: ${state}`); last = state; }
  if (canvas > 0) break;
}

const canvas = await page.locator("[data-canvas-root]").count();
console.log(`[warm] FINAL canvasRoot=${canvas}`);
if (canvas === 0) {
  const body = ((await page.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
  console.log(`[warm] body excerpt: ${body.slice(0, 500)}`);
}
console.log("[warm] errors:", errs.slice(0, 10).join("\n              ") || "(none)");
await browser.close();
