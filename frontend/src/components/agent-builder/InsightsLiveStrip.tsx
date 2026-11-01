"use client";

/**
 * The top of a live app's report: a quiet line saying where the numbers come from and how fresh they are (and, never hidden, how many
 * events were turned away), and the "right now" strip: replies a minute, people using it, how many failed and how slow the slowest were in
 * the last five minutes.
 *
 * No chart library and no new colours: a status dot, big figures and words. A failure rate is always said in words ("2.5% of replies
 * failed"), never only shown as a colour, and the dot is only ever a hint beside the words "Live" or "Waiting for events".
 */
import { AlertTriangle, Info } from "lucide-react";
import {
  droppedText, formatDuration, formatPct, formatRate, freshnessText, isLiveNow, peopleCount, type Insights, type RangeChoice,
} from "@/lib/agent-insights";
import type { Strip } from "./useAgentInsights";

/** The sentence for how far back the numbers go. */
export const RANGE_SENTENCE: Record<RangeChoice, string> = {
  "1h": "The last hour",
  "24h": "The last 24 hours",
  "7d": "The last 7 days",
  "30d": "The last 30 days",
  "90d": "The last 90 days",
};

/** Above this share of failed replies the strip says so with words and a warm tint. */
const FAILURE_HIGH_PCT = 10;

export function LiveSourceLine({ data, strip, range }: { data: Insights; strip: Strip | null; range: RangeChoice }) {
  const freshness = strip?.freshness ?? data.freshness ?? null;
  const exact = strip?.exact ?? data.exact;
  const dropped = droppedText(data.droppedEvents);
  const shownRange = data.range ?? range;
  return (
    <div className="space-y-2" data-testid="insights-scope">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
        <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[10px] font-medium text-sky-900" data-testid="insights-source">Live app</span>
        <span>{RANGE_SENTENCE[shownRange]}.</span>
        <span data-testid="insights-freshness">{freshnessText(freshness, exact)}</span>
        {data.granularity && data.granularity !== "day" && <span>Times are in your time zone.</span>}
      </p>
      {dropped && (
        <div role="status" className="flex items-start gap-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900" data-testid="insights-dropped">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{dropped}</span>
        </div>
      )}
    </div>
  );
}

export function LiveStrip({ data, strip }: { data: Insights; strip: Strip | null }) {
  const live = strip?.live ?? data.live ?? null;
  const freshness = strip?.freshness ?? data.freshness ?? null;
  const stale = strip?.stale === true;
  const flowing = isLiveNow(freshness) && !stale;
  const approximate = data.users?.approximate === true;
  const failed = live?.errorRatePct5m ?? null;
  const failureHigh = failed !== null && failed >= FAILURE_HIGH_PCT;

  return (
    <section aria-label="Right now" className="rounded-xl border bg-white px-4 py-3 shadow-sm" data-testid="insights-live-strip" data-live={flowing ? "true" : "false"}>
      <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
        <div className="flex items-center gap-2 text-xs font-medium" data-testid="insights-live-state">
          <span className="relative flex h-2.5 w-2.5" aria-hidden="true">
            {flowing && <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-500 opacity-60 motion-safe:animate-ping" />}
            <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${flowing ? "bg-emerald-500" : "bg-slate-300"}`} />
          </span>
          <span>{stale ? "Not updating" : flowing ? "Live" : "Waiting for events"}</span>
        </div>
        {live ? (
          // Four figures side by side when there is room, two by two when there is not, never one orphan on a row of its own.
          <div className="grid min-w-0 flex-1 grid-cols-2 gap-x-6 gap-y-3 sm:min-w-[34rem] sm:grid-cols-4">
            <Figure id="rate" value={formatRate(live.turnsPerMinute)} label={live.turnsPerMinute === 1 ? "reply a minute" : "replies a minute"} />
            <Figure
              id="people"
              value={peopleCount(live.activeUsers5m, approximate)}
              label={live.activeUsers5m === 1 && !approximate ? "person using it, last 5 minutes" : "people using it, last 5 minutes"}
            />
            <Figure
              id="failed"
              value={failed === null ? "n/a" : formatPct(failed)}
              label={failed === null ? "no replies in the last 5 minutes" : `of replies failed in the last 5 minutes${failureHigh ? ", more than 1 in 10" : ""}`}
              warn={failureHigh}
            />
            <Figure id="slow" value={formatDuration(live.p95Ms5m)} label="slowest 1 in 20 replies, last 5 minutes" />
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">No numbers for the last 5 minutes yet.</span>
        )}
      </div>
      {stale && (
        <p className="mt-2 flex items-center gap-1.5 text-[11px] text-amber-800" data-testid="insights-live-stale">
          <Info className="h-3 w-3 shrink-0" />
          The live numbers could not be refreshed just now. These are the last ones we got.
        </p>
      )}
    </section>
  );
}

function Figure({ id, value, label, warn = false }: { id: string; value: string; label: string; warn?: boolean }) {
  return (
    <div className="min-w-0" data-testid={`insights-live-${id}`} data-warn={warn ? "true" : undefined}>
      <div className="flex items-center gap-1.5 text-xl font-semibold leading-none tabular-nums">
        {warn && <AlertTriangle className="h-4 w-4 shrink-0 text-amber-700" aria-hidden="true" />}
        <span className={warn ? "text-amber-900" : ""}>{value}</span>
      </div>
      <div className="mt-1 text-[11px] leading-snug text-muted-foreground">{label}</div>
    </div>
  );
}
