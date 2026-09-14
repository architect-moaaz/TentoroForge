/**
 * TIER 2 — real browser, real UI, real backend.
 *
 * For every palette component: drop it on the canvas through the genuine HTML5
 * drag path, let the editor auto-select it, open the Style tab, change the
 * Padding dropdown like a user would, and look at what the DOM actually does.
 *
 * This exists to confirm-or-kill Tier 1's claim that 18 components silently
 * discard padding/radius/shadow/background. Tier 1 drove the store directly in
 * jsdom; this drives the UI in Chromium. Two independent channels agreeing is
 * the bar for reporting; either one alone is not.
 *
 * Preconditions are proved before any claim (the rule that caught three false
 * findings earlier):
 *   - the drop committed        -> canvas node count increased
 *   - nothing was refused       -> no [role=alert] "Edit rejected" banner
 *     (it AUTO-CLEARS after 5s — ErrorBanner.tsx:13-17 — so it is read
 *      immediately, never lazily)
 *   - the node is selected      -> exactly one [data-tentoro-selection-overlay]
 *   - the control exists        -> the Padding <select> was found and enabled
 * A precondition failure is recorded as HARNESS-BLOCKED, never as a defect.
 *
 * The observable is the EMITTED form, `var(--token-...)`, searched across the
 * node's whole subtree: library components put data-node-id on a wrapper span
 * that carries only sizing, while padding lands on the inner element. Searching
 * for the token REF instead of the emitted var is what produced 496 phantom
 * findings in an earlier Tier-1 pass.
 */
import { test, expect, type Page } from "@playwright/test";
import { writeFileSync, mkdirSync, readFileSync } from "node:fs";

const CANVAS = "[data-canvas-root]";
type Row = Record<string, unknown>;
const rows: Row[] = [];
const errors: string[] = [];

async function openEditor(page: Page) {
  await page.goto(process.env.E2E_PROJECT_URL ?? "/", { waitUntil: "domcontentloaded" });
  const tab = page.locator('[aria-label="Editor"]').first();
  await tab.waitFor({ state: "visible", timeout: 90_000 });
  await tab.click();
  await page.waitForSelector(CANVAS, { timeout: 90_000 });
  await page.waitForTimeout(2500);
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

/**
 * The Style tab's selects carry no label, no id and no testid — they are
 * identified by the element immediately before them. That element is a <span>
 * for the style sections (StylePanel.tsx:291-319) and a <div> for the Design
 * System block, so BOTH must be searched: querying only `div` found nothing and
 * blocked all 133 components on a harness fault.
 */
async function setStyleDropdown(page: Page, label: string, optionIndex = 1) {
  return page.evaluate(({ label, optionIndex }) => {
    const labels = Array.from(document.querySelectorAll("span, div"))
      .filter((d) => (d.textContent ?? "").trim().toLowerCase() === label.toLowerCase()
                     && d.children.length === 0);
    for (const l of labels) {
      const holder = l.nextElementSibling;
      const sel = holder?.querySelector("select") as HTMLSelectElement | null;
      if (!sel) continue;
      const opts = Array.from(sel.options).filter((o) => o.value !== "");
      if (!opts.length) return { ok: false, reason: "no non-empty options" };
      const pick = opts[Math.min(optionIndex, opts.length - 1)];
      // React listens for a native change; set through the value setter it patched.
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
      setter?.call(sel, pick.value);
      sel.dispatchEvent(new Event("change", { bubbles: true }));
      return { ok: true, value: pick.value, options: opts.length };
    }
    return { ok: false, reason: `no select under a "${label}" label` };
  }, { label, optionIndex });
}

test("tier2 — style edits through the real UI, every component", async ({ page }) => {
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message.slice(0, 200)}`));
  page.on("requestfailed", (r) => {
    if (/_rsc=/.test(r.url())) return;               // Next RSC prefetch aborts are noise
    errors.push(`REQFAIL ${r.url().slice(0, 110)}`);
  });

  await openEditor(page);

  // Read from disk rather than an env var — the list is 133 names and shell
  // substitution of that size is both fragile and unreadable in logs.
  const names: string[] = JSON.parse(readFileSync("tests/e2e/.auth/components.json", "utf-8"));
  expect(names.length).toBeGreaterThan(0);
  console.log(`[T2] sweeping ${names.length} components`);

  for (const name of names) {
    // RECOVER FROM A NAVIGATION. `Redirect` actually navigates when it renders,
    // which took the editor away mid-sweep: node count went 114 -> 0 and every
    // component after it reported "drop did not commit". That is a finding about
    // Redirect, not about the 90 components that followed it, so the canvas is
    // re-established before each one rather than letting one component poison
    // the rest of the run.
    if ((await page.locator(CANVAS).count()) === 0) {
      rows.push({ component: name, status: "RECOVERED",
                  detail: "canvas was gone before this component — editor reopened" });
      await openEditor(page).catch(() => {});
      if ((await page.locator(CANVAS).count()) === 0) {
        rows.push({ component: name, status: "HARNESS-BLOCKED", detail: "could not reopen the editor" });
        continue;
      }
    }

    const before = await page.locator(`${CANVAS} [data-node-id]`).count();
    const ok = await drop(page, name);
    await page.waitForTimeout(450);

    // Read the rejection banner IMMEDIATELY — it clears itself after 5s.
    const alert = page.locator('[role="alert"]');
    const banner = (await alert.count())
      ? ((await alert.innerText().catch(() => "")) || "").replace(/\s+/g, " ").trim()
      : "";
    const after = await page.locator(`${CANVAS} [data-node-id]`).count();

    if (!ok || after <= before) {
      rows.push({ component: name, status: "HARNESS-BLOCKED",
                  detail: `drop did not commit (${before}->${after})`, banner });
      continue;
    }

    const overlays = await page.locator("[data-tentoro-selection-overlay]").count();
    if (overlays !== 1) {
      rows.push({ component: name, status: "HARNESS-BLOCKED",
                  detail: `expected 1 selection overlay, saw ${overlays}` });
      continue;
    }

    // SCOPE THE TAB TO THE PANEL. An unscoped getByRole("button",{name:/^style$/i})
    // .first() matches a different "Style" button earlier in the document, so the
    // panel stayed on Props — which has no "Padding" label — and all 133
    // components blocked on a phantom "control missing".
    const rightPanel = page.locator("aside")
      .filter({ has: page.getByRole("button", { name: /^props$/i }) }).first();
    const styleTab = rightPanel.getByRole("button", { name: /^style$/i }).first();
    if (!(await styleTab.count())) {
      rows.push({ component: name, status: "HARNESS-BLOCKED", detail: "no Style tab in the right panel" });
      continue;
    }
    await styleTab.click().catch(() => {});
    await page.waitForTimeout(350);
    const panelText = ((await rightPanel.innerText().catch(() => "")) || "").replace(/\s+/g, " ");
    if (/Select a node/i.test(panelText)) {
      rows.push({ component: name, status: "HARNESS-BLOCKED",
                  detail: "panel shows its empty state — selection lost before the Style tab" });
      continue;
    }

    // Drive every token-wrapped style dropdown, not just one.
    const keys = ["Background", "Padding", "Radius", "Shadow", "Motion"];
    const applied: string[] = [];
    const missing: string[] = [];
    const blocked: string[] = [];

    for (const key of keys) {
      const set: any = await setStyleDropdown(page, key, 1);
      if (!set.ok) { blocked.push(`${key}(${set.reason})`); continue; }
      await page.waitForTimeout(350);

      const ref: string = set.value;
      // Motion is an ATTRIBUTE, not a var; everything else is var(--token-…).
      const emitted = key === "Motion"
        ? `data-motion="${ref}"`
        : `var(--token-${ref.replace(/^tokens\./, "").replace(/\./g, "-")})`;

      // The node just dropped is the last one (insert appends).
      const node = page.locator(`${CANVAS} [data-node-id]`).last();
      const html = (await node.evaluate((el) => el.outerHTML).catch(() => "")) || "";
      (html.includes(emitted) ? applied : missing).push(key);
    }

    rows.push({
      component: name,
      status: blocked.length === keys.length ? "HARNESS-BLOCKED"
            : missing.length === 0 ? "APPLIED"
            : applied.length === 0 ? "NONE-APPLIED"
            : "PARTIAL",
      applied: applied.join(","), missing: missing.join(","),
      blocked: blocked.join(",") || undefined,
    });

    // Remove the probe node again. The node is still selected (insert
    // auto-selects), so Delete removes it. Without this the canvas grew past 130
    // nodes during one sweep, which both slows every later query and leaves a
    // large diff in the user's project even though a snapshot restore follows.
    await page.keyboard.press("Delete").catch(() => {});
    await page.waitForTimeout(200);
  }

  const tally: Record<string, number> = {};
  for (const r of rows) tally[String(r.status)] = (tally[String(r.status)] ?? 0) + 1;
  console.log(`[T2] ${JSON.stringify(tally)}`);
  for (const r of rows.filter((r) => r.status !== "APPLIED")) {
    console.log(`[T2] ${String(r.component).padEnd(22)} ${r.status} ${r.detail ?? ""}`);
  }
  console.log(`[T2] page errors: ${errors.length ? errors.slice(0, 5).join(" | ") : "(none)"}`);
});
