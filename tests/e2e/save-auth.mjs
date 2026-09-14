/**
 * ONE-TIME LOGIN CAPTURE.
 *
 * Opens a real Chrome window at the editor. YOU type your email and password —
 * I never see them and am not permitted to type them. This script watches for
 * the login to succeed (URL leaves /login AND an access token appears in
 * localStorage), then saves the browser session to tests/e2e/.auth/state.json
 * and exits on its own. No keypress needed.
 *
 * That state file IS a live credential. It is gitignored. Delete it when done.
 */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:6501";
const OUT = resolve(process.cwd(), "tests/e2e/.auth/state.json");
const DEADLINE = Date.now() + 10 * 60_000; // 10 minutes to log in

const browser = await chromium.launch({
  headless: false,
  args: ["--window-size=1500,1000", "--window-position=80,40"],
});
const context = await browser.newContext({ viewport: { width: 1500, height: 950 } });
const page = await context.newPage();

console.log(`[auth] opening ${BASE}`);
try {
  await page.goto(BASE, { waitUntil: "domcontentloaded", timeout: 45_000 });
} catch (e) {
  console.error(`[auth] could not reach ${BASE}: ${e.message}`);
}

console.log("[auth] >>> LOG IN IN THE BROWSER WINDOW. I'll detect it automatically. <<<");

async function loggedIn() {
  if (/\/login|\/signup/.test(page.url())) return false;
  return page.evaluate(() => {
    try {
      const keys = ["token", "access_token", "authToken"];
      return keys.some((k) => {
        const v = localStorage.getItem(k);
        return typeof v === "string" && v.length > 20;
      });
    } catch { return false; }
  }).catch(() => false);
}

let ok = false;
while (Date.now() < DEADLINE) {
  if (await loggedIn()) { ok = true; break; }
  await page.waitForTimeout(1500);
}

if (!ok) {
  console.error("[auth] TIMED OUT — no login detected in 10 minutes.");
  await browser.close();
  process.exit(1);
}

// Let the editor settle so any post-login cookies are written too.
await page.waitForTimeout(2500);
mkdirSync(dirname(OUT), { recursive: true });
await context.storageState({ path: OUT });

console.log(`[auth] SAVED -> ${OUT}`);
console.log(`[auth] landed on: ${page.url()}`);
console.log("[auth] Now OPEN A PROJECT and leave it on the editor screen for 20s…");

// Give the user a moment to navigate into a project, then capture that URL too:
// the crawl is far more useful pointed straight at an editor page.
const settle = Date.now() + 25_000;
let last = page.url();
while (Date.now() < settle) {
  await page.waitForTimeout(1500);
  last = page.url();
}
await context.storageState({ path: OUT });
console.log(`[auth] PROJECT_URL=${last}`);
await browser.close();
console.log("[auth] done.");
