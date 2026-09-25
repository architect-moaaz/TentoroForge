// Look at, and use, every page of a running generated app — signed in. What
// the page reviewer (services/blueprint/page_review.py) judges from.
//
//   node page_shots.mjs <config.json>
//   config = { baseUrl, email, password, outDir, width?, height?, probe?,
//              pages: [{ id, route, entity? }] }
//
// For each page:
//   * the page as it is — screenshot, HTTP status, every browser error;
//   * the page EMPTY (the reviewer's server reads no rows when the
//     `forge-review-empty` cookie is set) — does it say so, or crash;
//   * a record page on a record that does not exist — a 404, not a crash;
//   * with `probe`, every control clicked from a fresh load: what happened.
//
// A route with a `[param]` is opened on a real record: the first row of the
// page's entity, read through the app's own data API as the signed-in user.
// Prints one JSON line: [{ id, route, url, status, file, errors[], ms,
//                          states: { empty?, missing? }, controls? }].
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
fs.mkdirSync(cfg.outDir, { recursive: true });
const browser = await chromium.launch();
const viewport = { width: cfg.width ?? 1440, height: cfg.height ?? 900 };
const ctx = await browser.newContext({ viewport });

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
// The same session, reading an application with no rows.
const emptyCtx = await browser.newContext({ viewport });
await emptyCtx.addCookies([...(await ctx.cookies()),
  { name: "forge-review-empty", value: "1", url: cfg.baseUrl }]);

// A page restricted to a role the administrator does not hold arrives with
// the `cookie` of a session minted for that role; it is opened — and its
// controls pressed, and its record found — as that person. One pair of
// contexts per distinct session.
const byCookie = new Map();
async function contextsFor(p) {
  if (!p.cookie) return { ctx, emptyCtx };
  const key = p.cookie.value;
  if (!byCookie.has(key)) {
    const own = await browser.newContext({ viewport });
    await own.addCookies([p.cookie]);
    const ownEmpty = await browser.newContext({ viewport });
    await ownEmpty.addCookies([p.cookie, { name: "forge-review-empty", value: "1", url: cfg.baseUrl }]);
    byCookie.set(key, { ctx: own, emptyCtx: ownEmpty });
  }
  return byCookie.get(key);
}

const MISSING_ID = "00000000-0000-4000-8000-000000000000";
const MAX_CONTROLS = 24;

async function firstId(context, entity) {
  if (!entity) return null;
  try {
    const res = await context.request.get(`${cfg.baseUrl}/api/data/${encodeURIComponent(entity)}?limit=1`);
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

function watch(page) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`.slice(0, 400)));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    // A 404 the page asked for is not the page crashing; the status says so.
    if (/Failed to load resource: the server responded with a status of 404/.test(t)) return;
    errors.push(t.slice(0, 400));
  });
  return errors;
}

async function open(context, url, { shot } = {}) {
  const page = await context.newPage();
  const errors = watch(page);
  let status = null;
  try {
    const res = await page.goto(cfg.baseUrl + url, { waitUntil: "load", timeout: 120000 });
    status = res?.status() ?? null;
    await page.waitForTimeout(1000);
  } catch (e) {
    errors.push(`navigation: ${e.message}`.slice(0, 400));
  }
  if (shot) {
    await unclip(page);
    await page.waitForTimeout(250);
    await page.screenshot({ path: shot, fullPage: true, animations: "disabled", timeout: 30000 })
      .catch((e) => errors.push(`screenshot: ${e.message}`));
  }
  // What the page SAYS it is — streaming sends a not-found page as HTTP 200.
  const state = await page.locator("[data-forge-page-state]").first()
    .getAttribute("data-forge-page-state", { timeout: 1000 }).catch(() => null);
  return { page, status, errors, state };
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

// What a person can press on the page's own content — not the frame's menu,
// not a form's submit (an empty submit only proves validation), not a field.
async function controls(page) {
  return page.evaluate(() => {
    const root = document.querySelector("main") || document.body;
    const frame = (el) => el.closest("header, nav[aria-label='Main'], aside");
    const SEL = "button, a[href], [role='button'], [role='menuitem'], [role='tab']";
    const all = [...document.querySelectorAll(SEL)];          // what `press` counts in
    const els = [...root.querySelectorAll(SEL)];
    const out = [];
    const seen = new Set();
    for (const el of els) {
      if (frame(el) && !el.closest("main")) continue;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      const style = getComputedStyle(el);
      if (style.visibility === "hidden" || style.display === "none") continue;
      if (el.disabled || el.getAttribute("aria-disabled") === "true") continue;
      if (el.tagName === "BUTTON" && (el.type === "submit" || el.closest("form"))) continue;
      const href = el.getAttribute("href") || "";
      if (href && (/^(mailto:|tel:|#)/.test(href) || /^https?:\/\//.test(href) && !href.startsWith(location.origin))) continue;
      const label = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("title") || "")
        .replace(/\s+/g, " ").trim().slice(0, 60) || `(${el.tagName.toLowerCase()} with no label)`;
      // One of each: a table's twenty "Edit" buttons are one control.
      const key = `${el.tagName}|${label}|${href.replace(/[0-9a-f-]{8,}/gi, ":id")}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ index: all.indexOf(el), label, kind: href ? "link" : "button", href });
    }
    return out;
  });
}

function fingerprint(page) {
  return page.evaluate(() => {
    const main = document.querySelector("main") || document.body;
    return {
      url: location.href,
      text: main.innerText.length + ":" + main.innerText.slice(0, 2000),
      dialogs: document.querySelectorAll("[role='dialog'], [role='alertdialog'], dialog[open]").length,
      expanded: [...document.querySelectorAll("[aria-expanded='true']")].length,
      toasts: document.querySelectorAll("[data-sonner-toast]").length,
    };
  });
}

async function press(context, url, control) {
  const page = await context.newPage();
  const errors = watch(page);
  const calls = [];
  let dialog = null;
  page.on("dialog", async (d) => { dialog = d.message().slice(0, 120); await d.accept().catch(() => {}); });
  page.on("response", async (res) => {
    const u = res.url();
    if (!/\/api\/workflows\/[^/]+\/execute/.test(u)) return;
    let body = {};
    try { body = await res.json(); } catch { /* not JSON */ }
    calls.push({ status: res.status(), failed: Boolean(body?.error) || body?.status === "failed",
                 error: String(body?.error?.message ?? body?.error ?? "").slice(0, 200) });
  });
  try {
    await page.goto(cfg.baseUrl + url, { waitUntil: "load", timeout: 60000 });
    await page.waitForTimeout(700);
    const before = await fingerprint(page);
    const target = page.locator("button, a[href], [role='button'], [role='menuitem'], [role='tab']")
      .nth(control.index);
    await target.click({ timeout: 5000 });
    // Wait for SOMETHING — a route the dev server has not compiled yet takes
    // seconds to answer the first press, and reading "nothing" at 1.5s made a
    // working link look dead. Up to 8s, stopping at the first change.
    let after = before;
    for (let waited = 0; waited < 8000; waited += 400) {
      await page.waitForTimeout(400);
      after = await fingerprint(page).catch(() => before);
      if (calls.length || dialog || errors.length || after.url !== before.url || after.dialogs !== before.dialogs
          || after.expanded !== before.expanded || after.toasts !== before.toasts || after.text !== before.text) break;
    }
    await page.waitForLoadState("load", { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(calls.length ? 800 : 0);            // let a workflow's reply land
    after = await fingerprint(page).catch(() => after);
    let outcome = "nothing", detail = "no navigation, no request, no visible change";
    if (errors.length) {
      outcome = "error"; detail = errors[0];
    } else if (calls.length) {
      const bad = calls.find((c) => c.failed || c.status >= 400);
      outcome = bad ? "workflow-failed" : "workflow";
      detail = bad ? `HTTP ${bad.status}${bad.error ? ": " + bad.error : ""}` : `ran (${calls.length})`;
    } else if (after.url !== before.url) {
      const res = await context.request.get(after.url).catch(() => null);
      const status = res?.status() ?? 0;
      // Where it landed, as the page says — a streamed not-found is HTTP 200.
      const landed = await page.locator("[data-forge-page-state]").first()
        .getAttribute("data-forge-page-state", { timeout: 1000 }).catch(() => null);
      const bad = status >= 400 || (landed && landed !== "loading");
      outcome = bad ? "broken-link" : "navigated";
      detail = `${new URL(after.url).pathname} (HTTP ${status}${landed ? `, shows the ${landed} page` : ""})`;
    } else if (dialog || after.dialogs > before.dialogs || after.expanded !== before.expanded
               || after.toasts > before.toasts || after.text !== before.text) {
      outcome = "changed";
      detail = dialog ? `asked "${dialog}"` : "the page changed";
    }
    return { label: control.label, kind: control.kind, outcome, detail };
  } catch (e) {
    return { label: control.label, kind: control.kind, outcome: "error",
             detail: `could not be pressed: ${e.message.split("\n")[0].slice(0, 200)}` };
  } finally {
    await page.close();
  }
}

// ---------------------------------------------------------------------------

const out = [];
for (const p of cfg.pages) {
  let url = p.route;
  const who = await contextsFor(p);
  const isRecord = /\[[^\]]+\]/.test(url);
  if (isRecord) {
    const id = await firstId(who.ctx, p.entity);
    if (!id) { out.push({ id: p.id, route: p.route, skipped: "no record to open" }); continue; }
    url = url.replace(/\[[^\]]+\]/g, id);
  }
  const t0 = Date.now();
  const file = path.join(cfg.outDir, `${p.id}.png`);
  const main = await open(who.ctx, url, { shot: file });
  const result = { id: p.id, route: p.route, url, as: p.as ?? null, status: main.status, state: main.state,
                   file, errors: [...new Set(main.errors)].slice(0, 12), states: {} };
  let found = [];
  if (cfg.probe) found = await controls(main.page).catch(() => []);
  await main.page.close();

  if (!isRecord) {
    const emptyShot = path.join(cfg.outDir, `${p.id}.empty.png`);
    const e = await open(who.emptyCtx, url, { shot: emptyShot });
    result.states.empty = { status: e.status, errors: [...new Set(e.errors)].slice(0, 8), file: emptyShot };
    await e.page.close();
  } else {
    const missingUrl = p.route.replace(/\[[^\]]+\]/g, MISSING_ID);
    const m = await open(who.ctx, missingUrl);
    result.states.missing = { status: m.status, state: m.state, errors: [...new Set(m.errors)].slice(0, 8) };
    await m.page.close();
  }

  if (cfg.probe) {
    result.controls = [];
    for (const c of found.slice(0, MAX_CONTROLS)) result.controls.push(await press(who.ctx, url, c));
  }
  result.ms = Date.now() - t0;
  out.push(result);
}
console.log(JSON.stringify(out));
await browser.close();
