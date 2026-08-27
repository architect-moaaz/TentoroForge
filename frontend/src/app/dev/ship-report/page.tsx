"use client";

/**
 * Dev preview for ShipReportCard (V3) — mirrors /dev/journey-chip.
 * Renders the three verdict states with representative payloads so the
 * card can be eyeballed without running a full generation.
 */
import { ShipReportCard, type ShipReport } from "@/components/verify/ShipReportCard";

const pass: ShipReport = {
  verdict: "pass",
  mode: "warn",
  summary: { criticals: 0, errors: 0, warnings: 2 },
  sources: {
    delivery: { present: true, criticals: 0, errors: 0, warnings: 2,
      sample: ["density frame missing on /reports", "sparse page without hero"] },
    security: { present: true, criticals: 0, errors: 0, warnings: 0 },
  },
};

const warn: ShipReport = {
  verdict: "warn",
  mode: "warn",
  summary: { criticals: 0, errors: 3, warnings: 1 },
  sources: {
    delivery: { present: true, errors: 2, warnings: 1,
      sample: ['launcher_missing: workflow "ApproveLeave" has no UI trigger',
               'transition_unreachable: /candidates/[id] → /offers'] },
    quarantine: { present: true, errors: 1,
      sample: ['{"check": "binding_contract", "kind": "unknown_slug", "detail": "dataSource equipments"}'] },
  },
};

const block: ShipReport = {
  verdict: "block",
  mode: "warn",
  summary: { criticals: 2, errors: 1, warnings: 0 },
  sources: {
    security: { present: true, criticals: 2, errors: 0,
      sample: ["secret_leak src/lib/mail.ts:12 — AKIA1B…(redacted)",
               "anon_read /api/data/employees returned 200 with rows"] },
    delivery: { present: true, errors: 1, sample: ["launcher_missing: ExportPayroll"] },
  },
};

export default function ShipReportDevPage() {
  return (
    <div className="mx-auto max-w-xl space-y-6 p-8">
      <h1 className="text-lg font-semibold">ShipReportCard states</h1>
      <section className="space-y-1">
        <p className="text-xs text-muted-foreground">pass</p>
        <ShipReportCard report={pass} />
      </section>
      <section className="space-y-1">
        <p className="text-xs text-muted-foreground">warn (click to expand)</p>
        <ShipReportCard report={warn} />
      </section>
      <section className="space-y-1">
        <p className="text-xs text-muted-foreground">block (auto-expanded)</p>
        <ShipReportCard report={block} />
      </section>
    </div>
  );
}
