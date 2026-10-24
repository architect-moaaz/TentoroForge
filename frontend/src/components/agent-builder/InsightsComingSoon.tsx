"use client";

import { BarChart3 } from "lucide-react";

/**
 * Insights is not open yet: this page stands in for it. The feature itself (AgentInsightsPanel and what feeds it) is built
 * and kept; the builder shows this page instead until INSIGHTS_READY is switched on (insights-ready.ts).
 */
export function InsightsComingSoon() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center" data-testid="insights-coming-soon">
      <div className="rounded-full bg-indigo-50 p-4">
        <BarChart3 className="h-8 w-8 text-indigo-600" />
      </div>
      <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-800">Coming soon</span>
      <h2 className="text-lg font-semibold">Insights</h2>
      <p className="max-w-md text-sm text-muted-foreground">
        Soon you will see how your agent is doing once real people use it: how many chats it has, what each answer costs, how often it
        gets things right, and what people thought of its answers.
      </p>
      <p className="max-w-md text-xs text-muted-foreground">Until then, use Test for a quick try, and Find problems to stress-test the agent.</p>
    </div>
  );
}
