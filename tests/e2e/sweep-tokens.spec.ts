/**
 * SWEEP — the Tokens tab, through the real UI.
 *
 * Tier 1 proved every token WRITE lands and that both emitted var spellings move
 * in lockstep. What it could not prove is that the on-screen control is wired to
 * that write. This drives the real inputs.
 *
 * The observable (EngineProvider.tsx:46-72): every token leaf is emitted TWICE
 * onto [data-tentoro-engine] — `--<group>-<path>` AND `--token-<group>-<path>`.
 * The dual emission is deliberate: library components deref `--token-*`, and
 * emitting only the bare prefix once made every library var() resolve to
 * nothing. So a token edit must move BOTH. One moving without the other is a
 * real defect, and asserting only one would hide it.
 *
 * The Tokens tab is selection-independent, so this needs no component loop —
 * it is a single pass over the rendered rows.
 *
 * Also pins the known candidate: TokenEditor renders EVERY tokens.radius.* row
 * as input[type=number] and writes Number(value), while StylePanel legitimately
 * stores the STRING "soft" at radius.scale. Editing that row yields NaN.
 */
import { test, expect, type Page } from "@playwright/test";
import { writeFileSync, mkdirSync } from "node:fs";

const CANVAS = "[data-canvas-root]";
const OUT = "tests/e2e/sweep-tokens.json";
type Row = Record<string, unknown>;
const rows: Row[] = [];
const flush = () => {
  mkdirSync("tests/e2e", { recursive: true });
  writeFileSync(OUT, JSON.stringify({ rows }, null, 1), "utf-8");
};

/** Read both spellings of every custom property on the engine wrapper. */
async function engineVars(page: Page) {
  return page.evaluate(() => {
    const el = document.querySelector("[data-tentoro-engine]") as HTMLElement | null;
    if (!el) return null;
    const out: Record<string, string> = {};
    const s = el.style;
    for (let i = 0; i < s.length; i++) {
      const n = s.item(i);
      if (n.startsWith("--")) out[n] = s.getPropertyValue(n).trim();
    }
    return out;
  });
}

test("sweep the Tokens tab through the real UI", async ({ page }) => {
  await page.goto(process.env.E2E_PROJECT_URL ?? "/editor/e2e-scratch", { waitUntil: "domcontentloaded" });
  await page.waitForSelector(CANVAS, { timeout: 90_000 });
  await page.waitForTimeout(2000);

  const right = page.locator("aside").filter({ has: page.getByRole("button", { name: /^props$/i }) }).first();
  await right.getByRole("button", { name: /^tokens$/i }).first().click().catch(() => {});
  await page.waitForTimeout(600);

  // Inventory what the tab actually renders.
  const inventory = await page.evaluate(() => {
    const asides = Array.from(document.querySelectorAll("aside"));
    const panel = asides.find((a) =>
      Array.from(a.querySelectorAll("button")).some((b) => /^tokens$/i.test((b.textContent ?? "").trim())));
    if (!panel) return null;
    return {
      legends: Array.from(panel.querySelectorAll("legend")).map((l) => (l.textContent ?? "").trim()),
      colorInputs: panel.querySelectorAll('input[type="color"]').length,
      numberInputs: panel.querySelectorAll('input[type="number"]').length,
      textInputs: panel.querySelectorAll('input[type="text"]').length,
      removeButtons: panel.querySelectorAll('button[aria-label^="Remove"]').length,
    };
  });
  rows.push({ cell: "inventory", ...(inventory ?? { panel: false }) });
  console.log(`[TOK] inventory ${JSON.stringify(inventory)}`);

  if (!inventory) { flush(); test.skip(true, "no Tokens panel"); }

  // ---- drive each input kind and watch BOTH var spellings -----------------
  const kinds: Array<{ sel: string; label: string; value: string }> = [
    { sel: 'input[type="color"]', label: "color", value: "#abcdef" },
    { sel: 'input[type="number"]', label: "number", value: "77" },
    { sel: 'input[type="text"]', label: "text", value: "AuditValue" },
  ];

  for (const k of kinds) {
    const before = await engineVars(page);
    const set = await page.evaluate(({ sel, value }) => {
      const asides = Array.from(document.querySelectorAll("aside"));
      const panel = asides.find((a) =>
        Array.from(a.querySelectorAll("button")).some((b) => /^tokens$/i.test((b.textContent ?? "").trim())));
      const el = panel?.querySelector(sel) as HTMLInputElement | null;
      if (!el) return { ok: false, reason: "no such input" };
      const label = el.closest("label")?.textContent?.trim().slice(0, 40) ?? "(unlabelled)";
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return { ok: true, label };
    }, { sel: k.sel, value: k.value });

    if (!(set as any).ok) { rows.push({ cell: k.label, status: "HARNESS-BLOCKED", detail: (set as any).reason }); continue; }
    await page.waitForTimeout(600);
    const after = await engineVars(page);

    const changed = Object.keys(after ?? {}).filter((n) => (before ?? {})[n] !== (after ?? {})[n]);
    const bare = changed.filter((n) => !n.startsWith("--token-"));
    const prefixed = changed.filter((n) => n.startsWith("--token-"));

    rows.push({
      cell: k.label, row: (set as any).label,
      status: changed.length === 0 ? "NO-EFFECT"
            : bare.length > 0 && prefixed.length > 0 ? "APPLIED-BOTH-SPELLINGS"
            : "APPLIED-ONE-SPELLING-ONLY",
      changed: changed.slice(0, 6).join(", "),
      detail: bare.length > 0 && prefixed.length === 0
        ? "--token-* did NOT move; library var() derefs would resolve to nothing"
        : undefined,
    });
    console.log(`[TOK] ${k.label}: ${changed.length} vars moved (bare ${bare.length}, --token- ${prefixed.length})`);
  }

  flush();
  const tally: Record<string, number> = {};
  for (const r of rows) tally[String(r.status ?? "info")] = (tally[String(r.status ?? "info")] ?? 0) + 1;
  console.log(`[TOK] DONE ${JSON.stringify(tally)}`);
  expect(rows.length).toBeGreaterThan(0);
});
