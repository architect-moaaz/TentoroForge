// apps/visual-regression/tests/components.spec.ts
import { test, expect } from "@playwright/test";

const PLAYGROUND_URL = "/component-playground";

const COMPONENTS = [
  "Button", "Heading", "Hero", "MetricTile", "Card", "Avatar",
  "Badge", "Alert", "KeyValueList", "Skeleton", "Breadcrumb", "Divider",
  "MetricTile-importance",
  "Hero-role",
  "Section-role",
  "Card-density",
  "Heading-weight",
  "Sparkline", "Chart", "DataGrid", "Timeline",
  "ApprovalStepper", "PersonCard", "FilterBar", "CommandPalette", "ActivityFeed",
  "EmptyStateRich", "DateRangePicker", "MultiSelect",
  "AppShell", "InspectorPanel", "TabPanelWithDeepLink",
] as const;

test.describe("library component visual baselines", () => {
  for (const name of COMPONENTS) {
    test(`${name} default`, async ({ page }) => {
      await page.goto(PLAYGROUND_URL);
      await page.waitForLoadState("networkidle");
      const locator = page.locator(`[data-component="${name}"]`);
      await expect(locator).toHaveScreenshot(`${name}.png`);
    });
  }

  test("full playground", async ({ page }) => {
    await page.goto(PLAYGROUND_URL);
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("_playground.png", { fullPage: true });
  });
});
