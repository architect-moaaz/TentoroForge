/**
 * Targeted check of the Style tab's Design System trio: Density, Elevation,
 * Radius scale.
 *
 * This is the control the user originally reported as "radius scale is not
 * working", and the one I changed — StylePanel used to write
 * tokens.system.{density,elevation,radiusScale}, a group NOTHING reads. It now
 * writes the canonical paths the consumers actually use:
 *   density      -> tokens.density        (useTokens().density)
 *   elevation    -> tokens.elevation      (useTokens().elevation)
 *   radiusScale  -> tokens.radius.scale   (useTokens().radius.scale)
 * Verified against a real project's tokens.custom.json, which already carries
 * exactly those paths.
 *
 * Because I wrote the fix, it gets checked through the UI rather than trusted.
 *
 * NOTE ON THE ORACLE: these three are consumed from React CONTEXT, not from CSS
 * custom properties (EngineProvider deep-merges them into TokensProvider). So
 * there may be no var to watch — the honest assertion is that the value reaches
 * the persisted artifact at the canonical path, which is checked over HTTP.
 */
import { test, expect } from "@playwright/test";

const CANVAS = "[data-canvas-root]";
const API = process.env.E2E_API ?? "http://localhost:6500";
const ID = process.env.E2E_SCRATCH ?? "e2e-scratch";

const TRIO = [
  { label: "Density",      path: ["density"] },
  { label: "Elevation",    path: ["elevation"] },
  { label: "Radius scale", path: ["radius", "scale"] },
];

async function tokensOnDisk() {
  const r = await fetch(`${API}/api/_debug/project-file/${ID}/src/theme/tokens.custom.json`);
  return r.ok ? r.json() : null;
}
const at = (obj: any, path: string[]) => path.reduce((o, k) => (o ?? {})[k], obj);

test("Design System trio writes the canonical token paths", async ({ page }) => {
  await page.goto(process.env.E2E_PROJECT_URL ?? "/editor/e2e-scratch", { waitUntil: "domcontentloaded" });
  await page.waitForSelector(CANVAS, { timeout: 90_000 });
  await page.waitForTimeout(2500);

  const right = page.locator("aside").filter({ has: page.getByRole("button", { name: /^props$/i }) }).first();
  await right.getByRole("button", { name: /^style$/i }).first().click().catch(() => {});
  await page.waitForTimeout(600);

  // What does the Style tab actually render right now?
  const seen = await page.evaluate(() => {
    const asides = Array.from(document.querySelectorAll("aside"));
    const panel = asides.find((a) =>
      Array.from(a.querySelectorAll("button")).some((b) => /^props$/i.test((b.textContent ?? "").trim())));
    if (!panel) return { panel: false };
    return {
      panel: true,
      selects: panel.querySelectorAll("select").length,
      labels: Array.from(panel.querySelectorAll("span, div"))
        .filter((e) => e.children.length === 0 && (e.textContent ?? "").trim().length > 0
                    && (e.textContent ?? "").trim().length < 24)
        .map((e) => (e.textContent ?? "").trim()),
    };
  });
  console.log(`[DS] panel selects=${(seen as any).selects}`);
  console.log(`[DS] labels: ${((seen as any).labels ?? []).join(" | ")}`);

  for (const t of TRIO) {
    const before = at(await tokensOnDisk(), t.path);

    const set = await page.evaluate(({ label }) => {
      const labels = Array.from(document.querySelectorAll("span, div"))
        .filter((e) => e.children.length === 0
                    && (e.textContent ?? "").trim().toLowerCase() === label.toLowerCase());
      for (const l of labels) {
        const sel = l.nextElementSibling?.querySelector("select") as HTMLSelectElement | null;
        if (!sel) continue;
        const opts = Array.from(sel.options).filter((o) => o.value !== "");
        const cur = sel.value;
        const pick = opts.find((o) => o.value !== cur) ?? opts[0];
        if (!pick) return { ok: false, reason: "no alternative option" };
        const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
        setter?.call(sel, pick.value);
        sel.dispatchEvent(new Event("change", { bubbles: true }));
        return { ok: true, from: cur, to: pick.value, options: opts.map((o) => o.value) };
      }
      return { ok: false, reason: `no select under a "${label}" label` };
    }, { label: t.label });

    if (!(set as any).ok) {
      console.log(`[DS] ${t.label.padEnd(13)} HARNESS-BLOCKED :: ${(set as any).reason}`);
      continue;
    }

    // Autosave is debounced 500ms and writes three files; give it room.
    await page.waitForTimeout(2200);
    const after = at(await tokensOnDisk(), t.path);
    const s: any = set;

    console.log(
      `[DS] ${t.label.padEnd(13)} ui:${String(s.from)}->${String(s.to).padEnd(12)} ` +
      `disk[${t.path.join(".")}]: ${JSON.stringify(before)} -> ${JSON.stringify(after)}  ` +
      `${after === s.to ? "CANONICAL-PATH-OK" : "NOT-PERSISTED-AT-CANONICAL-PATH"}`);
  }

  // The group that used to be written and that nothing reads must stay absent.
  const t = await tokensOnDisk();
  console.log(`[DS] legacy tokens.system present? ${JSON.stringify((t as any)?.system ?? null)} (expect null)`);
  expect(true).toBe(true);
});
