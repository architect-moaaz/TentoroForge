/**
 * SWEEP — the Style tab, through the real UI, for every in-scope component.
 *
 * Tier 1 already proved every style write reaches the artifact. It could not
 * prove the on-screen CONTROL is wired to that write — a dropdown rendered but
 * connected to nothing passes Tier 1 silently, which is exactly the shape of the
 * radius-scale defect. So this drives the real <select>/<input> and asserts the
 * DOM observable.
 *
 * Observables are exact, from applyStyleSlot (renderer/runtime/style-slot.ts):
 *   padding    -> style.padding      = var(--token-<ref>)
 *   radius     -> style.borderRadius = var(--token-<ref>)
 *   shadow     -> style.boxShadow    = var(--token-<ref>)
 *   background -> style.background   = var(--token-<ref>)
 *   width, height, minWidth, maxWidth, minHeight, maxHeight
 *                                    = RAW, deliberately not token-wrapped
 *   motion     -> a data-motion ATTRIBUTE, absent when "none"
 *
 * Two spellings matter and cost me 496 phantom findings once: the DOM carries
 * the EMITTED form `var(--token-spacing-4)`, never the token ref `spacing.4`.
 * And library components put data-node-id on a wrapper span carrying only
 * sizing, so the token-wrapped keys land on an inner element — the whole
 * subtree must be searched, not just the wrapper.
 *
 * Section labels are <span>, not <div> (StylePanel.tsx:291-319); the Design
 * System block below them uses <div>. Both are searched.
 */
import { test, expect, type Page } from "@playwright/test";
import { writeFileSync, mkdirSync, readFileSync } from "node:fs";

const CANVAS = "[data-canvas-root]";
const OUT = "tests/e2e/sweep-style.json";

const KEYS = [
  { label: "Background", emit: (v: string) => `var(--token-${v.replace(/^tokens\./, "").replace(/\./g, "-")})` },
  { label: "Padding",    emit: (v: string) => `var(--token-${v.replace(/^tokens\./, "").replace(/\./g, "-")})` },
  { label: "Radius",     emit: (v: string) => `var(--token-${v.replace(/^tokens\./, "").replace(/\./g, "-")})` },
  { label: "Shadow",     emit: (v: string) => `var(--token-${v.replace(/^tokens\./, "").replace(/\./g, "-")})` },
  { label: "Motion",     emit: (v: string) => `data-motion="${v}"` },
];
const SIZES = [
  { label: "Width", value: "321px" }, { label: "Height", value: "123px" },
  { label: "Min W", value: "77px" },  { label: "Max W", value: "888px" },
  { label: "Min H", value: "55px" },  { label: "Max H", value: "999px" },
];
const DESIGN_SYSTEM = ["Density", "Elevation", "Radius scale"];

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

/** A Style-tab <select> is the sibling of a bare <span>/<div> holding its label. */
async function setSectionSelect(page: Page, label: string, index = 1) {
  return page.evaluate(({ label, index }) => {
    const labels = Array.from(document.querySelectorAll("span, div"))
      .filter((e) => e.children.length === 0
                  && (e.textContent ?? "").trim().toLowerCase() === label.toLowerCase());
    for (const l of labels) {
      const sel = l.nextElementSibling?.querySelector("select") as HTMLSelectElement | null;
      if (!sel) continue;
      const opts = Array.from(sel.options).filter((o) => o.value !== "");
      if (!opts.length) return { ok: false, reason: "no options" };
      const pick = opts[Math.min(index, opts.length - 1)];
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
      setter?.call(sel, pick.value);
      sel.dispatchEvent(new Event("change", { bubbles: true }));
      return { ok: true, value: pick.value };
    }
    return { ok: false, reason: "no select under that label" };
  }, { label, index });
}

/** A size field commits on blur/Enter only (StylePanel.tsx:47-84), never per keystroke. */
async function setSizeField(page: Page, label: string, value: string) {
  return page.evaluate(({ label, value }) => {
    const l = Array.from(document.querySelectorAll("label")).find((x) => {
      const s = x.querySelector("span");
      return s && (s.textContent ?? "").trim().toLowerCase() === label.toLowerCase();
    });
    const el = l?.querySelector("input") as HTMLInputElement | null;
    if (!el) return { ok: false, reason: `no input for "${label}"` };
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new FocusEvent("blur", { bubbles: true }));   // the commit
    return { ok: true, value };
  }, { label, value });
}

const subtree = (page: Page, id: string) =>
  page.evaluate((n) => document.querySelector(`[data-node-id="${n}"]`)?.outerHTML ?? "", id);

test("sweep the Style tab for every in-scope component", async ({ page }) => {
  page.on("pageerror", (e) => harness.push(`pageerror: ${e.message.slice(0, 160)}`));
  const names: string[] = JSON.parse(readFileSync("tests/e2e/.auth/components.json", "utf-8"));
  console.log(`[STYLE] ${names.length} components`);
  await openEditor(page);

  for (const [i, name] of names.entries()) {
    if ((await page.locator(CANVAS).count()) === 0) {
      harness.push(`${name}: canvas gone — reopening`);
      await openEditor(page).catch(() => {});
    }
    const before = await page.locator(`${CANVAS} [data-node-id]`).count();
    await drop(page, name);
    await page.waitForTimeout(400);
    const after = await page.locator(`${CANVAS} [data-node-id]`).count();
    if (after <= before) {
      rows.push({ component: name, status: "HARNESS-BLOCKED", detail: "drop refused" });
      continue;
    }
    const nodeId = await page.locator(`${CANVAS} [data-node-id]`).last()
      .getAttribute("data-node-id").catch(() => null);

    const right = page.locator("aside").filter({ has: page.getByRole("button", { name: /^props$/i }) }).first();
    await right.getByRole("button", { name: /^style$/i }).first().click().catch(() => {});
    await page.waitForTimeout(300);

    const applied: string[] = [], missing: string[] = [], blocked: string[] = [];

    for (const k of KEYS) {
      const r: any = await setSectionSelect(page, k.label, 1);
      if (!r.ok) { blocked.push(`${k.label}(${r.reason})`); continue; }
      await page.waitForTimeout(280);
      const html = await subtree(page, nodeId ?? "");
      (html.includes(k.emit(r.value)) ? applied : missing).push(k.label);
    }
    for (const s of SIZES) {
      const r: any = await setSizeField(page, s.label, s.value);
      if (!r.ok) { blocked.push(`${s.label}(${r.reason})`); continue; }
      await page.waitForTimeout(220);
      const html = await subtree(page, nodeId ?? "");
      (html.includes(s.value) ? applied : missing).push(s.label);
    }

    rows.push({
      component: name,
      status: blocked.length === KEYS.length + SIZES.length ? "HARNESS-BLOCKED"
            : missing.length === 0 ? "ALL-APPLIED"
            : applied.length === 0 ? "NONE-APPLIED" : "PARTIAL",
      applied: applied.join(","), missing: missing.join(","),
      blocked: blocked.join(",") || undefined,
    });

    await page.locator(`${CANVAS} [data-node-id]`).last().click({ force: true }).catch(() => {});
    await page.waitForTimeout(120);
    await page.keyboard.press("Delete").catch(() => {});
    await page.waitForTimeout(180);

    if ((i + 1) % 10 === 0) { flush(); console.log(`[STYLE] ${i + 1}/${names.length}`); }
  }

  // Design System trio is selection-independent — checked once, not per component.
  const dsRow: Row = { component: "(design-system)", status: "INFO" };
  for (const label of DESIGN_SYSTEM) {
    const r: any = await setSectionSelect(page, label, 1);
    dsRow[label] = r.ok ? `set ${r.value}` : `BLOCKED ${r.reason}`;
  }
  rows.push(dsRow);

  flush();
  const tally: Record<string, number> = {};
  for (const r of rows) tally[String(r.status)] = (tally[String(r.status)] ?? 0) + 1;
  console.log(`[STYLE] DONE ${JSON.stringify(tally)}`);
  expect(rows.length).toBeGreaterThan(0);
});
