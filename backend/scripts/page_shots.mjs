// Look at, and use, every page of a running generated app — signed in. What
// the page reviewer (services/blueprint/page_review.py) judges from.
//
//   node page_shots.mjs <config.json>
//   config = { baseUrl, email, password, outDir, width?, height?, probe?,
//              states?, pages: [{ id, route, entity?, cookies?, anonymous?, group? }] }
//
// `states: false` skips the empty and missing-record openings (Smith's
// `open_page` asks how ONE page behaves, not how it degrades). A page with
// `anonymous` is opened signed out.
//
// For each page:
//   * the page as it is — screenshot, HTTP status, every browser error;
//   * the page EMPTY (the reviewer's server reads no rows when the
//     `forge-review-empty` cookie is set) — does it say so, or crash;
//   * a record page on a record that does not exist — a 404, not a crash;
//   * with `probe`, every control clicked from a fresh load: what happened.
//
// A route with a `[param]` is opened on a real record: the first row of the
// page's entity, read through the app's own data API as the signed-in user —
// in the path (`/orders/[id]`) or in the query, where a screen opens a record
// in its panel (`/support?ticket=[ticket]`). Pages of one `group` are one
// screen opened at different places (a tab, a panel): a control already
// pressed in the group is not pressed again.
// Prints one JSON line: [{ id, route, url, landed, text, status, file, errors[], ms,
//                          tabs[], states: { empty?, missing? }, controls? }];
// a control that opened a dialog carries what it showed (`opened`).
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
fs.mkdirSync(cfg.outDir, { recursive: true });
const browser = await chromium.launch();
const viewport = { width: cfg.width ?? 1440, height: cfg.height ?? 900 };
// The tallest screenshot a reviewer is sent (scale factor 1): under the API's 8000.
const MAX_SHOT_PX = 7800;
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
// the `cookies` of a session minted for that role (one per name the app
// might read); it is opened — and its controls pressed, and its record
// found — as that person. One pair of contexts per distinct session.
const byCookie = new Map();
async function contextsFor(p) {
  if (p.anonymous) {
    if (!byCookie.has("")) {
      const none = await browser.newContext({ viewport });
      byCookie.set("", { ctx: none, emptyCtx: none });
    }
    return byCookie.get("");
  }
  if (!p.cookies?.length) return { ctx, emptyCtx };
  const key = p.cookies[0].value;
  if (!byCookie.has(key)) {
    const own = await browser.newContext({ viewport });
    await own.addCookies(p.cookies);
    const ownEmpty = await browser.newContext({ viewport });
    await ownEmpty.addCookies([...p.cookies, { name: "forge-review-empty", value: "1", url: cfg.baseUrl }]);
    byCookie.set(key, { ctx: own, emptyCtx: ownEmpty });
  }
  return byCookie.get(key);
}

const MISSING_ID = "00000000-0000-4000-8000-000000000000";
const MAX_CONTROLS = 24;

async function firstRow(context, entity) {
  if (!entity) return null;
  try {
    const res = await context.request.get(`${cfg.baseUrl}/api/data/${encodeURIComponent(entity)}?limit=1`);
    const body = await res.json();
    return body?.data?.[0] ?? null;
  } catch { return null; }
}

// EACH [param] BY ITS NAME. `/shop/[slug]` opened on a product's id answered
// "not found", and every look at TCommerce's product page — the one with Add
// to Bag — was a look at the not-found screen (2026-10-06). A param the row
// carries as a field (slug, code) takes that value; any other takes the id.
function fillRoute(url, row) {
  const camel = (s) => s.replace(/[-_]([a-z])/g, (_, c) => c.toUpperCase());
  const [pathPart, query] = url.split("?");
  const filled = pathPart.replace(/\[([^\]]+)\]/g, (_, name) => {
    const v = name === "id" ? row.id : (row[name] ?? row[camel(name)] ?? row.id);
    return encodeURIComponent(String(v));
  });
  // A panel's link names the record by its id, whatever the parameter is called.
  return query === undefined ? filled
    : `${filled}?${query.replace(/\[([^\]]+)\]/g, () => encodeURIComponent(String(row.id)))}`;
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
    // React's development-only notice that some ATTRIBUTES differ between the
    // server's HTML and the browser's (an extension, a generated id): the page
    // renders and works, and a built app never prints it. Three ToroCommerce
    // pages were sent to repair over it (memg8iw6, 2026-10-09).
    if (/A tree hydrated but some attributes of the server rendered HTML didn't match/.test(t)) return;
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
  // THE PICTURE IS THE CHECK'S, NOT THE PAGE'S. A screenshot that could not be
  // taken (the page still moving under a redirect) says nothing about the
  // page: it is the check's note, and the page is judged on what it did.
  let checkerNote = null;
  if (shot) {
    try {
      await unclip(page);
      await page.waitForTimeout(250);
      // At most MAX_SHOT_PX tall: the API refuses an image with a side over
      // 8000, and a long list's full page passed it (wz7a99ir, 2026-10-04).
      const tall = await page.evaluate(() => document.documentElement.scrollHeight).catch(() => viewport.height);
      await page.screenshot({ path: shot, fullPage: true, animations: "disabled", timeout: 30000,
                              clip: { x: 0, y: 0, width: viewport.width, height: Math.min(Math.max(tall, viewport.height), MAX_SHOT_PX) } });
    } catch (e) {
      checkerNote = `no screenshot: ${String(e?.message || e).split("\n")[0].slice(0, 200)}`;
    }
  }
  // What the page SAYS it is — streaming sends a not-found page as HTTP 200.
  const state = await page.locator("[data-forge-page-state]").first()
    .getAttribute("data-forge-page-state", { timeout: 1000 }).catch(() => null);
  // Where the page ended up and what it says: a sign-in that lands on the
  // wrong screen, or a list that is empty, is only visible here.
  const landed = new URL(page.url()).pathname;
  const text = (await page.locator("body").innerText({ timeout: 5000 }).catch(() => "")).slice(0, 6000);
  // The screen's tabs, by what they say — who is shown which is a fact here.
  const tabs = await page.evaluate(() => [...(document.querySelector("main") || document.body)
    .querySelectorAll("[role='tab']")].map((t) => (t.textContent || "").replace(/\s+/g, " ").trim())
    .filter(Boolean)).catch(() => []);
  return { page, status, errors, state, landed, text, tabs, checkerNote };
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

// What a person can press on the page's own content — not the frame's menu,
// not a form's submit (an empty submit only proves validation), not a field.
async function controls(page) {
  return page.evaluate(() => {
    // AN OPEN PANEL OR DIALOG IS WHAT A PERSON CAN PRESS. Behind its overlay
    // the page is inert: a panel opened by its link had the screen's own
    // links pressed behind it, each a five-second timeout read as broken
    // (ToroCommerce, 2026-10-07). Its controls are the ones to try.
    const open = [...document.querySelectorAll("[role='dialog'], [role='alertdialog'], dialog[open]")]
      .filter((d) => { const r = d.getBoundingClientRect(); return r.width && r.height; });
    const modal = open.filter((d) => d.getAttribute("aria-modal") === "true" || d.tagName === "DIALOG").pop();
    const root = modal || document.querySelector("main") || document.body;
    const frame = (el) => el.closest("header, nav[aria-label='Main'], aside");
    const SEL = "button, a[href], [role='button'], [role='menuitem'], [role='tab']";
    const all = [...document.querySelectorAll(SEL)];          // what `press` counts in
    const els = [...root.querySelectorAll(SEL)];
    const out = [];
    const seen = new Set();
    for (const el of els) {
      if (!modal && frame(el) && !el.closest("main")) continue;
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
      // AN OPTION ALREADY CHOSEN. "Dine-in" was the order type a page opened
      // with; pressing it changed nothing, rightly, and read as a dead button
      // (F&B, 2026-10-03). Said by the control itself when it says it, and
      // otherwise found by pressing an option beside it first (`alt`).
      const chosen = ["aria-pressed", "aria-checked", "aria-selected"].some((a) => el.getAttribute(a) === "true")
        || (el.hasAttribute("aria-current") && el.getAttribute("aria-current") !== "false");
      const sibling = href ? null : [...(el.parentElement?.children || [])]
        .find((x) => x !== el && x.matches(SEL) && !x.disabled);
      out.push({ index: all.indexOf(el), label, kind: href ? "link" : "button", href, chosen,
                 alt: sibling ? all.indexOf(sibling) : null });
    }
    return out;
  });
}

function fingerprint(page) {
  return page.evaluate(() => {
    const main = document.querySelector("main") || document.body;
    const open = [...document.querySelectorAll("[role='dialog'], [role='alertdialog'], dialog[open]")];
    // A CHOSEN OPTION IS A CHANGE. A size or a colour pressed in a product's
    // panel says so with aria-pressed and changes no text: it read as a
    // button that does nothing (ToroCommerce, 2026-10-07).
    const chosen = [...document.querySelectorAll(
      "[aria-pressed='true'], [aria-checked='true'], [aria-selected='true'], [data-state='checked'], [data-state='on'], [data-state='active']")]
      .map((el) => (el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 40)).join("|");
    const inside = open.map((d) => d.innerText || "").join("\n");
    return {
      url: location.href,
      text: main.innerText.length + ":" + main.innerText.slice(0, 2000) + "\u0000" + inside.slice(0, 2000),
      dialogs: open.length,
      expanded: [...document.querySelectorAll("[aria-expanded='true']")].length,
      toasts: document.querySelectorAll("[data-sonner-toast]").length,
      chosen,
    };
  });
}

async function press(context, url, control, firstIndex = null) {
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
                 // THE APP SAID NO, ON PURPOSE: a workflow's own refusal ("not enough
                 // stock") answers 422 with `refused`. It is the app working, said
                 // in its words — not a control that is broken (ToroCommerce's plus
                 // button at the stock limit, 2026-10-08).
                 refused: body?.refused === true,
                 error: String(body?.error?.message ?? body?.error ?? "").slice(0, 200) });
  });
  try {
    await page.goto(cfg.baseUrl + url, { waitUntil: "load", timeout: 60000 });
    await page.waitForTimeout(700);
    if (firstIndex !== null) {
      // Another option first, so this one is not the one already chosen.
      await page.locator("button, a[href], [role='button'], [role='menuitem'], [role='tab']")
        .nth(firstIndex).click({ timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(500);
    }
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
          || after.expanded !== before.expanded || after.toasts !== before.toasts || after.text !== before.text
          || after.chosen !== before.chosen) break;
    }
    await page.waitForLoadState("load", { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(calls.length ? 800 : 0);            // let a workflow's reply land
    after = await fingerprint(page).catch(() => after);
    let outcome = "nothing", detail = "no navigation, no request, no visible change";
    // The browser logs a refused workflow's 422 as a console error; that line
    // is the refusal, not a second fault.
    if (calls.some((c) => c.refused)) {
      for (let i = errors.length - 1; i >= 0; i--) {
        if (/Failed to load resource: the server responded with a status of 422/.test(errors[i])) errors.splice(i, 1);
      }
    }
    if (errors.length) {
      outcome = "error"; detail = errors[0];
    } else if (calls.length) {
      const bad = calls.find((c) => (c.failed || c.status >= 400) && !c.refused);
      const refused = calls.find((c) => c.refused);
      outcome = bad ? "workflow-failed" : refused ? "refused" : "workflow";
      detail = bad ? `HTTP ${bad.status}${bad.error ? ": " + bad.error : ""}`
        : refused ? `the app refused: ${refused.error || "no reason given"}` : `ran (${calls.length})`;
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
               || after.toasts > before.toasts || after.text !== before.text || after.chosen !== before.chosen) {
      outcome = "changed";
      detail = dialog ? `asked "${dialog}"` : after.chosen !== before.chosen && after.text === before.text
        ? "it was chosen" : "the page changed";
    }
    // WHAT A DIALOG SHOWS. A dialog that opened counted as working, and what
    // was in it — an add form reading its choices, a record's panel — was
    // never looked at. Read once it has settled; a crash inside it after it
    // opened is still this press's error.
    let opened = null;
    if (outcome === "changed" && after.dialogs > before.dialogs) {
      await page.waitForTimeout(800);
      opened = await page.evaluate(() => {
        const all = document.querySelectorAll("[role='dialog'], [role='alertdialog'], dialog[open]");
        return all.length ? (all[all.length - 1].innerText || "").slice(0, 3000) : null;
      }).catch(() => null);
      if (errors.length) { outcome = "error"; detail = `inside the dialog it opened: ${errors[0]}`; }
    }
    return { label: control.label, kind: control.kind, outcome, detail, ...(opened !== null ? { opened } : {}) };
  } catch (e) {
    return { label: control.label, kind: control.kind, outcome: "error",
             detail: `could not be pressed: ${e.message.split("\n")[0].slice(0, 200)}` };
  } finally {
    await page.close();
  }
}

// ---------------------------------------------------------------------------

const out = [];
const pressedIn = new Set();          // `${group}|${control}` — a screen's control is pressed once
// ONE PAGE'S TROUBLE IS ITS OWN. A screenshot that threw on one customer
// page ended the whole run, and every page of that person was reported "could
// not be opened" and handed to Smith to repair — a fault in this script, sent
// to be fixed in the app (memg8iw6, 2026-10-09). What throws here is recorded
// against the page as the CHECK's failure (`checkerError`), never its own.
async function visit(p) {
  if (p.signIn) {
    // SIGNING IN, THROUGH THE FORM, as a person does: where it lands is the
    // app's answer to "the admin lands on the customers' menu", and only the
    // form's own redirect shows it.
    const fresh = await browser.newContext({ viewport });
    const page = await fresh.newPage();
    const errors = watch(page);
    let status = null;
    try {
      // A dev server compiling for the first time reloads the page under a
      // redirect ("Fast Refresh will perform a full reload"): the sign-in
      // succeeds and the person is left on the form. Warm it first, and
      // submit once more if a reload took the redirect away.
      await page.goto(cfg.baseUrl + p.route, { waitUntil: "networkidle", timeout: 120000 }).catch(() => {});
      await page.waitForTimeout(3000);
      for (let attempt = 0; attempt < 2; attempt++) {
        const res = await page.goto(cfg.baseUrl + p.route, { waitUntil: "load", timeout: 120000 });
        status = res?.status() ?? null;
        const before = new URL(page.url()).pathname;
        await page.locator('input[type="email"], input[name="email"]').first().fill(cfg.email, { timeout: 15000 });
        await page.locator('input[type="password"]').first().fill(cfg.password, { timeout: 15000 });
        await page.locator('button[type="submit"], form button').first().click({ timeout: 15000 });
        await page.waitForURL((u) => new URL(u.toString()).pathname !== before, { timeout: 60000 }).catch(() => {});
        await page.waitForLoadState("load").catch(() => {});
        await page.waitForTimeout(1500);
        if (new URL(page.url()).pathname !== before) break;
        await page.context().clearCookies();
      }
    } catch (e) {
      errors.push(`sign-in: ${e.message.split("\n")[0]}`.slice(0, 400));
    }
    const landed = new URL(page.url()).pathname;
    const text = (await page.locator("body").innerText({ timeout: 5000 }).catch(() => "")).slice(0, 6000);
    out.push({ id: p.id, route: p.route, url: p.route, as: p.as ?? null, status, landed, text,
               signedIn: true, errors: [...new Set(errors)].slice(0, 12), states: {} });
    await fresh.close();
    return;
  }
  let url = p.route;
  const who = await contextsFor(p);
  const isRecord = /\[[^\]]+\]/.test(url);
  if (isRecord) {
    const row = await firstRow(who.ctx, p.entity);
    if (!row?.id) { out.push({ id: p.id, route: p.route, skipped: "no record to open" }); return; }
    url = fillRoute(url, row);
  }
  const t0 = Date.now();
  const file = path.join(cfg.outDir, `${p.id}.png`);
  const main = await open(who.ctx, url, { shot: file });
  const result = { id: p.id, route: p.route, url, as: p.as ?? null, status: main.status, state: main.state,
                   landed: main.landed, text: main.text, tabs: main.tabs,
                   file, errors: [...new Set(main.errors)].slice(0, 12), states: {},
                   ...(main.checkerNote ? { checkerNote: main.checkerNote } : {}) };
  let found = [];
  if (cfg.probe) found = await controls(main.page).catch(() => []);
  await main.page.close();

  if (cfg.states === false) {
    // asked about the page as it is, not about its degraded states
  } else if (!isRecord) {
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
    const fresh = found.filter((c) => {
      if (!p.group) return true;
      const key = `${p.group}|${c.kind}|${c.label}|${(c.href || "").replace(/[0-9a-f-]{8,}/gi, ":id")}`;
      if (pressedIn.has(key)) return false;
      pressedIn.add(key);
      return true;
    });
    for (const c of fresh.slice(0, MAX_CONTROLS)) {
      // A DEAD CONTROL IS DEAD TWICE. The first press of a link on a cold dev
      // server compiles the page it opens, and F&B's working Edit link read
      // as "does nothing when pressed" (2026-10-01) — a false finding that
      // sends Smith to fix what works. Pressed again, the page is compiled.
      let outcome = await press(who.ctx, url, c);
      if (outcome.outcome === "nothing") outcome = await press(who.ctx, url, c);
      if (outcome.outcome === "nothing" && c.chosen) {
        outcome = { ...outcome, outcome: "chosen", detail: "the option already chosen" };
      } else if (outcome.outcome === "nothing" && c.alt !== null) {
        const again = await press(who.ctx, url, c, c.alt);
        if (again.outcome !== "nothing") {
          outcome = { ...again, detail: `the option already chosen; after another is chosen it ${again.detail}` };
        }
      }
      result.controls.push(outcome);
    }
  }
  result.ms = Date.now() - t0;
  out.push(result);
}

for (const p of cfg.pages) {
  try {
    await visit(p);
  } catch (e) {
    out.push({ id: p.id, route: p.route, as: p.as ?? null,
               checkerError: String(e?.message || e).split("\n")[0].slice(0, 300) });
  }
}
console.log(JSON.stringify(out));
await browser.close();
