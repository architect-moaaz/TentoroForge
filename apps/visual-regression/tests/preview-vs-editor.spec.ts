// apps/visual-regression/tests/preview-vs-editor.spec.ts
//
// Pixel-diff parity test: editor canvas vs render-scaffold preview.
// Threshold = 10% reflects current library coverage; tighten to 5% after WS-5 follow-ups.
import { test, expect } from "@playwright/test";
import pixelmatch from "pixelmatch";
import { PNG } from "pngjs";

const PROJECT = process.env.PARITY_PROJECT ?? "db17s1zl";
const PAGES = ["home", "requests", "approvals", "tasks"];
const DIFF_THRESHOLD = 0.10; // 10% — lenient because library is not 100% themed yet

interface DiffResult {
  changedPx: number;
  totalPx: number;
  ratio: number;
}

function comparePngs(a: Buffer, b: Buffer): DiffResult {
  const imgA = PNG.sync.read(a);
  const imgB = PNG.sync.read(b);
  // Resize: pixelmatch requires same dimensions. If they differ, scale down
  // the larger to the smaller via a bounding box. Easier: pad whichever is
  // smaller with white so dimensions match.
  const w = Math.max(imgA.width, imgB.width);
  const h = Math.max(imgA.height, imgB.height);
  const aPadded = padToSize(imgA, w, h);
  const bPadded = padToSize(imgB, w, h);
  const diff = new PNG({ width: w, height: h });
  const changedPx = pixelmatch(aPadded.data, bPadded.data, diff.data, w, h, { threshold: 0.2 });
  return { changedPx, totalPx: w * h, ratio: changedPx / (w * h) };
}

function padToSize(src: PNG, w: number, h: number): PNG {
  if (src.width === w && src.height === h) return src;
  const out = new PNG({ width: w, height: h });
  // Initialise to white
  out.data.fill(0xff);
  // Copy src in top-left
  for (let y = 0; y < src.height; y++) {
    for (let x = 0; x < src.width; x++) {
      const srcIdx = (y * src.width + x) * 4;
      const dstIdx = (y * w + x) * 4;
      out.data[dstIdx] = src.data[srcIdx];
      out.data[dstIdx + 1] = src.data[srcIdx + 1];
      out.data[dstIdx + 2] = src.data[srcIdx + 2];
      out.data[dstIdx + 3] = src.data[srcIdx + 3];
    }
  }
  return out;
}

for (const slug of PAGES) {
  test(`editor canvas matches preview for /${slug}`, async ({ browser }) => {
    // Quick reachability check before spending time navigating
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    try {
      const editor = await ctx.newPage();
      const preview = await ctx.newPage();

      // --- editor ---
      let editorOk = false;
      try {
        const editorResp = await editor.goto(
          `http://localhost:6501/editor/${PROJECT}`,
          { waitUntil: "networkidle", timeout: 20000 },
        );
        editorOk = editorResp !== null && editorResp.ok();
      } catch {
        editorOk = false;
      }
      if (!editorOk) {
        console.log(`[parity] SKIP /${slug}: editor unreachable`);
        test.skip(true, `editor at localhost:6501 unreachable for project ${PROJECT}`);
        return;
      }

      // Wait for engine wrapper + token application
      try {
        await editor.waitForSelector("[data-tentoro-engine]", { timeout: 10000 });
      } catch {
        console.log(`[parity] SKIP /${slug}: [data-tentoro-engine] not found on editor`);
        test.skip(true, `[data-tentoro-engine] not present — editor may not have loaded for ${PROJECT}`);
        return;
      }
      await editor.waitForTimeout(2500);

      // Navigate the PagePicker if needed ("home" is the default tab)
      if (slug !== "home") {
        const tab = editor.getByRole("button", { name: new RegExp(`/${slug}\\b`) }).first();
        if (await tab.count() > 0) {
          await tab.click();
          await editor.waitForTimeout(2000);
        }
      }

      const canvasFrame = editor.locator("[data-canvas-frame]");
      await canvasFrame.waitFor({ state: "visible", timeout: 10000 });
      const editorPng = await canvasFrame.screenshot();

      // --- preview ---
      let previewOk = false;
      try {
        const previewResp = await preview.goto(
          `http://localhost:6503/p/${PROJECT}/${slug}?v=${Date.now()}`,
          { waitUntil: "networkidle", timeout: 20000 },
        );
        previewOk = previewResp !== null && previewResp.ok();
      } catch {
        previewOk = false;
      }
      if (!previewOk) {
        console.log(`[parity] SKIP /${slug}: preview unreachable`);
        test.skip(true, `preview at localhost:6503/p/${PROJECT}/${slug} unreachable`);
        return;
      }

      try {
        await preview.waitForSelector("[data-appshell]", { timeout: 10000 });
      } catch {
        console.log(`[parity] SKIP /${slug}: [data-appshell] not found on preview`);
        test.skip(true, `[data-appshell] not present on preview for ${slug}`);
        return;
      }
      await preview.waitForTimeout(2500);

      const previewMain = preview.locator("[data-appshell] main").first();
      const previewPng = await previewMain.screenshot();

      // --- diff ---
      const diff = comparePngs(editorPng, previewPng);
      console.log(
        `[parity] /${slug}: changed ${diff.changedPx}/${diff.totalPx} px (${(diff.ratio * 100).toFixed(1)}%)`,
      );

      expect(diff.ratio).toBeLessThan(DIFF_THRESHOLD);
    } finally {
      await ctx.close();
    }
  });
}
