import { defineConfig, devices } from "@playwright/test";

/**
 * TIER 2 — real browser, against the frontend built from THIS worktree.
 *
 * Port 3000, not 6501: the editor on 6501 is built from smithv2-editor-fixes,
 * a different tree 32 commits ahead, so testing it would audit code these fixes
 * do not land in. This worktree runs on 3000 against the same backend on 6500.
 *
 * Why 3000 specifically: the backend's ALLOWED_ORIGINS defaults to
 * localhost:{3000,6501} (config.py:95-98). An earlier attempt on 6701 was
 * CORS-blocked on every API call, and the editor sat on a loading spinner
 * forever with NO console error and NO 4xx — the failure surfaces only as
 * `requestfailed`. 3000 is already allow-listed, so no backend restart and no
 * disruption to the session running on 6501.
 *
 * Auth uses state-3000.json — localStorage is keyed by ORIGIN (port included),
 * so the session captured on 6501 has to be re-originned (tests/e2e/port-auth.mjs 3000).
 *
 * Viewport is 1600x1000 because the palette only renders at >=1280px
 * (useMediaQuery "(min-width: 1280px)"); a narrower window would report an
 * empty palette as a defect.
 */
export default defineConfig({
  testDir: ".",
  // 60 min, not 15. The props sweep needs ~16 min for 113 components and was
  // killed mid-run at #100 by the old 15-min cap — the partial ledger survived
  // only because it flushes every 5 components.
  timeout: 3_600_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    storageState: "tests/e2e/.auth/state-3000.json",
    // HEADED BY DEFAULT — the run is meant to be watched, and a flag that has
    // to be remembered gets forgotten. Set E2E_HEADLESS=1 for an unattended run.
    headless: process.env.E2E_HEADLESS === "1",
    viewport: { width: 1600, height: 1000 },
    actionTimeout: 15_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
