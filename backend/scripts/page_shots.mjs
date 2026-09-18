// Screenshot pages of a running generated app, signed in — what the page
// reviewer (services/blueprint/page_review.py) looks at.
//
//   node page_shots.mjs <config.json>
//   config = { baseUrl, email, password, outDir, width?, height?,
//              pages: [{ id, route, entity? }] }
//
// A route with a `[param]` is opened on a real record: the first row of the
// page's entity, read through the app's own data API as the signed-in user.
// Prints one JSON line: [{ id, route, url, status, file, errors[], ms }].
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
fs.mkdirSync(cfg.outDir, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: cfg.width ?? 1440, height: cfg.height ?? 900 } });

// NextAuth's own credentials endpoint; the session cookie lands in this context.
const { csrfToken } = await (await ctx.request.get(`${cfg.baseUrl}/api/auth/csrf`)).json();
await ctx.request.post(`${cfg.baseUrl}/api/auth/callback/credentials`, {
  form: { csrfToken, email: cfg.email, password: cfg.password, json: "true" },
});
const session = await (await ctx.request.get(`${cfg.baseUrl}/api/auth/session`)).json().catch(() => ({}));
if (!session?.user) {
  console.log(JSON.stringify({ error: "could not sign in" }));
  process.exit(2);
}

async function firstId(entity) {
  if (!entity) return null;
  try {
    const res = await ctx.request.get(`${cfg.baseUrl}/api/data/${encodeURIComponent(entity)}?limit=1`);
    const body = await res.json();
    return body?.data?.[0]?.id ?? null;
  } catch { return null; }
}

// The shell scrolls its main column, so a full-page screenshot would stop at
// the viewport. Let every scroll container grow to its content first.
async function unclip(page) {
  await page.evaluate(() => {
    for (const el of document.querySelectorAll("body *")) {
      const s = getComputedStyle(el);
      if ((s.overflowY === "auto" || s.overflowY === "scroll") && el.scrollHeight > el.clientHeight + 4) {
        // The container and every ancestor that pins it to the viewport
        // (`h-screen overflow-hidden` shells) grow to the content.
        for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
          n.style.overflow = "visible";
          n.style.height = "auto";
          n.style.maxHeight = "none";
        }
      }
    }
    document.documentElement.style.height = "auto";
    document.body.style.height = "auto";
  });
}

const out = [];
for (const p of cfg.pages) {
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`.slice(0, 400)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 400)); });
  let url = p.route;
  if (/\[[^\]]+\]/.test(url)) {
    const id = await firstId(p.entity);
    if (!id) { out.push({ id: p.id, route: p.route, skipped: "no record to open" }); await page.close(); continue; }
    url = url.replace(/\[[^\]]+\]/g, id);
  }
  const t0 = Date.now();
  let status = null;
  try {
    const res = await page.goto(cfg.baseUrl + url, { waitUntil: "load", timeout: 120000 });
    status = res?.status() ?? null;
    await page.waitForTimeout(1200);
    await unclip(page);
    await page.waitForTimeout(300);
  } catch (e) {
    errors.push(`navigation: ${e.message}`.slice(0, 400));
  }
  const file = path.join(cfg.outDir, `${p.id}.png`);
  await page.screenshot({ path: file, fullPage: true, animations: "disabled", timeout: 30000 }).catch((e) => errors.push(`screenshot: ${e.message}`));
  out.push({ id: p.id, route: p.route, url, status, file, errors: [...new Set(errors)].slice(0, 12), ms: Date.now() - t0 });
  await page.close();
}
console.log(JSON.stringify(out));
await browser.close();
