/**
 * Capture the EDITOR page URL, reusing the session already saved by
 * save-auth.mjs — no second login.
 *
 * Opens the project, then just waits and watches. Take as long as you like:
 * navigate into the visual editor, open a page, and when the canvas is on
 * screen this records the URL and exits. Five minutes, and it prints where it
 * thinks you are every few seconds so it is obvious it is still watching.
 */
import { chromium } from "playwright";
import { writeFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const STATE = resolve(process.cwd(), "tests/e2e/.auth/state.json");
const OUT = resolve(process.cwd(), "tests/e2e/.auth/editor-url.txt");
const START = process.env.E2E_PROJECT_URL ?? process.env.E2E_BASE_URL ?? "http://localhost:6501";

if (!existsSync(STATE)) {
  console.error(`[url] no saved session at ${STATE} — run save-auth.mjs first`);
  process.exit(1);
}

const browser = await chromium.launch({
  headless: false,
  args: ["--window-size=1500,1000", "--window-position=80,40"],
});
const context = await browser.newContext({
  storageState: STATE,
  viewport: { width: 1500, height: 950 },
});
const page = await context.newPage();

console.log(`[url] opening ${START}`);
await page.goto(START, { waitUntil: "domcontentloaded", timeout: 60_000 }).catch((e) =>
  console.error(`[url] ${e.message}`));

console.log(`
────────────────────────────────────────────────────────────
  Take your time. Open the VISUAL EDITOR for a page so the
  canvas with components is on screen.

  I'll detect the canvas automatically and close the window.
  Five minutes. No keypress needed.
────────────────────────────────────────────────────────────
`);

const DEADLINE = Date.now() + 5 * 60_000;
let found = null;
let tick = 0;

while (Date.now() < DEADLINE) {
  await page.waitForTimeout(2000);
  // The canvas is the thing that matters — a node with data-node-id means the
  // editor is genuinely mounted, not merely that the URL looks right.
  const nodes = await page.locator("[data-node-id]").count().catch(() => 0);
  const url = page.url();
  if (++tick % 4 === 0) {
    console.log(`[url] watching… ${url}  (canvas nodes: ${nodes})`);
  }
  if (nodes > 0) { found = url; break; }
}

if (!found) {
  console.error("[url] TIMED OUT — never saw a canvas ([data-node-id]).");
  console.error(`[url] last URL: ${page.url()}`);
  await context.storageState({ path: STATE });
  await browser.close();
  process.exit(1);
}

writeFileSync(OUT, found, "utf-8");
// Refresh the session too, in case tokens rotated while navigating.
await context.storageState({ path: STATE });
console.log(`[url] EDITOR_URL=${found}`);
console.log(`[url] saved -> ${OUT}`);
await browser.close();
console.log("[url] done.");
