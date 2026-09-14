/**
 * FULL EDITOR SWEEP — drives every node on the canvas through every inspector
 * tab and every design-system control, in a real browser, recording what
 * actually happens in the DOM.
 *
 * Selection note: the canvas click handler (hooks/useSelection.ts:16) is
 * mounted on the CANVAS WRAPPER and walks up from e.target to the nearest
 * [data-node-id]. A [data-node-id] outside that wrapper therefore never
 * selects — which is why an earlier version of this file clicked the first
 * match in document order and silently selected nothing, then reported the
 * resulting empty panel as "controls missing". Nodes are scoped to the canvas
 * host here, and selection is VERIFIED before any panel claim is made.
 *
 * Everything is recorded to tests/e2e/sweep.json.
 */
import { test, expect, type Page, type Locator } from "@playwright/test";
import { writeFileSync, mkdirSync } from "node:fs";

type Row = Record<string, unknown>;
const rows: Row[] = [];
const errors: Row[] = [];
const push = (r: Row) => rows.push(r);

function watch(page: Page, label: () => string) {
  page.on("pageerror", (e) => errors.push({ kind: "page-error", where: label(), detail: e.message }));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    if (/React DevTools/i.test(t)) return;
    errors.push({ kind: "console-error", where: label(), detail: t.slice(0, 300) });
  });
  page.on("requestfailed", (r) =>
    errors.push({ kind: "request-failed", where: label(), detail: `${r.method()} ${r.url()}` }));
  page.on("response", (r) => {
    if (r.status() >= 400)
      errors.push({ kind: `http-${r.status()}`, where: label(), detail: `${r.request().method()} ${r.url()}` });
  });
}

async function occlusionOf(locator: Locator) {
  const h = await locator.elementHandle().catch(() => null);
  if (!h) return null;
  return h.evaluate((root) => {
    const r = root.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return { empty: true } as any;
    for (const [x, y] of [
      [r.left + r.width / 2, r.top + 24],
      [r.left + r.width / 2, r.top + r.height / 2],
    ] as Array<[number, number]>) {
      const top = document.elementFromPoint(x, y);
      if (top && top !== root && !root.contains(top)) {
        const d = top as HTMLElement;
        const cs = getComputedStyle(d);
        return { occluded: true, at: `${Math.round(x)},${Math.round(y)}`,
                 by: `${d.tagName.toLowerCase()}.${String(d.className).slice(0, 60)}`,
                 pos: cs.position, z: cs.zIndex } as any;
      }
    }
    return { occluded: false } as any;
  });
}

test.afterAll(() => {
  mkdirSync("tests/e2e", { recursive: true });
  writeFileSync("tests/e2e/sweep.json",
    JSON.stringify({ rows, errors }, null, 1), "utf-8");
  console.log("\n================ EDITOR SWEEP ================");
  for (const r of rows) console.log(" " + JSON.stringify(r));
  const byKind = errors.reduce<Record<string, number>>((m, e) => {
    m[String(e.kind)] = (m[String(e.kind)] ?? 0) + 1; return m;
  }, {});
  console.log("\n---- errors seen: " + JSON.stringify(byKind));
  const seen = new Set<string>();
  for (const e of errors) {
    const k = `${e.kind}:${String(e.detail).slice(0, 90)}`;
    if (seen.has(k)) continue;
    seen.add(k);
    console.log(`  [${e.kind}] ${e.detail}`);
  }
  console.log(`\n(${rows.length} rows, ${errors.length} errors -> tests/e2e/sweep.json)`);
});

test("sweep every canvas node through every inspector tab", async ({ page }) => {
  let where = "boot";
  watch(page, () => where);

  await page.goto(process.env.E2E_PROJECT_URL ?? "/", { waitUntil: "domcontentloaded" });

  where = "open-editor";
  const tab = page.locator('[aria-label="Editor"]').first();
  await tab.waitFor({ state: "visible", timeout: 60_000 });
  await tab.click();
  await page.waitForSelector("main [data-node-id]", { timeout: 60_000 });
  await page.waitForTimeout(2500);

  // Canvas-scoped nodes only — see the header note.
  const canvasNodes = page.locator("main [data-node-id]");
  const total = await canvasNodes.count();
  push({ step: "canvas", nodes: total });

  const right = page.locator("aside")
    .filter({ has: page.getByRole("button", { name: /^props$/i }) }).first();

  // Walk a spread of nodes rather than all of them — deep nodes are the ones
  // with interesting props; the root container has none.
  const picks: number[] = Array.from({ length: total }, (_, i) => i);

  for (const idx of picks) {
    const node = canvasNodes.nth(idx);
    const nodeId = await node.getAttribute("data-node-id").catch(() => null);
    where = `node:${nodeId}`;

    // Click the node's own box; no force, so we hit a real target inside the
    // canvas wrapper and the click handler actually runs.
    await node.scrollIntoViewIfNeeded().catch(() => {});
    await node.click({ timeout: 8000 }).catch(async () => {
      await node.click({ force: true, timeout: 8000 }).catch(() => {});
    });
    await page.waitForTimeout(350);

    // VERIFY selection before believing anything the panel says.
    const panelTxt = ((await right.innerText().catch(() => "")) || "").replace(/\s+/g, " ").trim();
    const selected = !/Select a node/i.test(panelTxt);
    if (!selected) {
      push({ node: nodeId, idx, selected: false, note: "click did not select — skipping panel claims" });
      continue;
    }

    const row: Row = { node: nodeId, idx, selected: true };

    for (const t of ["Props", "Style", "Bindings", "Tokens"]) {
      where = `node:${nodeId}/${t}`;
      const btn = page.getByRole("button", { name: new RegExp(`^${t}$`, "i") }).first();
      if (!(await btn.count())) { row[t] = "tab-missing"; continue; }
      await btn.click().catch(() => {});
      await page.waitForTimeout(250);
      const txt = ((await right.innerText().catch(() => "")) || "").replace(/\s+/g, " ").trim();
      const controls = await right.locator("input, select, textarea, button").count();
      const occ: any = await occlusionOf(right);
      row[t] = `${controls} ctrls${occ?.occluded ? ` OCCLUDED by ${occ.by}` : ""}`;
      if (txt.length < 3) row[t] = "EMPTY";
    }

    // Breakpoint switcher lives in the Props tab header.
    where = `node:${nodeId}/bp`;
    await page.getByRole("button", { name: /^props$/i }).first().click().catch(() => {});
    await page.waitForTimeout(200);
    const bpFound: string[] = [];
    for (const bp of ["All", "sm", "md", "lg", "xl"]) {
      const b = right.getByRole("button", { name: new RegExp(`^${bp}$`, "i") }).first();
      if (await b.count()) bpFound.push(bp);
    }
    row.breakpoints = bpFound.length ? bpFound.join(",") : "NONE";
    push(row);
  }

  // ---- design-system controls (Style tab) ---------------------------------
  where = "design-system";
  await page.getByRole("button", { name: /^style$/i }).first().click().catch(() => {});
  await page.waitForTimeout(600);
  const styleTxt = ((await right.innerText().catch(() => "")) || "").replace(/\s+/g, " ");
  push({
    step: "design-system-visible",
    density: /DENSITY/i.test(styleTxt),
    elevation: /ELEVATION/i.test(styleTxt),
    radiusScale: /RADIUS SCALE/i.test(styleTxt),
  });

  expect(rows.length).toBeGreaterThan(0);
});
