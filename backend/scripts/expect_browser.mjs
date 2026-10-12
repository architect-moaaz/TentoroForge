// The hands of the expectation runner (services/expects/runner.py): a browser
// that does what it is told, one person at a time, and reports what happened.
// Python is the head — it decides what to do and judges what came back.
//
//   node expect_browser.mjs            (commands on stdin, one JSON per line)
//
// Each command is `{ id, cmd, ...args }`; each answer is `{ id, ok, ... }` or
// `{ id, ok: false, error }`, one JSON per line on stdout.
//
//   person   { key, base }                a new browser context: one person
//   goto     { key, url }                 open an address; what it gave
//   look     { key }                      where they are, the text, the controls
//   act      { key, actions }             do things to controls; what the app answered
//   signin   { key, url, email, password } sign in through the page's own form
//   api      { key, method, path, body }  a request as this person (their cookies)
//   cookies  { key }                      this person's cookies
//   reload   { key }
//   close    { key }
//
// THE CONTROLS ARE NUMBERED ON EACH LOOK. `look` marks every visible control
// with `data-exp-idx` and describes it (role, name, label, value, options);
// `act` targets them by that number. Python matches a remembered control to
// a fresh look by its description, never by the number.
import { chromium } from "playwright";
import readline from "node:readline";

const browser = await chromium.launch();
const people = new Map(); // key -> { ctx, page, base, errors, calls, dialogs }
const TEXT_MAX = 6000;
// What an upload sends: a small picture, or a one-page PDF when a document is asked for.
const PNG = "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAF0lEQVR4nGP8z8BQz0AEYBxVSF+FAAhKDveksOjmAAAAAElFTkSuQmCC";
const PDF = "JVBERi0xLjQKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+PgplbmRvYmoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0tpZHNbMyAwIFJdL0NvdW50IDE+PgplbmRvYmoKMyAwIG9iago8PC9UeXBlL1BhZ2UvUGFyZW50IDIgMCBSL01lZGlhQm94WzAgMCA2MTIgNzkyXT4+CmVuZG9iagp0cmFpbGVyCjw8L1Jvb3QgMSAwIFI+PgolJUVPRgo=";

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

function sameOrigin(base, url) {
  try { return new URL(url).origin === new URL(base).origin; } catch { return false; }
}

async function newPerson(key, base, state) {
  // `state`: a signed-in session kept from an earlier statement (cookies),
  // so a person who is not what the statement is about is not signed in
  // through the form again.
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 },
                                         ...(state ? { storageState: state } : {}) });
  const page = await ctx.newPage();
  const who = { ctx, page, base, errors: [], calls: [], dialogs: [] };
  page.on("pageerror", (e) => who.errors.push(String(e?.message || e).slice(0, 300)));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    // A 404 the page asked for is not the page failing, and React's
    // development-only attribute notice never appears in a built app.
    if (/Failed to load resource: the server responded with a status of 404/.test(t)) return;
    if (/A tree hydrated but some attributes of the server rendered HTML didn't match/.test(t)) return;
    who.errors.push(t.slice(0, 300));
  });
  page.on("dialog", async (d) => { who.dialogs.push(d.message().slice(0, 300)); await d.accept().catch(() => {}); });
  page.on("response", async (res) => {
    const req = res.request();
    const url = res.url();
    if (!sameOrigin(base, url) || !new URL(url).pathname.includes("/api/")) return;
    if (/\/api\/auth\/(session|csrf|providers)/.test(url)) return;
    const call = { method: req.method(), path: new URL(url).pathname, status: res.status(), body: "" };
    if (req.method() !== "GET" || res.status() >= 400) {
      call.body = (await res.text().catch(() => "")).slice(0, 600);
      // What the screen SENT, beside what came back: a process that ran and
      // wrote nothing was often handed a field under another name, and only
      // the request shows it.
      if (req.method() !== "GET") call.sent = String(req.postData() || "").slice(0, 600);
    }
    who.calls.push(call);
  });
  people.set(key, who);
  return who;
}

function get(key) {
  const who = people.get(key);
  if (!who) throw new Error(`no person ${key}`);
  return who;
}

async function settle(page, ms = 4000) {
  await page.waitForLoadState("domcontentloaded", { timeout: ms }).catch(() => {});
  await page.waitForLoadState("networkidle", { timeout: ms }).catch(() => {});
  await page.waitForTimeout(250);
}

async function text(page) {
  const t = await page.evaluate(() => document.body ? document.body.innerText : "").catch(() => "");
  return String(t || "").replace(/\n{3,}/g, "\n\n").slice(0, TEXT_MAX);
}

// What the app said out loud: toasts, alerts, status regions, invalid fields.
async function said(page, within = null) {
  return page.evaluate((within) => {
    const out = [];
    const sel = '[role="alert"], [role="status"], [data-sonner-toast], [aria-live="assertive"], [aria-live="polite"], .toast';
    for (const el of document.querySelectorAll(sel)) {
      const t = (el.innerText || "").trim();
      if (t && !out.includes(t)) out.push(t.slice(0, 300));
    }
    const invalid = [];
    // Only the form the person sent: a screen with several forms keeps the
    // others empty, and their blanks are not this one's refusal.
    const scope = (within !== null && document.querySelector(`[data-exp-idx="${within}"]`)?.closest("form")) || document;
    for (const el of scope.querySelectorAll("input, select, textarea")) {
      if (el.willValidate && !el.checkValidity()) {
        invalid.push((el.getAttribute("name") || el.getAttribute("aria-label") || el.id || el.type) + ": " + el.validationMessage);
      }
    }
    return { messages: out.slice(0, 12), invalid: invalid.slice(0, 12) };
  }, within).catch(() => ({ messages: [], invalid: [] }));
}

// Every visible control, numbered and described.
async function controls(page) {
  return page.evaluate(() => {
    for (const el of document.querySelectorAll("[data-exp-idx]")) el.removeAttribute("data-exp-idx");
    const sel = 'a[href], button, input, select, textarea, [role="button"], [role="link"], [role="checkbox"], ' +
      '[role="radio"], [role="tab"], [role="menuitem"], [role="option"], [role="switch"], [role="combobox"], [contenteditable="true"]';
    const seen = new Set();
    const out = [];
    // AN OPEN DIALOG IS ALL A PERSON CAN USE. A product opened in a panel
    // covers the list behind it; its size chips were listed, chosen, and the
    // click timed out under the panel (torob1, 2026-10-09). With a dialog open,
    // only what is inside the topmost one is offered.
    const dialogs = [...document.querySelectorAll('[role="dialog"], [aria-modal="true"], dialog[open]')]
      .filter((d) => { const r = d.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
    const scope = dialogs.length ? dialogs[dialogs.length - 1] : document;
    const visible = (el) => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
    };
    const labelOf = (el) => {
      if (el.id) {
        const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (l) return l.innerText.trim();
      }
      const wrap = el.closest("label");
      if (wrap) return wrap.innerText.trim();
      const by = el.getAttribute("aria-labelledby");
      if (by) return by.split(/\s+/).map((i) => document.getElementById(i)?.innerText || "").join(" ").trim();
      return "";
    };
    let i = 0;
    for (const el of scope.querySelectorAll(sel)) {
      if (seen.has(el) || !visible(el) || el.closest("[aria-hidden='true']")) continue;
      seen.add(el);
      const tag = el.tagName.toLowerCase();
      const type = (el.getAttribute("type") || "").toLowerCase();
      if (type === "hidden") continue;
      const role = el.getAttribute("role") || (tag === "a" ? "link" : tag === "button" ? "button" :
        tag === "select" ? "select" : tag === "textarea" ? "textbox" :
        tag === "input" ? (["checkbox", "radio"].includes(type) ? type : ["submit", "button"].includes(type) ? "button" :
          type === "file" ? "file" : "textbox") : tag);
      const name = (el.getAttribute("aria-label") || labelOf(el) || (el.innerText || "").trim() ||
        el.getAttribute("placeholder") || el.getAttribute("title") || el.getAttribute("value") || "").replace(/\s+/g, " ").slice(0, 120);
      const row = { idx: i, role, tag, name };
      if (type) row.type = type;
      const nm = el.getAttribute("name"); if (nm) row.field = nm;
      const ph = el.getAttribute("placeholder"); if (ph) row.placeholder = ph.slice(0, 80);
      if (tag === "a") row.href = el.getAttribute("href");
      if (tag === "input" || tag === "textarea") row.value = String(el.value ?? "").slice(0, 80);
      if (tag === "select") {
        row.value = el.value;
        row.options = [...el.options].map((o) => o.text.trim()).slice(0, 30);
      }
      if (["checkbox", "radio"].includes(type)) row.checked = el.checked;
      if (el.getAttribute("aria-pressed")) row.pressed = el.getAttribute("aria-pressed");
      if (el.getAttribute("aria-selected")) row.selected = el.getAttribute("aria-selected");
      if (el.disabled || el.getAttribute("aria-disabled") === "true") row.disabled = true;
      // Where it sits: the nearest heading or card text, so two "Add" buttons differ.
      const card = el.closest("article, li, tr, section, form, [class*='card']");
      if (card) {
        const h = card.querySelector("h1, h2, h3, h4, h5, h6, [class*='title']");
        const t = (h?.innerText || "").trim();
        if (t && t !== row.name) row.within = t.slice(0, 80);
      }
      el.setAttribute("data-exp-idx", String(i));
      out.push(row);
      i += 1;
      if (i >= 250) break;
    }
    return out;
  });
}

async function look(who) {
  return { url: who.page.url(), text: await text(who.page), controls: await controls(who.page),
           ...(await said(who.page)) };
}

// Why an action could not be done: Playwright's first line is only "Timeout
// exceeded"; the reason ("<div …> intercepts pointer events", "element is
// not enabled") is further down its log.
function whyNot(e) {
  const lines = String(e?.message || e).split("\n").map((l) => l.trim()).filter(Boolean);
  const reason = lines.find((l) => /intercepts pointer events|not enabled|not visible|not stable|detached|outside of the viewport/.test(l));
  return (lines[0] + (reason ? ` — ${reason.replace(/^-\s*/, "")}` : "")).slice(0, 300);
}

// A click as a person makes it: if something is over the control — a toast,
// an open menu, a sticky header — they close it or scroll, and click again.
async function clickAsAPerson(page, loc) {
  try {
    await loc.click({ timeout: 5000 });
  } catch (first) {
    await page.keyboard.press("Escape").catch(() => {});
    await loc.scrollIntoViewIfNeeded({ timeout: 2000 }).catch(() => {});
    await page.waitForTimeout(400);
    try {
      await loc.click({ timeout: 5000 });
    } catch {
      throw first;
    }
  }
}

// A choice from a list, as a person makes it: a real <select> takes the
// option; a drop-down built from buttons (a combobox, a menu) is opened and
// the option with that text is pressed.
async function chooseAsAPerson(page, loc, value) {
  const tag = await loc.evaluate((el) => el.tagName.toLowerCase()).catch(() => "");
  if (tag === "select") {
    await loc.selectOption({ label: value }, { timeout: 5000 })
      .catch(() => loc.selectOption(value, { timeout: 5000 }));
    return;
  }
  await clickAsAPerson(page, loc);
  await page.waitForTimeout(300);
  const option = page.getByRole("option", { name: value, exact: true }).first();
  if (await option.count()) { await option.click({ timeout: 5000 }); return; }
  const item = page.getByRole("menuitem", { name: value, exact: true }).first();
  if (await item.count()) { await item.click({ timeout: 5000 }); return; }
  await page.getByText(value, { exact: true }).first().click({ timeout: 5000 });
}

async function act(who, actions) {
  const page = who.page;
  who.calls = [];
  who.dialogs = [];
  const errorsBefore = who.errors.length;
  const done = [];
  for (const a of actions) {
    const loc = page.locator(`[data-exp-idx="${a.idx}"]`).first();
    try {
      if (a.do === "click") await clickAsAPerson(page, loc);
      else if (a.do === "fill") await loc.fill(String(a.value ?? ""), { timeout: 5000 });
      else if (a.do === "select") await chooseAsAPerson(page, loc, String(a.value ?? ""));
      else if (a.do === "check") await loc.check({ timeout: 5000 });
      else if (a.do === "uncheck") await loc.uncheck({ timeout: 5000 });
      else if (a.do === "press") await loc.press(String(a.value || "Enter"), { timeout: 5000 });
      else if (a.do === "upload") await loc.setInputFiles(
        String(a.value || "").toLowerCase().endsWith(".pdf")
          ? { name: "document.pdf", mimeType: "application/pdf", buffer: Buffer.from(PDF, "base64") }
          : { name: "picture.png", mimeType: "image/png", buffer: Buffer.from(PNG, "base64") }, { timeout: 5000 });
      else throw new Error(`unknown action ${a.do}`);
      done.push({ ...a, ok: true });
    } catch (e) {
      done.push({ ...a, ok: false, error: whyNot(e) });
      break;
    }
    await settle(page, 2500);
  }
  await settle(page, 5000);
  const last = [...actions].reverse().find((a) => a.do === "click" || a.do === "press");
  return { done, url: page.url(), calls: who.calls.slice(0, 30), dialogs: who.dialogs,
           errors: who.errors.slice(errorsBefore).slice(0, 10), ...(await said(page, last ? last.idx : null)) };
}

async function signin(who, url, email, password) {
  const page = who.page;
  const res = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await settle(page);
  const emailBox = page.locator('input[type="email"], input[name*="email" i], input[autocomplete="username"], input[name*="user" i]').first();
  const passBox = page.locator('input[type="password"]').first();
  await emailBox.fill(email, { timeout: 10000 });
  await passBox.fill(password, { timeout: 10000 });
  who.calls = [];
  const form = passBox.locator("xpath=ancestor::form[1]");
  const submit = (await form.count())
    ? form.locator('button[type="submit"], input[type="submit"], button:not([type])').first()
    : page.locator('button[type="submit"]').first();
  const before = new URL(page.url()).pathname;
  await submit.click({ timeout: 10000 });
  // Until they have left the sign-in page: a first visit to where they are
  // sent is compiled by the dev server first, and that can take half a minute.
  await page.waitForURL((u) => new URL(u.toString()).pathname !== before, { timeout: 45000 }).catch(() => {});
  await settle(page, 8000);
  return { status: res?.status() ?? 0, url: page.url(), calls: who.calls.slice(0, 20), ...(await said(page)) };
}

const rl = readline.createInterface({ input: process.stdin });
for await (const line of rl) {
  if (!line.trim()) continue;
  let msg;
  try { msg = JSON.parse(line); } catch { continue; }
  const { id, cmd } = msg;
  try {
    let out = {};
    if (cmd === "person") {
      await newPerson(msg.key, msg.base, msg.state);
    } else if (cmd === "state") {
      out = { state: await get(msg.key).ctx.storageState() };
    } else if (cmd === "goto") {
      const who = get(msg.key);
      const errorsBefore = who.errors.length;
      const res = await who.page.goto(msg.url, { waitUntil: "domcontentloaded", timeout: 60000 });
      await settle(who.page);
      out = { status: res?.status() ?? 0, url: who.page.url(), text: await text(who.page),
              errors: who.errors.slice(errorsBefore).slice(0, 10) };
    } else if (cmd === "look") {
      out = await look(get(msg.key));
    } else if (cmd === "act") {
      out = await act(get(msg.key), msg.actions || []);
    } else if (cmd === "signin") {
      out = await signin(get(msg.key), msg.url, msg.email, msg.password);
    } else if (cmd === "apisignin") {
      // NextAuth's credentials endpoint, for a person whose form is not what is tried.
      const who = get(msg.key);
      const { csrfToken } = await (await who.ctx.request.get(new URL("/api/auth/csrf", who.base).toString())).json();
      await who.ctx.request.post(new URL("/api/auth/callback/credentials", who.base).toString(),
        { form: { csrfToken, email: msg.email, password: msg.password, json: "true" } });
      const session = await (await who.ctx.request.get(new URL("/api/auth/session", who.base).toString())).json().catch(() => ({}));
      out = { signedIn: Boolean(session?.user) };
    } else if (cmd === "api") {
      const who = get(msg.key);
      const opts = { headers: { "content-type": "application/json" }, failOnStatusCode: false };
      if (msg.body !== undefined) opts.data = msg.body;
      const res = await who.ctx.request.fetch(new URL(msg.path, who.base).toString(), { method: msg.method || "GET", ...opts });
      out = { status: res.status(), body: (await res.text()).slice(0, 4000) };
    } else if (cmd === "cookies") {
      out = { cookies: await get(msg.key).ctx.cookies() };
    } else if (cmd === "reload") {
      const who = get(msg.key);
      await who.page.reload({ waitUntil: "domcontentloaded" });
      await settle(who.page);
      out = { url: who.page.url() };
    } else if (cmd === "close") {
      const who = people.get(msg.key);
      if (who) { await who.ctx.close().catch(() => {}); people.delete(msg.key); }
    } else if (cmd === "quit") {
      send({ id, ok: true });
      break;
    } else {
      throw new Error(`unknown command ${cmd}`);
    }
    send({ id, ok: true, ...out });
  } catch (e) {
    send({ id, ok: false, error: String(e?.message || e).split("\n")[0].slice(0, 400) });
  }
}
await browser.close();
process.exit(0);
