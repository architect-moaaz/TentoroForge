"use client";

import { Radio } from "lucide-react";

/**
 * Watch live is not open yet: this page stands in for it. The feature itself (AgentWatchPanel, useAgentWatch) is built
 * and kept; the builder shows this page instead until WATCH_LIVE_READY is switched on in AgentBuilderPanel.
 */
export function WatchComingSoon() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center" data-testid="watch-coming-soon">
      <div className="rounded-full bg-indigo-50 p-4">
        <Radio className="h-8 w-8 text-indigo-600" />
      </div>
      <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-800">Coming soon</span>
      <h2 className="text-lg font-semibold">Watch live</h2>
      <p className="max-w-md text-sm text-muted-foreground">
        Soon you will be able to chat with your real app and watch this diagram light up, box by box, as the agent works: what it was asked, which
        tools it chose, and what came back.
      </p>
      <p className="max-w-md text-xs text-muted-foreground">Until then, use Test for a quick try, and Find problems to stress-test the agent.</p>
    </div>
  );
}
