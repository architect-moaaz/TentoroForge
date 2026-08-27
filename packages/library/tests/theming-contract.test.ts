import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

// Files explicitly grandfathered until follow-up migration.
const ALLOWED_HOLDOUTS = [
  "ApprovalStepper/ApprovalStepper.tsx",
  "PersonCard/PersonCard.tsx",
  "ActivityFeed/ActivityFeed.tsx",
  "Timeline/Timeline.tsx",
  "MetricTile/MetricTile.tsx",
  "MetricTile/MetricTile.linear.tsx",
  "MetricTile/MetricTile.stripe.tsx",
  "MetricTile/MetricTile.workday.tsx",
  "MetricTile/MetricTile.figma.tsx",
  "MetricTile/MetricTile.notion.tsx",
];

const BANNED =
  /\b(bg|text|border|from|to|ring|outline|divide)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/;

/** Recursively collect .tsx files under `dir`. */
function collectTsx(dir: string): string[] {
  const results: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      results.push(...collectTsx(full));
    } else if (entry.endsWith(".tsx")) {
      results.push(full);
    }
  }
  return results;
}

const COMPONENTS_ROOT = join(
  import.meta.dirname ?? __dirname,
  "../src/components",
);

describe("library theming contract", () => {
  const files = collectTsx(COMPONENTS_ROOT);
  const enforced = files.filter(
    (f) => !ALLOWED_HOLDOUTS.some((h) => f.endsWith(h)),
  );

  it.each(enforced)("%s uses no raw Tailwind palette classes", (file) => {
    const src = readFileSync(file, "utf8");
    const hits = src.match(new RegExp(BANNED.source, "g"));
    expect(hits, `palette classes found: ${hits?.join(", ")}`).toBeNull();
  });
});
