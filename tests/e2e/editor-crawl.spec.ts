/**
 * EDITOR CRAWL — drives the real editor looking for defects that are tedious
 * to find by hand.
 *
 * Written to REPORT, not to stop at the first problem: a missing selector
 * records a finding and the crawl continues, because a spec that dies on step
 * one tells you nothing about steps two through two hundred.
 *
 * Continuous watches, on every interaction:
 *   • uncaught page errors and console.error
 *   • HTTP 4xx/5xx and outright request failures
 *   • panel OCCLUSION — is the topmost element at a panel's own coordinates
 *     actually inside that panel? (this is what "the palette looks
 *     transparent" really was: a fixed z-50 overlay painting on top)
 *
 * Findings → tests/e2e/findings.json.
 *
 * The visual editor is a TAB inside the project page, not its own route — the
 * URL never changes — so the crawl clicks `aria-label="Editor"` to get there
 * (page.tsx:262 defines the tab, :474 exposes the aria-label).
 */
import { test, expect, type Page, type Locator } from "@playwright/test";
import { writeFileSync, mkdirSync } from "node:fs";

type Finding = { kind: string; where: string; detail: string };
const findings: Finding[] = [];
const add = (kind: string, where: string, detail: string) =>
  findings.push({ kind, where, detail: String(detail).slice(0, 400) });

function watch(page: Page, label: () => string) {
  page.on("pageerror", (e) => add("page-error", label(), e.message));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    if (/Download the React DevTools/i.test(t)) return;
    add("console-error", label(), t);
  });
  page.on("requestfailed", (r) =>
    add("request-failed", label(), `${r.method()} ${r.url()} — ${r.failure()?.errorText}`));
  page.on("response", (r) => {
    if (r.status() >= 400) add(`http-${r.status()}`, label(), `${r.request().method()} ${r.url()}`);
  });
}

/** Is the topmost element at this element's own coordinates inside it? */
async function occlusionOf(locator: Locator) {
  const handle = await locator.elementHandle().catch(() => null);
  if (!handle) return { found: false as const };
  return handle.evaluate((root) => {
    const r = root.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return { found: true, empty: true } as const;
    const pts: Array<[number, number]> = [
      [r.left + r.width / 2, r.top + 24],
      [r.left + r.width / 2, r.top + r.height / 2],
      [r.left + r.width / 2, r.bottom - 24],
    ];
    for (const [x, y] of pts) {
      const top = document.elementFromPoint(x, y);
      if (!top) continue;
      if (top !== root && !root.contains(top)) {
        const d = top as HTMLElement;
        const cs = getComputedStyle(d);
        return {
          found: true, empty: false, occluded: true,
          at: `${Math.round(x)},${Math.round(y)}`,
          by: `${d.tagName.toLowerCase()}.${String(d.className).slice(0, 70)}`,
          pos: cs.position, z: cs.zIndex,
        } as const;
      }
    }
    return { found: true, empty: false, occluded: false } as const;
  });
}

test.afterAll(() => {
  mkdirSync("tests/e2e", { recursive: true });
  writeFileSync("tests/e2e/findings.json", JSON.stringify(findings, null, 1), "utf-8");
  const byKind = findings.reduce<Record<string, number>>((m, f) => {
    m[f.kind] = (m[f.kind] ?? 0) + 1; return m;
  }, {});
  console.log("\n=== CRAWL FINDINGS ===");
  console.log(JSON.stringify(byKind, null, 1));
  for (const f of findings.slice(0, 60)) console.log(` [${f.kind}] ${f.where} :: ${f.detail}`);
  console.log(`\n(${findings.length} total → tests/e2e/findings.json)`);
});

test("crawl the editor", async ({ page }) => {
  let where = "boot";
  watch(page, () => where);

  await page.goto(process.env.E2E_PROJECT_URL ?? "/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(4000);

  if (/\/login/.test(page.url())) {
    add("auth", "boot", `Redirected to ${page.url()} — session missing/expired; re-run save-auth.mjs`);
    test.skip(true, "not authenticated");
  }

  // ---- open the Editor tab -------------------------------------------------
  where = "open-editor";
  // WAIT for the tab rail, don't sample it. The project page hydrates and then
  // fetches before the rail exists; a fixed sleep found it on one run and
  // missed it on the next, which is a flaky harness reporting a phantom defect.
  const editorTab = page.locator('[aria-label="Editor"]').first();
  try {
    await editorTab.waitFor({ state: "visible", timeout: 60_000 });
    await editorTab.click();
  } catch (e: any) {
    add("selector-miss", where, `[aria-label="Editor"] never became clickable: ${e.message}`);
  }
  await page.waitForSelector("[data-node-id]", { timeout: 45_000 })
    .catch(() => add("no-canvas", where, "no [data-node-id] appeared after opening Editor"));
  await page.waitForTimeout(2500);

  const nodeCount = await page.locator("[data-node-id]").count();
  add("info", "canvas", `${nodeCount} nodes on canvas`);

  // ---- 1. panel occlusion --------------------------------------------------
  where = "occlusion";
  const panels: Array<[string, Locator]> = [
    ["palette", page.locator("aside").filter({ hasText: "COMPONENTS" }).first()],
    ["right-panel", page.locator("aside")
      .filter({ has: page.getByRole("button", { name: /^props$/i }) }).first()],
  ];
  for (const [name, loc] of panels) {
    if (!(await loc.count())) { add("selector-miss", where, `${name}: no matching <aside>`); continue; }
    const r: any = await occlusionOf(loc);
    if (r?.occluded) add("panel-occluded", name, `covered at ${r.at} by ${r.by} (position:${r.pos} z:${r.z})`);
    else if (r?.empty) add("panel-empty", name, "zero-size box");
  }

  // ---- 2. inspector tabs ---------------------------------------------------
  const firstNode = page.locator("[data-node-id]").first();
  if (nodeCount > 0) {
    where = "select-node";
    await firstNode.click({ force: true }).catch((e) => add("click-failed", where, e.message));
    await page.waitForTimeout(1200);
    // Did the click actually SELECT anything? If the panel is still showing its
    // empty state then every downstream "control missing" finding is an
    // artefact of this click, not a defect in the panel.
    const probe = page.locator("aside")
      .filter({ has: page.getByRole("button", { name: /^props$/i }) }).first();
    const probeTxt = ((await probe.innerText().catch(() => "")) || "").replace(/\s+/g, " ").trim();
    add("info", "right-panel-after-select", probeTxt.slice(0, 220) || "(no right panel found)");
    const selId = await firstNode.getAttribute("data-node-id").catch(() => null);
    add("info", "clicked-node", String(selId));

    // NOTE: the tabs LOOK uppercase but the DOM text is "Props"/"Style"/… —
    // RightPanel.tsx:18 applies a CSS `uppercase` class. Playwright matches DOM
    // text, so an exact "PROPS" never matches. Match case-insensitively.
    const rightPanel = page.locator("aside")
      .filter({ has: page.getByRole("button", { name: /^props$/i }) }).first();
    for (const tab of ["Props", "Style", "Bindings", "Tokens"]) {
      where = `tab:${tab}`;
      const btn = page.getByRole("button", { name: new RegExp(`^${tab}$`, "i") }).first();
      if (!(await btn.count())) { add("selector-miss", where, `no ${tab} tab`); continue; }
      await btn.click().catch((e) => add("click-failed", where, e.message));
      await page.waitForTimeout(600);
      const txt = (await rightPanel.innerText().catch(() => "")) || "";
      if (txt.trim().length < 3) add("empty-tab", where, `${tab} rendered no content`);
      const occ: any = await occlusionOf(rightPanel);
      if (occ?.occluded) add("panel-occluded", where, `covered at ${occ.at} by ${occ.by} (z:${occ.z})`);
    }

    // ---- 3. breakpoint switcher -------------------------------------------
    where = "breakpoints";
    await page.getByRole("button", { name: /^props$/i }).first().click().catch(() => {});
    await page.waitForTimeout(500);
    for (const bp of ["All", "sm", "md", "lg", "xl"]) {
      const b = page.getByRole("button", { name: new RegExp(`^${bp}$`, "i") }).first();
      if (!(await b.count())) { add("selector-miss", where, `no '${bp}' button`); continue; }
      await b.click().catch((e) => add("click-failed", `${where}:${bp}`, e.message));
      await page.waitForTimeout(400);
      const inputs = rightPanel.locator("input, select, textarea");
      const n = await inputs.count();
      let filled = 0;
      for (let i = 0; i < Math.min(n, 30); i++) {
        const v = await inputs.nth(i).inputValue().catch(() => "");
        if (v && v.trim() !== "") filled++;
      }
      add("bp-observation", `${where}:${bp}`, `${n} controls, ${filled} non-empty`);
    }
  }

  expect(true).toBe(true);
});
