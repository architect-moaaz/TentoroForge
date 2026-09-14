/**
 * The reportable style finding = measured by BOTH channels AND survived
 * adversarial refutation.
 *
 * Measurement alone is not a verdict: a portal or a headless component
 * legitimately applies no style, and reporting those would be exactly the false
 * positives this whole exercise exists to avoid.
 */
import { readFileSync } from "node:fs";

// Adversarial verdicts from the earlier classification workflow.
const CONFIRMED_BUG = ["ActivityFeed","AppShell","ApprovalStepper","Chart","DataGrid","DateRangePicker",
  "EmptyStateRich","FilterBar","FilterBuilder","Heatmap","Kanban","PersonCard","Redirect",
  "ResourceTimeline","Sparkline","TabPanel","Timeline","Wizard"];
const REFUTED = ["CommandPalette","MultiSelect","SplitView","TabPanelWithDeepLink"];
const PORTAL = ["BulkActionBar","CartBadge","DescriptionList","Dialog","InspectorPanel",
  "KeyboardShortcuts","PresenceIndicator","TourOverlay","UndoManager"];
const HEADLESS = ["AutoFocus","FocusRing","FocusTrap","OptimisticProvider","SkipLink"];

const t2 = JSON.parse(readFileSync("tests/e2e/sweep-style.json", "utf-8"));
const measuredNone = new Set(t2.rows.filter((r) => r.status === "NONE-APPLIED").map((r) => r.component));
const measuredPartial = t2.rows.filter((r) => r.status === "PARTIAL");
const blocked = new Set(t2.rows.filter((r) => r.status === "HARNESS-BLOCKED").map((r) => r.component));

const reportable = CONFIRMED_BUG.filter((c) => measuredNone.has(c)).sort();
const confirmedButBlocked = CONFIRMED_BUG.filter((c) => blocked.has(c)).sort();
const confirmedNotMeasured = CONFIRMED_BUG
  .filter((c) => !measuredNone.has(c) && !blocked.has(c) && !measuredPartial.some((p) => p.component === c))
  .sort();
const excluded = [...PORTAL, ...HEADLESS].filter((c) => measuredNone.has(c)).sort();

console.log("REPORTABLE — both channels agree AND survived refutation");
console.log(`  ${reportable.length}: ${reportable.join(", ")}`);
console.log("");
console.log("CORRECTLY EXCLUDED — measured as dropping style, but portal/headless by design");
console.log(`  ${excluded.length}: ${excluded.join(", ")}`);
console.log("");
console.log("MOTION-ONLY (partial) — everything else applied");
for (const p of measuredPartial) {
  const tag = REFUTED.includes(p.component) ? "refuted"
            : CONFIRMED_BUG.includes(p.component) ? "confirmed-bug" : "unclassified";
  console.log(`  ${String(p.component).padEnd(16)} missing ${p.missing}   (${tag})`);
}
console.log("");
console.log("CONFIRMED BY SOURCE BUT NOT MEASURED IN THE BROWSER — needs a targeted check");
console.log(`  blocked in Tier 2 : ${confirmedButBlocked.join(", ") || "(none)"}`);
console.log(`  applied in Tier 2 : ${confirmedNotMeasured.join(", ") || "(none)"}`);
console.log("");
console.log(`REFUTED, correctly absent from the report: ${REFUTED.join(", ")}`);
