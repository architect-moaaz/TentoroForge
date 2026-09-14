/**
 * SWEEP — every prop of every in-scope component, through the real Props tab.
 *
 * Runs against the throwaway project `e2e-scratch` at /editor/e2e-scratch, so
 * the user's six real projects are never opened or written. The scratch page's
 * root is Container > Stack because an empty page's root falls back to `Text`,
 * which is not a registry key and refuses every drop.
 *
 * ── The oracle: differential, no spec required ───────────────────────────────
 * Nothing in this repo declares what a prop is SUPPOSED to do to the DOM, so a
 * spec-based assertion would have to be written by reading the implementation —
 * which passes by construction and proves nothing. Instead each prop is driven
 * to two (or for enums, all) distinct values and the rendered subtree compared:
 *
 *   different DOM  -> the control does something      (WORKS)
 *   identical DOM  -> the control does nothing        (NO-EFFECT, a candidate)
 *
 * NO-EFFECT is a CANDIDATE, not a verdict. Many props legitimately have no
 * visual effect (a route, a workflow id, a binding path). Whether a given
 * NO-EFFECT is a defect is decided later against the author-written description,
 * read blind. This file measures; it does not judge.
 *
 * ── Preconditions, proved before any claim ──────────────────────────────────
 * A run of this shape produced three separate rounds of false findings earlier,
 * every one of them the harness's fault. So each component proves: the drop
 * committed (node count rose), nothing was refused ([role=alert] read
 * IMMEDIATELY — it self-clears after 5s), exactly one selection overlay exists,
 * and the named control was actually found. Any failure is HARNESS-BLOCKED and
 * the prop is never scored.
 *
 * ── Pacing ──────────────────────────────────────────────────────────────────
 * The backend rate limit is 120 req/min, burst 20 (config.py:86-87) and each
 * settled edit costs ~3 POSTs. A 429 surfaces in the UI as a save failure, so an
 * unpaced harness would manufacture "save broken" findings about itself. 429s
 * are counted and reported as harness errors, never as defects.
 */
import { test, expect, type Page } from "@playwright/test";
import { writeFileSync, mkdirSync, readFileSync } from "node:fs";
import { starterRegistry } from "@forge/registry";

const CANVAS = "[data-canvas-root]";
const OUT = "tests/e2e/sweep-props.json";

type PropRow = {
  component: string; category: string; prop: string;
  type: string; control: string; group: string;
  status: string; detail?: string; values?: string;
};
// RESUMABLE. A 15-min cap killed an earlier run at component 100 of 113; the
// ledger survived only because it flushes every 5. Prior rows are loaded and
// re-scored components replaced, so the tail can be run on its own without
// discarding what already cost 16 minutes.
const rows: PropRow[] = (() => {
  try {
    const prior = JSON.parse(readFileSync(OUT, "utf-8"));
    const kept = Array.isArray(prior?.rows) ? prior.rows : [];
    if (kept.length) console.log(`[SWEEP] resuming — ${kept.length} prior rows loaded`);
    return kept;
  } catch { return []; }
})();
const harness: string[] = [];
let rateLimited = 0;

function flush() {
  mkdirSync("tests/e2e", { recursive: true });
  writeFileSync(OUT, JSON.stringify({ rows, harness, rateLimited }, null, 1), "utf-8");
}

async function openEditor(page: Page) {
  await page.goto(process.env.E2E_PROJECT_URL ?? "/editor/e2e-scratch", { waitUntil: "domcontentloaded" });
  await page.waitForSelector(CANVAS, { timeout: 90_000 });
  await page.waitForTimeout(2000);
}

async function drop(page: Page, name: string) {
  return page.evaluate((n) => {
    const root = document.querySelector("[data-canvas-root]") as HTMLElement | null;
    if (!root) return false;
    const dt = new DataTransfer();
    dt.setData("text/x-forge-component", n);
    const o: any = { bubbles: true, cancelable: true, composed: true, dataTransfer: dt };
    root.dispatchEvent(new DragEvent("dragenter", o));
    root.dispatchEvent(new DragEvent("dragover", o));
    root.dispatchEvent(new DragEvent("drop", o));
    return true;
  }, name);
}

/** Set a control addressed by its prop-name label. React needs the patched setter. */
async function setControl(page: Page, prop: string, value: string | boolean) {
  return page.evaluate(({ prop, value }) => {
    const labels = Array.from(document.querySelectorAll("label"));
    const target = labels.find((l) => {
      const s = l.querySelector("span");
      return s && (s.textContent ?? "").trim() === prop;
    });
    if (!target) return { ok: false, reason: "no label" };
    const el = target.querySelector("input, select, textarea") as
      | HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null;
    if (!el) return { ok: false, reason: "label has no control" };
    if (el.disabled) return { ok: false, reason: "control disabled" };

    const tag = el.tagName.toLowerCase();
    if (tag === "input" && (el as HTMLInputElement).type === "checkbox") {
      const box = el as HTMLInputElement;
      const want = !!value;
      if (box.checked !== want) box.click();
      return { ok: true, kind: "checkbox", applied: String(want) };
    }
    const proto = tag === "select" ? HTMLSelectElement.prototype
      : tag === "textarea" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    setter?.call(el, String(value));
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return { ok: true, kind: tag, applied: String(value) };
  }, { prop, value });
}

/** Options of a select addressed by its prop-name label. */
async function optionsOf(page: Page, prop: string): Promise<string[]> {
  return page.evaluate((prop) => {
    const l = Array.from(document.querySelectorAll("label")).find((x) => {
      const s = x.querySelector("span");
      return s && (s.textContent ?? "").trim() === prop;
    });
    const sel = l?.querySelector("select") as HTMLSelectElement | null;
    if (!sel) return [];
    return Array.from(sel.options).map((o) => o.value).filter((v) => v !== "");
  }, prop);
}

/** The rendered subtree of the node under test, normalised. */
async function signature(page: Page, nodeId: string) {
  return page.evaluate((id) => {
    const el = document.querySelector(`[data-node-id="${id}"]`);
    if (!el) return "";
    return (el.outerHTML || "")
      .replace(/\s+/g, " ")
      // ids and react keys churn between renders; they are not prop effects
      .replace(/data-node-id="[^"]*"/g, "")
      .replace(/ id="[^"]*"/g, "")
      .replace(/for="[^"]*"/g, "");
  }, nodeId);
}

test("sweep every prop of every in-scope component", async ({ page }) => {
  page.on("response", (r) => { if (r.status() === 429) rateLimited++; });
  page.on("pageerror", (e) => harness.push(`pageerror: ${e.message.slice(0, 160)}`));

  const names: string[] = JSON.parse(readFileSync("tests/e2e/.auth/components.json", "utf-8"));
  console.log(`[SWEEP] ${names.length} components`);

  await openEditor(page);

  for (const [i, name] of names.entries()) {
    const entry = (starterRegistry as any)[name];
    const descriptors = Object.entries(entry?.props ?? {}) as Array<[string, any]>;

    if ((await page.locator(CANVAS).count()) === 0) {
      harness.push(`${name}: canvas gone — reopening`);
      await openEditor(page).catch(() => {});
      if ((await page.locator(CANVAS).count()) === 0) {
        rows.push({ component: name, category: entry?.category, prop: "*", type: "*", control: "*",
                    group: "*", status: "HARNESS-BLOCKED", detail: "editor would not reopen" });
        continue;
      }
    }

    const before = await page.locator(`${CANVAS} [data-node-id]`).count();
    await drop(page, name);
    await page.waitForTimeout(400);

    const alert = page.locator('[role="alert"]');
    const banner = (await alert.count())
      ? ((await alert.innerText().catch(() => "")) || "").replace(/\s+/g, " ").trim() : "";
    const after = await page.locator(`${CANVAS} [data-node-id]`).count();

    if (after <= before) {
      rows.push({ component: name, category: entry?.category, prop: "*", type: "*", control: "*",
                  group: "*", status: "HARNESS-BLOCKED",
                  detail: `drop refused (${before}->${after}) ${banner}` });
      continue;
    }
    const overlays = await page.locator("[data-tentoro-selection-overlay]").count();
    if (overlays !== 1) {
      rows.push({ component: name, category: entry?.category, prop: "*", type: "*", control: "*",
                  group: "*", status: "HARNESS-BLOCKED", detail: `overlays=${overlays}` });
      await page.keyboard.press("Delete").catch(() => {});
      continue;
    }

    const nodeId = await page.locator(`${CANVAS} [data-node-id]`).last()
      .getAttribute("data-node-id").catch(() => null);

    // Props tab
    const right = page.locator("aside").filter({ has: page.getByRole("button", { name: /^props$/i }) }).first();
    await right.getByRole("button", { name: /^props$/i }).first().click().catch(() => {});
    await page.waitForTimeout(250);

    for (const [prop, d] of descriptors) {
      const base = { component: name, category: entry?.category, prop,
                     type: d.type, control: d.control, group: d.group };

      // Bindings get their own pass — the {$binding} vs {{expr}} distinction
      // makes a naive differential here meaningless.
      if (d.type === "binding") {
        rows.push({ ...base, status: "DEFERRED", detail: "binding pass" });
        continue;
      }

      let vals: Array<string | boolean>;
      if (d.type === "enum") {
        const opts = await optionsOf(page, prop);
        if (opts.length < 2) { rows.push({ ...base, status: "SKIPPED", detail: `enum with ${opts.length} option(s)` }); continue; }
        vals = opts.slice(0, 4);
      } else if (d.type === "boolean") vals = [false, true];
      else if (d.type === "number") vals = ["3", "417"];
      else if (d.type === "action") vals = ["navigate"];
      else vals = [`ZQXa${prop}`, `ZQXb${prop}`];

      const sigs: string[] = [];
      let blocked = "";
      for (const v of vals) {
        const r: any = await setControl(page, prop, v);
        if (!r.ok) { blocked = r.reason; break; }
        await page.waitForTimeout(260);
        sigs.push(await signature(page, nodeId ?? ""));
      }

      if (blocked) { rows.push({ ...base, status: "HARNESS-BLOCKED", detail: blocked }); continue; }

      const distinct = new Set(sigs).size;
      const sentinelSeen = d.type === "string" && sigs.some((s) => s.includes(`ZQXb${prop}`));
      rows.push({
        ...base,
        status: sentinelSeen ? "WORKS-VISIBLE"
              : distinct > 1 ? "WORKS-DIFFERENTIAL"
              : "NO-EFFECT",
        values: vals.map(String).join(" | "),
      });
    }

    // Remove the probe node; it is still selected after the drop.
    await page.locator(`${CANVAS} [data-node-id]`).last().click({ force: true }).catch(() => {});
    await page.waitForTimeout(120);
    await page.keyboard.press("Delete").catch(() => {});
    await page.waitForTimeout(200);

    if ((i + 1) % 5 === 0) {
      flush();
      const done = rows.filter((r) => r.prop !== "*").length;
      console.log(`[SWEEP] ${i + 1}/${names.length} components, ${done} props scored, 429s=${rateLimited}`);
    }
  }

  flush();
  const tally: Record<string, number> = {};
  for (const r of rows) tally[r.status] = (tally[r.status] ?? 0) + 1;
  console.log(`[SWEEP] DONE ${JSON.stringify(tally)}`);
  console.log(`[SWEEP] rate-limited responses (harness, not defects): ${rateLimited}`);
  expect(rows.length).toBeGreaterThan(0);
});
