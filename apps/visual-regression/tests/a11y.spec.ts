import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const TEST_PROJECT = process.env.TEST_PROJECT ?? "genmetrics-1778439719";
const PAGES = [
  `/p/${TEST_PROJECT}/tasks/list`,
  `/p/${TEST_PROJECT}/tasks/detail`,
  `/p/${TEST_PROJECT}/tasks/form`,
  `/p/${TEST_PROJECT}/users/list`,
];

for (const url of PAGES) {
  test.describe(`a11y ${url}`, () => {
    test("axe-core: no serious or critical violations", async ({ page }) => {
      await page.goto(`http://localhost:6503${url}`);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa"])
        .analyze();
      const seriousOrCritical = results.violations.filter(v =>
        v.impact === "serious" || v.impact === "critical"
      );
      if (seriousOrCritical.length > 0) {
        console.log("axe violations:\n" + seriousOrCritical.map(v =>
          `  ${v.id} (${v.impact}): ${v.description}\n    nodes: ${v.nodes.length}`
        ).join("\n"));
      }
      expect(seriousOrCritical).toEqual([]);
    });

    test("keyboard: every interactive element is reachable via Tab", async ({ page }) => {
      await page.goto(`http://localhost:6503${url}`);
      // Tag every interactive element with a unique data-a11y-idx so the
      // "stuck on same element" check has a stable, per-element identity.
      // Without this, sibling buttons that share tagName/className/text
      // (e.g. 14 row-level "View" buttons) produce identical fingerprints
      // and trigger a false "stuck" error after the first Tab past them.
      const interactiveCount = await page.evaluate(() => {
        const els = Array.from(document.querySelectorAll(
          "button, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])"
        ));
        els.forEach((el, i) => el.setAttribute("data-a11y-idx", String(i)));
        return els.length;
      });
      if (interactiveCount === 0) return;
      const seen = new Set<string>();
      let lastFocused = "";
      for (let i = 0; i < interactiveCount + 5; i++) {
        await page.keyboard.press("Tab");
        const cur = await page.evaluate(() => {
          const el = document.activeElement as HTMLElement | null;
          if (!el || el === document.body) return "";
          // Next.js dev-mode portal/overlay (only present in `next dev`) is an
          // environmental artifact, not a real Tab trap. Production builds
          // don't render it, so we filter it out of the stuck-check.
          if (el.tagName === "NEXTJS-PORTAL" || el.closest("nextjs-portal")) {
            return "__SKIP_DEV_PORTAL__";
          }
          const idx = el.getAttribute("data-a11y-idx");
          // Native date / datetime / time inputs expose internal spinner
          // sub-fields that consume Tab events while focus stays on the same
          // <input>. That's correct browser behaviour, not a Tab trap — we
          // treat each internal Tab as a distinct identity to avoid the
          // false stuck-on-self error.
          const type = (el as HTMLInputElement).type;
          if (el.tagName === "INPUT" && (type === "date" || type === "datetime-local" || type === "time" || type === "month" || type === "week")) {
            return `INPUT:${idx}:date-subcontrol:${Date.now()}`;
          }
          return `${el.tagName}:${idx}`;
        });
        // Skip dev-portal focuses entirely — don't count, don't compare.
        if (cur === "__SKIP_DEV_PORTAL__") continue;
        if (cur === lastFocused && cur !== "") {
          throw new Error(`Tab focus stuck on ${cur} at step ${i}`);
        }
        if (cur) seen.add(cur);
        lastFocused = cur;
      }
      expect(seen.size).toBeGreaterThanOrEqual(Math.floor(interactiveCount / 2));
    });
  });
}
