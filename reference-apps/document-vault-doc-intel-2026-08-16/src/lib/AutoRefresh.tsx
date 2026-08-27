"use client";

/**
 * AutoRefresh — client-side driver for stateful single-page schemas.
 *
 * A page schema can declare a `poll` object at the top level:
 *
 *     {
 *       "route": "/scan",
 *       "poll": { "interval": 2500, "stopWhen": "scan.status IN ('completed','failed')" },
 *       "dataSources": [...],
 *       "root": {"type": "Conditional", ...}
 *     }
 *
 * When present, schema-page.tsx wraps the rendered tree in this component.
 * On mount it starts a `router.refresh()` interval; every tick re-runs the
 * server RSC path so dataSources re-resolve and the tree re-renders with
 * fresh data. This is how a stateful single-page schema (scan flow: initial
 * → scanning → results) transitions between states without a page navigation.
 *
 * The `stopWhen` expression is evaluated client-side against the latest
 * previewData snapshot the server passed in on this render. When it matches,
 * we clear the interval — no more network calls once the workflow has
 * terminated. Missing/malformed stopWhen ⇒ poll runs until the component
 * unmounts (page nav away).
 *
 * Never runs on the server (client-only via "use client"). Idempotent: two
 * AutoRefresh instances on the same page are legal; each schedules its own
 * refresh loop, and router.refresh() is deduped by Next.
 */

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { evalStopWhen } from "./stopWhen";

type PollSpec = {
  interval?: number;
  stopWhen?: string;
};

type Props = {
  poll: PollSpec;
  previewData?: Record<string, unknown>;
  children: React.ReactNode;
};

// Minimum interval a schema author can request. Sub-second polling on a
// dev server drowns the logs; a live scan workflow needs 2-5s ticks.
const _MIN_INTERVAL_MS = 500;
const _DEFAULT_INTERVAL_MS = 3000;

export function AutoRefresh({ poll, previewData, children }: Props) {
  const router = useRouter();
  const stoppedRef = useRef(false);

  useEffect(() => {
    const interval = Math.max(_MIN_INTERVAL_MS, poll?.interval ?? _DEFAULT_INTERVAL_MS);
    // Evaluate stopWhen BEFORE scheduling — a page that already loaded in the
    // terminal state should never fire a poll tick.
    if (poll?.stopWhen && evalStopWhen(poll.stopWhen, previewData ?? {})) {
      stoppedRef.current = true;
      return;
    }
    const handle = setInterval(() => {
      if (stoppedRef.current) return;
      // Server re-renders the RSC subtree; new previewData arrives via prop.
      // We can't re-read the DOM to check stopWhen — instead we rely on the
      // NEXT render's AutoRefresh mount to short-circuit if the terminal
      // state has been reached.
      router.refresh();
    }, interval);
    return () => clearInterval(handle);
    // Rerun the effect when the incoming previewData (i.e. the state
    // machine's current state) changes — this is the moment stopWhen might
    // newly evaluate true.
  }, [router, poll?.interval, poll?.stopWhen, JSON.stringify(previewData ?? {})]);

  return <>{children}</>;
}

// The pure stopWhen evaluator lives in ./stopWhen so it's testable
// without React. See src/lib/__tests__/stopWhen.node.mjs for the
// smoke test that exercises every supported form.
