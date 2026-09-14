/**
 * SWEEP — the Bindings surface. The trickiest tab, so the rules are strictest.
 *
 * ── Why a naive sweep here is worthless ─────────────────────────────────────
 * There are TWO binding forms and only one can ever render:
 *   "{{expr}}"            written by updateProp   -> resolved by interpolateDeep
 *   { $binding: "expr" }  written by bindProp     -> NEVER resolved; `$binding`
 *                                                    appears nowhere in
 *                                                    renderer/engine/library
 * The Props-tab bind toggle emits the SECOND form for every prop except the six
 * names in DATA_SOURCE_PROPS (data, rows, options, items, entries, records).
 * So a sweep that toggles "bind" on every prop and checks the DOM would report
 * ~90 separate bugs for ONE architectural fact. That is counted once, here, and
 * never multiplied per prop.
 *
 * ── The oracle ──────────────────────────────────────────────────────────────
 * An unresolved WHOLE template survives into the DOM as the literal `{{expr}}`
 * (interpolate.ts:165-175, pinned by interpolate.test.ts:64). Resolved-but-empty
 * renders "". So:
 *   literal "{{...}}" present  -> NEVER RESOLVED
 *   absent, content changed    -> RESOLVED
 * Table and Chart additionally stamp data-forge-empty, separating "drew nothing"
 * from "legitimately empty".
 *
 * ── Rules that prevent false reports ────────────────────────────────────────
 * 1. previewData MUST be non-empty first. A 404 yields {} and makes EVERY
 *    binding look broken — ~43 false reports in one stroke.
 * 2. Only dataSource-rooted expressions are scored. The scopes the dropdown
 *    offers — form., state., global., row. — CANNOT resolve in this runtime
 *    (no such keys are ever injected) and are indistinguishable in the DOM from
 *    a genuine failure. They are reported as NOT-APPLICABLE, never as failures.
 *    `global.user.id` in particular is simply a wrong dropdown option: the real
 *    key is `user`.
 * 3. Never bind a boolean field — `false` is folded in with unresolved.
 * 4. ROW_TEMPLATE_PROPS (rowHref, eventHref, cardHref, rowActions, bulkActions)
 *    are deliberately NOT interpolated (dispatch.tsx:45) — excluded.
 */
import { test, expect, type Page } from "@playwright/test";
import { writeFileSync, mkdirSync, readFileSync } from "node:fs";
import { starterRegistry } from "@forge/registry";

const CANVAS = "[data-canvas-root]";
const OUT = "tests/e2e/sweep-bindings.json";
const API = process.env.E2E_API ?? "http://localhost:6500";
const SCRATCH = process.env.E2E_SCRATCH ?? "e2e-scratch";

/** Only these six get the resolvable "{{expr}}" form from the panel. */
const DATA_SOURCE_PROPS = new Set(["data", "rows", "options", "items", "entries", "records"]);
/** Deliberately un-interpolated by the renderer. */
const ROW_TEMPLATE_PROPS = new Set(["rowHref", "eventHref", "cardHref", "rowActions", "bulkActions"]);
/** Declared in the scratch page — the only roots that can legitimately resolve. */
const RESOLVABLE_ROOTS = ["items", "itemStats", "stats", "user", "currentUser", "Item", "item", "overview"];

type Row = Record<string, unknown>;
const rows: Row[] = [];
const harness: string[] = [];
const flush = () => {
  mkdirSync("tests/e2e", { recursive: true });
  writeFileSync(OUT, JSON.stringify({ rows, harness }, null, 1), "utf-8");
};

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

/** Type a whole-template expression into the control labelled with the prop name. */
async function bindProp(page: Page, prop: string, expr: string) {
  return page.evaluate(({ prop, expr }) => {
    const l = Array.from(document.querySelectorAll("label")).find((x) => {
      const s = x.querySelector("span");
      return s && (s.textContent ?? "").trim() === prop;
    });
    if (!l) return { ok: false, reason: "no label" };
    // BindingControl renders a <select> of known sources AND a free-text input.
    const sel = l.parentElement?.querySelector("select") as HTMLSelectElement | null;
    if (sel) {
      const match = Array.from(sel.options).find((o) => o.value === expr);
      if (match) {
        const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
        setter?.call(sel, match.value);
        sel.dispatchEvent(new Event("change", { bubbles: true }));
        return { ok: true, via: "select", value: match.value };
      }
    }
    const input = l.querySelector("input") as HTMLInputElement | null;
    if (!input) return { ok: false, reason: "no select option and no text input" };
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(input, expr);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    input.dispatchEvent(new FocusEvent("blur", { bubbles: true }));
    return { ok: true, via: "text", value: expr };
  }, { prop, expr });
}

test("sweep bindings for every in-scope component", async ({ page }) => {
  page.on("pageerror", (e) => harness.push(`pageerror: ${e.message.slice(0, 160)}`));

  // ---- RULE 1: previewData must be non-empty, or nothing may be scored -----
  const pd = await fetch(`${API}/api/_debug/preview-data/${SCRATCH}`);
  const pdBody = pd.ok ? await pd.json() : null;
  const pdKeys = pdBody ? Object.keys(pdBody) : [];
  console.log(`[BIND] previewData status=${pd.status} keys=${pdKeys.length} :: ${pdKeys.slice(0, 8).join(", ")}`);
  if (pdKeys.length === 0) {
    harness.push("previewData is EMPTY — every binding would look broken; refusing to score");
    flush();
    test.skip(true, "previewData empty");
  }

  const names: string[] = JSON.parse(readFileSync("tests/e2e/.auth/components.json", "utf-8"));
  await openEditor(page);

  for (const [i, name] of names.entries()) {
    const entry = (starterRegistry as any)[name];
    const props = Object.entries(entry?.props ?? {}) as Array<[string, any]>;

    // Only props that can receive the RESOLVABLE form are scorable.
    const scorable = props.filter(([p]) => DATA_SOURCE_PROPS.has(p) && !ROW_TEMPLATE_PROPS.has(p));
    const unscorable = props.filter(([p]) => !DATA_SOURCE_PROPS.has(p) && !ROW_TEMPLATE_PROPS.has(p));

    // Record the architectural fact once per component, not once per prop.
    if (unscorable.length) {
      rows.push({
        component: name, prop: `(${unscorable.length} props)`, status: "NOT-APPLICABLE",
        detail: "bind toggle emits {$binding}, which the renderer never resolves — one architectural defect, counted once",
      });
    }
    if (!scorable.length) { if ((i + 1) % 15 === 0) flush(); continue; }

    if ((await page.locator(CANVAS).count()) === 0) await openEditor(page).catch(() => {});
    const before = await page.locator(`${CANVAS} [data-node-id]`).count();
    await drop(page, name);
    await page.waitForTimeout(400);
    if ((await page.locator(`${CANVAS} [data-node-id]`).count()) <= before) {
      rows.push({ component: name, prop: "*", status: "HARNESS-BLOCKED", detail: "drop refused" });
      continue;
    }
    const nodeId = await page.locator(`${CANVAS} [data-node-id]`).last()
      .getAttribute("data-node-id").catch(() => null);

    const right = page.locator("aside").filter({ has: page.getByRole("button", { name: /^props$/i }) }).first();
    await right.getByRole("button", { name: /^props$/i }).first().click().catch(() => {});
    await page.waitForTimeout(250);

    for (const [prop] of scorable) {
      const expr = "items";                       // a declared dataSource on the scratch page
      const r: any = await bindProp(page, prop, expr);
      if (!r.ok) { rows.push({ component: name, prop, status: "HARNESS-BLOCKED", detail: r.reason }); continue; }
      await page.waitForTimeout(420);

      const html = await page.evaluate((n) =>
        document.querySelector(`[data-node-id="${n}"]`)?.outerHTML ?? "", nodeId ?? "");
      const literal = /\{\{[^}]+\}\}/.test(html);
      const emptyMarker = /data-forge-empty/.test(html);

      rows.push({
        component: name, prop, expr, via: r.via,
        status: literal ? "NEVER-RESOLVED" : emptyMarker ? "RESOLVED-EMPTY" : "RESOLVED",
        detail: literal ? "literal {{…}} survived into the DOM" : undefined,
      });
    }

    await page.locator(`${CANVAS} [data-node-id]`).last().click({ force: true }).catch(() => {});
    await page.waitForTimeout(120);
    await page.keyboard.press("Delete").catch(() => {});
    await page.waitForTimeout(180);
    if ((i + 1) % 10 === 0) { flush(); console.log(`[BIND] ${i + 1}/${names.length}`); }
  }

  flush();
  const tally: Record<string, number> = {};
  for (const r of rows) tally[String(r.status)] = (tally[String(r.status)] ?? 0) + 1;
  console.log(`[BIND] DONE ${JSON.stringify(tally)}`);
  expect(rows.length).toBeGreaterThan(0);
});
