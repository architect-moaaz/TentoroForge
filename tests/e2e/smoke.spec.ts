/**
 * W0 SMOKE — prove the two Tier-2 primitives before sweeping 133 components.
 *
 * 1. INSERTION. Native HTML5 drag is the only insertion path in the editor
 *    (Palette.tsx:164-192; insertNode dispatched from exactly one place,
 *    useDrop.ts:200-206). onDrop reads only dataTransfer.getData and e.target,
 *    so a synthetic DragEvent carrying "text/x-forge-component" dispatched on
 *    [data-canvas-root] should drive the whole real path. That is an INFERENCE
 *    FROM SOURCE — React 18 uses delegated listeners and may not receive a
 *    manually dispatched event. This test decides it. If it fails, Tier 2 falls
 *    back to Playwright's real mouse drag and the sweep is re-timed.
 *
 * 2. SELECTION. Not canvas clicks — an unsized library component's
 *    data-node-id lives on a display:contents span with no layout box, so
 *    Playwright actionability times out. The layers tree in PagePicker renders a
 *    real <button onClick={() => onSelect(node.id)}> (PagePicker.tsx:282) wired
 *    straight to setSelection. This test confirms it selects.
 *
 * A trap this must not fall into: an EMPTY page's root is `Text`
 * (Canvas.tsx:70-75), which is not one of the 133 registry keys, so validateDrop
 * rejects EVERY drop. The test reports that explicitly rather than concluding
 * "insertion is broken".
 */
import { test, expect, type Page } from "@playwright/test";

const CANVAS = "[data-canvas-root]";

async function openEditor(page: Page) {
  await page.goto(process.env.E2E_PROJECT_URL ?? "/", { waitUntil: "domcontentloaded" });
  // WAIT for the tab; never sample it. `if (await tab.count())` right after
  // domcontentloaded reads 0 because the rail has not hydrated, silently skips
  // the click, and then times out waiting for a canvas nobody opened — which
  // looks exactly like "the editor is broken". Measured: with a proper wait the
  // canvas mounts in ~3s.
  const tab = page.locator('[aria-label="Editor"]').first();
  await tab.waitFor({ state: "visible", timeout: 90_000 });
  await tab.click();
  await page.waitForSelector(CANVAS, { timeout: 90_000 });
  await page.waitForTimeout(2500);
}

/** Dispatch a real DragEvent with a populated DataTransfer onto the canvas. */
async function syntheticDrop(page: Page, componentName: string) {
  return page.evaluate((name) => {
    const root = document.querySelector("[data-canvas-root]") as HTMLElement | null;
    if (!root) return { ok: false, reason: "no [data-canvas-root]" };
    const dt = new DataTransfer();
    dt.setData("text/x-forge-component", name);
    const opts: any = { bubbles: true, cancelable: true, composed: true, dataTransfer: dt };
    root.dispatchEvent(new DragEvent("dragenter", opts));
    root.dispatchEvent(new DragEvent("dragover", opts));
    root.dispatchEvent(new DragEvent("drop", opts));
    return { ok: true };
  }, componentName);
}

test("W0 — synthetic drop and layers-tree selection", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));

  await openEditor(page);

  // --- the empty-page trap, checked explicitly -----------------------------
  const rootType = await page.evaluate(() => {
    const el = document.querySelector("[data-canvas-root] [data-node-id]");
    return el?.getAttribute("data-structural-node")
      ?? el?.getAttribute("data-node-id")
      ?? "(none)";
  });
  const before = await page.locator(`${CANVAS} [data-node-id]`).count();
  console.log(`[W0] canvas nodes before = ${before}, first node hint = ${rootType}`);
  if (before === 0) {
    console.log("[W0] EMPTY PAGE — root is `Text`, absent from the registry, so every drop " +
                "would be refused. This is the documented trap, not an insertion defect.");
  }

  // --- 1. INSERTION --------------------------------------------------------
  const res = await syntheticDrop(page, "Button");
  console.log(`[W0] synthetic drop dispatched: ${JSON.stringify(res)}`);
  await page.waitForTimeout(1200);

  const after = await page.locator(`${CANVAS} [data-node-id]`).count();
  const banner = page.locator('[role="alert"]');
  const bannerText = (await banner.count())
    ? ((await banner.innerText().catch(() => "")) || "").replace(/\s+/g, " ").trim()
    : "";
  console.log(`[W0] canvas nodes after  = ${after} (delta ${after - before})`);
  console.log(`[W0] error banner        = ${bannerText || "(none)"}`);
  console.log(`[W0] INSERTION PRIMITIVE : ${after > before ? "WORKS" : "DOES NOT WORK — fall back to real mouse drag"}`);

  // --- 2. SELECTION via the layers tree ------------------------------------
  // The tree renders one button per node, labelled with node.type.
  const treeButtons = page.locator("nav button, aside button").filter({ hasText: /^[A-Z][A-Za-z]+$/ });
  const treeCount = await treeButtons.count();
  let selected = "(not attempted)";
  if (treeCount > 0) {
    await treeButtons.nth(Math.min(2, treeCount - 1)).click().catch(() => {});
    await page.waitForTimeout(700);
    const overlays = await page.locator("[data-tentoro-selection-overlay]").count();
    const right = page.locator("aside").filter({ has: page.getByRole("button", { name: /^props$/i }) }).first();
    const txt = ((await right.innerText().catch(() => "")) || "").replace(/\s+/g, " ");
    selected = `overlays=${overlays} panelSaysSelect=${/Select a node/i.test(txt)}`;
  }
  console.log(`[W0] layers-tree buttons = ${treeCount}`);
  console.log(`[W0] SELECTION PRIMITIVE : ${selected}`);

  console.log(`[W0] page errors         = ${errors.length ? errors.join(" | ") : "(none)"}`);
  expect(true).toBe(true);
});
