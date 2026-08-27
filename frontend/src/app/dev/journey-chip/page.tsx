"use client";

/**
 * Dev-only page: renders JourneyGateCard through each of its states side
 * by side so a designer can eyeball the chip without running a real
 * generation. Ships in the tree because it's tiny and useful; hide it
 * from production nav by convention (path is under /dev/*).
 */
import { JourneyGateCard } from "@/components/verify/JourneyGateCard";

export default function JourneyChipPreview() {
  return (
    <div className="p-8 max-w-3xl mx-auto space-y-8 text-sm">
      <h1 className="text-lg font-semibold">JourneyGateCard preview</h1>

      <section className="space-y-2">
        <h2 className="text-xs uppercase tracking-wide text-muted-foreground">
          1. running (streaming journey_result events, no summary yet)
        </h2>
        <JourneyGateCard
          results={[
            { slug: "primary-scan", name: "Scan a product and see prices",
              status: "passed", duration_ms: 38107 },
          ]}
          summary={null}
        />
      </section>

      <section className="space-y-2">
        <h2 className="text-xs uppercase tracking-wide text-muted-foreground">
          2. all passed (green terminal state, warn mode)
        </h2>
        <JourneyGateCard
          results={[
            { slug: "primary-scan", name: "Scan a product and see prices",
              status: "passed", duration_ms: 38107 },
          ]}
          summary={{ mode: "warn", ok: true, total: 1, passed: 1, failed: 0,
                     duration_ms: 40041 }}
        />
      </section>

      <section className="space-y-2">
        <h2 className="text-xs uppercase tracking-wide text-muted-foreground">
          3. one failed (click to expand — strict mode)
        </h2>
        <JourneyGateCard
          results={[
            { slug: "primary-scan", name: "Scan a product and see prices",
              status: "failed", duration_ms: 100719,
              failing_step: "Workflow runs to terminal",
              failure: "Error: wait_for_workflow timed out: scan-product-workflow not terminal" },
            { slug: "admin-approve", name: "Admin approves a retailer",
              status: "passed", duration_ms: 12300 },
          ]}
          summary={{ mode: "strict", ok: false, total: 2, passed: 1, failed: 1,
                     duration_ms: 113019 }}
          hints={[
            { journey_slug: "primary-scan",
              failing_step: "Workflow runs to terminal",
              likely_cause: "Workflow never reached a terminal status.",
              target_seam: "workflow-definition",
              hint: "The workflow either had no path from start to a terminal node, hung on a specific action_type, or crashed silently. Inspect workflows/*.json.",
              tags: ["workflow", "runtime"] },
          ]}
        />
      </section>

      <section className="space-y-2">
        <h2 className="text-xs uppercase tracking-wide text-muted-foreground">
          4. off (no results, no summary → renders nothing)
        </h2>
        <JourneyGateCard results={[]} summary={null} />
        <p className="text-xs text-muted-foreground">
          (chip is hidden — you should see empty space above)
        </p>
      </section>
    </div>
  );
}
