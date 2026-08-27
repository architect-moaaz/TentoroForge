#!/usr/bin/env node
/**
 * Headless click-through crawler for a running generated app (Slice 1 of the
 * validate→repair loop). Logs in, visits every route, and clicks every button,
 * emitting a structured findings report between the FINDINGS/END sentinels.
 *
 * Usage: node crawl.mjs '<config-json>'
 *   config = { baseUrl, routes: string[], email, password }
 *
 * Requires Playwright (`npx playwright install chromium`). If it's unavailable
 * the script prints an `harness_unavailable` finding and exits 0 so the caller
 * degrades gracefully rather than crashing.
 */

const SENTINEL_START = "===FINDINGS===";
const SENTINEL_END = "===END===";

function emit(findings) {
  process.stdout.write("\n" + SENTINEL_START + "\n" + JSON.stringify({ findings }) + "\n" + SENTINEL_END + "\n");
}

let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  emit([{ type: "harness_unavailable", detail: "playwright not installed (npx playwright install chromium)" }]);
  process.exit(0);
}

const cfg = JSON.parse(process.argv[2] || "{}");
const baseUrl = (cfg.baseUrl || "http://localhost:3000").replace(/\/+$/, "");
const routes = Array.isArray(cfg.routes) && cfg.routes.length ? cfg.routes : ["/"];
const findings = [];

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext();
const page = await ctx.newPage();

// Instrument: console errors + failed responses per current route.
let current = "/";
page.on("console", (m) => {
  if (m.type() === "error") findings.push({ type: "render_error", route: current, detail: m.text().slice(0, 300) });
});
page.on("pageerror", (e) => findings.push({ type: "render_error", route: current, detail: String(e).slice(0, 300) }));
page.on("response", (r) => {
  const s = r.status();
  const u = r.url();
  if (s >= 400 && u.startsWith(baseUrl)) {
    if (u.includes("/api/workflows"))
      findings.push({ type: "dispatch_failed", route: current, status: s, detail: u.replace(baseUrl, "") });
    else if (u.includes("/api/data"))
      findings.push({ type: "data_failed", route: current, status: s, detail: u.replace(baseUrl, "") });
  }
});

async function login() {
  try {
    await page.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded", timeout: 15000 });
    await page.fill('input[type="email"], #email', cfg.email || "admin@example.com");
    await page.fill('input[type="password"], #password', cfg.password || "admin1234");
    await Promise.all([
      page.waitForNavigation({ timeout: 10000 }).catch(() => {}),
      page.click('button[type="submit"]'),
    ]);
  } catch {
    findings.push({ type: "login_failed", detail: "could not complete the login form" });
  }
}

async function visit(route) {
  current = route;
  const target = route.replace(/\[.*?\]/g, "1").replace(/\{\{.*?\}\}/g, "1"); // fill dynamic segs
  let resp;
  try {
    resp = await page.goto(`${baseUrl}${target}`, { waitUntil: "networkidle", timeout: 20000 });
  } catch (e) {
    findings.push({ type: "route_error", route, detail: String(e).slice(0, 200) });
    return;
  }
  if (resp && resp.status() >= 400) {
    findings.push({ type: "route_404", route, status: resp.status() });
    return;
  }
  await clickButtons(route, target);
}

async function clickButtons(route, target) {
  let count;
  try {
    count = await page.locator("button:visible, a[href]:visible").count();
  } catch {
    return;
  }
  for (let i = 0; i < Math.min(count, 40); i++) {
    let el;
    try {
      el = page.locator("button:visible, a[href]:visible").nth(i);
      const label = ((await el.innerText().catch(() => "")) || "").trim().slice(0, 40);
      const href = await el.getAttribute("href").catch(() => null);
      // Skip logout / external / obvious-nav anchors that would derail the crawl.
      if (/sign out|log ?out/i.test(label)) continue;
      await el.click({ timeout: 3000, trial: false }).catch(() => {});
      await page.waitForTimeout(250);
      // If the click navigated to a 404 page, record it.
      const u = page.url();
      if (u !== `${baseUrl}${target}` && u.startsWith(baseUrl)) {
        const r = await page.goto(u, { waitUntil: "domcontentloaded", timeout: 8000 }).catch(() => null);
        if (r && r.status() >= 400) findings.push({ type: "route_404", route: u.replace(baseUrl, ""), status: r.status(), via: `${route}:${label}` });
        // return to the page under test
        await page.goto(`${baseUrl}${target}`, { waitUntil: "domcontentloaded", timeout: 12000 }).catch(() => {});
        current = route;
      }
    } catch {
      /* best-effort per button */
    }
  }
}

await login();
for (const r of routes) await visit(r);
await browser.close();
emit(findings);
