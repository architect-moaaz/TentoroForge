import { defineConfig, devices } from "@playwright/test";

/**
 * E2E config for driving the REAL editor.
 *
 * BASE_URL defaults to the editor you already have running on :6501. Override
 * with E2E_BASE_URL if you start one elsewhere. Note this therefore tests
 * WHATEVER BRANCH that server was built from — not necessarily this worktree.
 *
 * Auth: tests reuse the storage state written by save-auth.mjs. Nothing here
 * ever types a password; you log in once by hand and the session is reused.
 */
export default defineConfig({
  testDir: ".",
  timeout: 900_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["json", { outputFile: "e2e-report.json" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:6501",
    storageState: "tests/e2e/.auth/state.json",
    viewport: { width: 1600, height: 1000 },
    actionTimeout: 15_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
