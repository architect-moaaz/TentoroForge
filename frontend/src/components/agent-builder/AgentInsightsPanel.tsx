"use client";

/**
 * Insights: how an agent is doing, what it costs and how good it is.
 *
 * Fills the canvas area like Find problems does. The numbers come from one of two places and the page says which: a LIVE app that sends
 * every chat to the platform (every chat counted, no Watch live needed), or, when there is none, the development app connected in Watch
 * live (see useAgentInsights). Money is always an estimate from list prices, and a model with no price is shown as tokens only: it is
 * never guessed. With neither, the page offers to connect a live app and says where to connect the development one.
 *
 * One scroll region (the body), so it works at 700px wide: the cards wrap to two or three columns and the tables scroll sideways inside
 * their own box rather than the page.
 */
import { useState } from "react";
import { AlertTriangle, BarChart3, CheckCircle2, ChevronDown, ChevronRight, Info, Loader2, Radio, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ago, countOf, dayLabel, downsampleRows, formatCount, formatDuration, formatMinutes, formatMoney, formatPct, formatTokens, granularityFor, maxColumns,
  modelCost, peopleCount, RANGE_CHOICES, REASON_LABEL, seriesRows, dayRows, sortTips, type ChartRow, type Insights, type Problem, type RangeChoice,
} from "@/lib/agent-insights";
import { ColumnChart, LineChart, Meter, SpeedRange, Sparkline, TokenSplit, ToolBars, VizStyles } from "./insights-charts";
import { ChartCard, Empty, Section, StatTile } from "./insights-parts";
import { InsightsLiveSetup } from "./InsightsLiveSetup";
import { LiveSourceLine, LiveStrip } from "./InsightsLiveStrip";
import { InsightsPeople } from "./InsightsPeople";
import { useAgentInsights, type InsightsSource, type Strip } from "./useAgentInsights";

interface Props {
  projectId: string;
  agentId: string;
  agentName: string;
  /** Where the development app is, exactly as Watch live was connected: "tunnel" (the builder's computer), a localhost address, or "" when none is connected. */
  appUrl: string;
  /** Takes the builder to Watch live, where the development app is connected. Without it the empty state just says where to go. */
  onOpenWatch?: () => void;
}

export function AgentInsightsPanel({ projectId, agentId, agentName, appUrl, onOpenWatch }: Props) {
  const [range, setRange] = useState<RangeChoice>("7d");
  const app = appUrl.trim();
  const { data, source, loading, settled, error, reason, liveReason, updatedAt, strip, refresh, devRange } = useAgentInsights({ projectId, agentId, appUrl: app, range });
  const connected = app !== "";
  const problem = reason ?? error;
  // A development app only knows whole days: the choice it can answer is the one shown as chosen, and the other two are not offered.
  const chosen = source === "dev" ? devRange : range;

  return (
    <div className="flex h-full min-w-0 flex-col overflow-hidden bg-white" data-testid="agent-insights">
      <div className="shrink-0 border-b px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <BarChart3 className="h-4 w-4 text-sky-600" />
          <h3 className="text-sm font-semibold">Insights</h3>
          <span className="min-w-0 truncate text-xs text-muted-foreground" title={agentName}>{agentName}</span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {updatedAt && !loading && source === "dev" && (
              <span className="text-[11px] text-muted-foreground" data-testid="insights-updated">
                Updated {new Date(updatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
            {loading && data && <span className="text-[11px] text-muted-foreground" data-testid="insights-refreshing">Refreshing…</span>}
            <div className="flex flex-wrap gap-1" role="group" aria-label="How far back to look">
              {RANGE_CHOICES.map((c) => {
                const devCannot = source === "dev" && c.value !== devRange && (c.value === "1h" || c.value === "24h");
                return (
                  <Button
                    key={c.value}
                    size="sm"
                    variant={chosen === c.value ? "default" : "outline"}
                    className="h-7 px-2 text-xs"
                    aria-pressed={chosen === c.value}
                    onClick={() => setRange(c.value)}
                    disabled={devCannot}
                    title={devCannot ? "The development app can only show whole days. Connect a live app to see this." : undefined}
                  >
                    {c.label}
                  </Button>
                );
              })}
            </div>
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => void refresh()} disabled={loading}>
              {loading ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <RefreshCw className="mr-1 h-3 w-3" />}
              Refresh
            </Button>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3" data-testid="insights-body">
        {problem && (
          <div role="alert" className="flex flex-wrap items-center gap-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900" data-testid="insights-problem">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span className="min-w-0 flex-1">
              {problem}
              {data ? " The numbers below are the last ones we got." : ""}
            </span>
            {onOpenWatch && source !== "live" && connected && (
              <Button size="sm" variant="outline" className="h-6 text-[11px]" onClick={onOpenWatch}>
                Open Watch live
              </Button>
            )}
          </div>
        )}
        {data?.warning && (
          <div role="status" className="flex items-start gap-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900" data-testid="insights-warning">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{data.warning}</span>
          </div>
        )}
        {data && source ? (
          <>
            <Report data={data} source={source} strip={strip} range={range} refreshing={loading} />
            <LiveSetupDisclosure projectId={projectId} reason={source === "dev" ? liveReason : null} />
          </>
        ) : !settled ? (
          <Skeleton />
        ) : (
          <div className="mx-auto max-w-2xl space-y-4" data-testid="insights-setup">
            <InsightsLiveSetup projectId={projectId} reason={liveReason} standalone />
            {!connected && (
              <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-6 text-center" data-testid="insights-empty">
                <Radio className="h-6 w-6 text-sky-600" />
                <p className="text-sm font-semibold">Or look at the app you run while you build</p>
                <p className="text-xs text-muted-foreground">
                  Connect your development app once in Watch live, then come back here to see what the agent costs and how well it is doing.
                  It only sees that one app on your computer, not your live users.
                </p>
                {onOpenWatch && (
                  <Button size="sm" onClick={onOpenWatch}>
                    Open Watch live
                  </Button>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** The setup card, always one click away at the bottom of a report. It is only built (and the key only asked for) once opened, then kept so a key just made is not lost by closing it. */
function LiveSetupDisclosure({ projectId, reason }: { projectId: string; reason: string | null }) {
  const [open, setOpen] = useState(false);
  const [everOpened, setEverOpened] = useState(false);
  return (
    <section className="pb-2" data-testid="insights-section-connect" aria-label="Connect a live app">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="insights-connect-body"
        onClick={() => {
          setOpen((o) => !o);
          setEverOpened(true);
        }}
        className="flex items-center gap-1 rounded text-sm font-semibold hover:text-sky-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
      >
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        Connect a live app
      </button>
      <div id="insights-connect-body" hidden={!open} className="mt-2">
        {everOpened && <InsightsLiveSetup projectId={projectId} reason={reason} />}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// the report
// ---------------------------------------------------------------------------

function Report({
  data, source, strip, range, refreshing = false,
}: { data: Insights; source: InsightsSource; strip: Strip | null; range: RangeChoice; refreshing?: boolean }) {
  const q = data.quality;
  const t = data.totals;
  const cost = data.cost;
  const tools = [...data.tools].sort((a, b) => b.calls - a.calls);
  const tips = sortTips(data.tips);
  const noChats = t.turns === 0;
  // A live app answers in buckets of a minute, an hour or a day; a development app in days. The table keeps every bucket, the drawing
  // gets no more columns than are readable.
  const live = source === "live";
  const granularity = live && data.series ? data.granularity ?? granularityFor(data.range ?? range) : "day";
  const rows: ChartRow[] = live && data.series && data.series.length > 0 ? seriesRows(data.series, granularity) : dayRows(data);
  const days = downsampleRows(rows, maxColumns(granularity));
  const anyCost = rows.some((d) => d.usd !== null);
  const anyTurns = rows.some((d) => d.turns > 0);
  const each = granularity; // "minute", "hour" or "day"
  const about = data.users?.approximate === true;
  const failureHigh = q.toolFailures.pct !== null && q.toolFailures.pct > 20;

  return (
    // While the numbers are fetched again the last ones stay on screen, slightly faded: no flash, no jump.
    <div className={`viz space-y-5 transition-opacity ${refreshing ? "opacity-60" : ""}`} aria-busy={refreshing}>
      <VizStyles />
      {live ? (
        <>
          <LiveSourceLine data={data} strip={strip} range={range} />
          <LiveStrip data={data} strip={strip} />
        </>
      ) : (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground" data-testid="insights-scope">
          <span className="rounded-full border px-2 py-0.5 text-[10px] font-medium text-foreground" data-testid="insights-source">Development app on your computer</span>
          <span>
            The last {data.days} days in the app connected in Watch live (your development app, not a live one)
            {data.firstTurnAt ? `. The first chat recorded was on ${dayLabel(data.firstTurnAt.slice(0, 10))}` : ""}.
          </span>
        </p>
      )}

      <section className="space-y-3" aria-label="The headline numbers" data-testid="insights-cards">
        <div className="rounded-xl border bg-white p-4 shadow-sm" data-testid="insights-card-cost">
          <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
            <div className="min-w-0">
              <div className="text-xs text-muted-foreground">Estimated cost</div>
              <div className={`mt-1.5 font-semibold leading-none tracking-tight ${cost.estimatedUsd === null && t.turns > 0 ? "text-2xl" : "text-5xl"}`}>
                {formatMoney(cost.estimatedUsd)}
              </div>
              <div className="mt-2.5 text-xs text-muted-foreground">
                {cost.estimatedUsd === null ? "No price on file for this model" : cost.perChatUsd === null ? "No chats yet" : `${formatMoney(cost.perChatUsd)} per chat`}
              </div>
              {cost.partial && <div className="mt-0.5 text-[11px] text-amber-800">Models with no price are left out</div>}
            </div>
            {anyCost && (
              <div className="w-full min-w-0 sm:w-72">
                <Sparkline values={days.map((d) => d.usd)} wide height={60} />
                <div className="mt-0.5 flex justify-between text-[10px] text-muted-foreground" aria-hidden="true">
                  <span>{days[0].label}</span>
                  <span>{days[days.length - 1].label}</span>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
          <StatTile id="chats" label="Chats" value={formatCount(t.conversations)} sub={`${formatCount(t.turns)} ${t.turns === 1 ? "reply" : "replies"}, ${peopleCount(t.users, about)} ${t.users === 1 && !about ? "person" : "people"}`}>
            {anyTurns && (
              <div className="mt-2">
                <Sparkline values={days.map((d) => d.turns)} height={28} />
              </div>
            )}
          </StatTile>
          <StatTile id="answered" label="Answered without a person" value={formatPct(q.answeredWithoutPerson.pct)} sub={noChats ? "No replies yet" : `${countOf(q.answeredWithoutPerson)} replies`}>
            <Meter pct={q.answeredWithoutPerson.pct} label="Share of replies answered without a person" />
          </StatTile>
          <StatTile id="thumbs" label="Thumbs up" value={formatPct(q.thumbsUp.pct)} sub={q.thumbsUp.of > 0 ? `${q.thumbsUp.count} of ${q.thumbsUp.of} rated` : "No ratings yet"}>
            <Meter pct={q.thumbsUp.pct} label="Share of rated replies that got a thumbs up" />
          </StatTile>
          <StatTile id="speed" label="Typical speed" value={formatDuration(q.speed.p50Ms)} sub="" tone={q.speed.slow ? "warn" : undefined}>
            {q.speed.p50Ms !== null && q.speed.p95Ms !== null ? <SpeedRange p50Ms={q.speed.p50Ms} p95Ms={q.speed.p95Ms} /> : <div className="mt-1.5 text-[11px] text-muted-foreground">No replies timed yet</div>}
          </StatTile>
          <StatTile
            id="tools"
            label="Tool failures"
            value={formatPct(q.toolFailures.pct)}
            sub={q.toolFailures.of > 0 ? `${countOf(q.toolFailures)} tool calls${failureHigh ? ", more than 1 in 5" : ""}` : "No tool calls yet"}
            tone={failureHigh ? "warn" : undefined}
          >
            <Meter pct={q.toolFailures.pct} bad={failureHigh} label="Share of tool calls that failed" />
          </StatTile>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard
          id="daily"
          title={`Replies each ${each}`}
          subtitle={`${t.errors > 0 ? "Part of a column in red: replies that failed" : `One column for each ${each}`}${each === "day" ? "" : ". Times are in your time zone"}${days.length < rows.length ? `. Neighbouring ${each}s are added together to draw it; the table has every one` : ""}`}
          empty={days.length === 0 || !anyTurns ? "No replies were recorded in this time." : null}
          table={<DayTable rows={rows} each={each} showPeople={live} approximate={about} />}
        >
          <div data-testid="insights-chart">
            <ColumnChart days={days} what={`Replies each ${each}`} />
          </div>
        </ChartCard>

        <ChartCard
          id="daily-cost"
          title={`Estimated cost each ${each}`}
          subtitle={`From list prices; ${each}s with no known price are left blank`}
          empty={days.length === 0 || !anyTurns ? "No replies were recorded in this time." : null}
          table={<DayTable rows={rows} each={each} showPeople={live} approximate={about} />}
        >
          {anyCost ? (
            <LineChart days={days} what={`Estimated cost each ${each}`} />
          ) : (
            <p className="rounded-md border border-dashed px-3 py-6 text-center text-xs text-muted-foreground" data-testid="insights-cost-legend">
              Cost each {each} is not shown because a price is not known.
            </p>
          )}
        </ChartCard>
      </div>

      {live && data.users && <InsightsPeople users={data.users} />}

      <Section title="Where the cost goes" id="models" hint={cost.note}>
        {cost.byModel.length === 0 ? (
          <Empty>No model use has been recorded yet.</Empty>
        ) : (
          <div className="space-y-3 rounded-xl border bg-white p-4 shadow-sm">
            <div>
              <div className="mb-2 text-xs font-medium">What the tokens are spent on</div>
              <TokenSplit inputTokens={t.inputTokens} outputTokens={t.outputTokens} />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-left text-xs">
                <thead className="text-[11px] text-muted-foreground">
                  <tr className="border-b">
                    <th className="px-2 py-1.5 font-medium">Model</th>
                    <th className="px-2 py-1.5 text-right font-medium">Replies</th>
                    <th className="px-2 py-1.5 text-right font-medium">Tokens in</th>
                    <th className="px-2 py-1.5 text-right font-medium">Tokens out</th>
                    <th className="px-2 py-1.5 text-right font-medium">Estimated cost</th>
                  </tr>
                </thead>
                <tbody>
                  {cost.byModel.map((m) => (
                    <tr key={m.model} className="border-b last:border-b-0" data-testid="insights-model-row">
                      <td className="px-2 py-2 font-mono text-[11px]">{m.model}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{m.turns}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{formatTokens(m.inputTokens)}</td>
                      <td className="px-2 py-2 text-right tabular-nums">{formatTokens(m.outputTokens)}</td>
                      <td className={`px-2 py-2 text-right tabular-nums ${m.priced ? "" : "text-amber-700"}`}>{modelCost(m)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t font-medium">
                    <td className="px-2 py-2" colSpan={2}>{cost.partial ? "Total of the models with a price" : "Total (estimate)"}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{formatTokens(t.inputTokens)}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{formatTokens(t.outputTokens)}</td>
                    <td className="px-2 py-2 text-right tabular-nums" data-testid="insights-total-cost">{formatMoney(cost.estimatedUsd)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
            {cost.unpricedModels.length > 0 && (
              <p className="text-[11px] text-amber-800" data-testid="insights-unpriced">
                Price unknown for {cost.unpricedModels.join(", ")}. Its tokens are shown, but nothing is added to the total for it.
              </p>
            )}
          </div>
        )}
      </Section>

      <ChartCard
        id="tools-table"
        title="Tools"
        subtitle="How often each tool was used, busiest first; the red end of a bar is calls that failed"
        empty={tools.length === 0 ? "No tools were used in this time." : null}
        table={<ToolTable tools={tools} />}
        plain
      >
        <ToolBars tools={tools} />
      </ChartCard>

      <Section title="Things to look at" id="look-at">
        {tips.length === 0 ? (
          <p className="flex items-center gap-1.5 text-xs text-green-700" data-testid="insights-no-tips">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Nothing stands out. The agent looks healthy for this time.
          </p>
        ) : (
          <ul className="space-y-1.5" data-testid="insights-tips">
            {tips.map((tip) => (
              <li
                key={tip.id}
                data-severity={tip.severity}
                className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${tip.severity === "warn" ? "border-amber-300 bg-amber-50 text-amber-900" : "border-sky-200 bg-sky-50 text-sky-900"}`}
              >
                {tip.severity === "warn" ? <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
                <span>{tip.text}</span>
              </li>
            ))}
          </ul>
        )}

        <h5 className="mt-4 text-xs font-semibold">Chats that went wrong</h5>
        {data.problems.length === 0 ? (
          <Empty>No chats went wrong in this time.</Empty>
        ) : (
          <ul className="mt-1.5 space-y-1.5" data-testid="insights-problems">
            {[...data.problems]
              .sort((a, b) => Date.parse(b.at ?? "") - Date.parse(a.at ?? "") || 0)
              .map((p, i) => (
                <ProblemRow key={`${p.conversationId}-${i}`} p={p} />
              ))}
          </ul>
        )}
      </Section>

      <Section title="Handed to a person" id="handoffs">
        {data.handoffs.total === 0 ? (
          <Empty>Nothing was handed to a person in this time.</Empty>
        ) : (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-xl border bg-white px-4 py-3 text-xs shadow-sm" data-testid="insights-handoffs">
            <span className="inline-flex items-center gap-1.5">All <Badge variant="secondary">{data.handoffs.total}</Badge></span>
            <span className="inline-flex items-center gap-1.5">Waiting <Badge variant="outline">{data.handoffs.open}</Badge></span>
            <span className="inline-flex items-center gap-1.5">Picked up <Badge variant="outline">{data.handoffs.claimed}</Badge></span>
            <span className="inline-flex items-center gap-1.5">Resolved <Badge variant="outline">{data.handoffs.resolved}</Badge></span>
            <span className="text-muted-foreground">
              Average time to resolve: {data.handoffs.avgResolveMinutes === null ? "n/a" : formatMinutes(data.handoffs.avgResolveMinutes)}
            </span>
          </div>
        )}
      </Section>

      <p className="pb-2 text-[11px] text-muted-foreground" data-testid="insights-note">{cost.note}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// pieces
// ---------------------------------------------------------------------------

/** The numbers behind the two time charts: every bucket, newest first. */
function DayTable({ rows, each, showPeople, approximate }: { rows: ChartRow[]; each: "minute" | "hour" | "day"; showPeople: boolean; approximate: boolean }) {
  const head = each === "day" ? "Day" : each === "hour" ? "Hour" : "Minute";
  return (
    <div className="max-h-72 overflow-auto" data-testid="insights-day-table">
      <table className="w-full text-left text-xs">
        <caption className="sr-only">Replies and estimated cost for each {each}</caption>
        <thead className="sticky top-0 bg-white text-[11px] text-muted-foreground">
          <tr className="border-b">
            <th className="px-2 py-1.5 font-medium">{head}</th>
            <th className="px-2 py-1.5 text-right font-medium">Replies</th>
            <th className="px-2 py-1.5 text-right font-medium">Failed</th>
            <th className="px-2 py-1.5 text-right font-medium">Estimated cost</th>
            {showPeople && <th className="px-2 py-1.5 text-right font-medium">{approximate ? "People (about)" : "People"}</th>}
          </tr>
        </thead>
        <tbody>
          {[...rows].reverse().map((d, i) => (
            <tr key={`${d.day}-${i}`} className="border-b last:border-b-0">
              <td className="px-2 py-1.5">{d.label}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{d.turns}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{d.errors}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{d.usd === null ? "price unknown" : formatMoney(d.usd)}</td>
              {showPeople && <td className="px-2 py-1.5 text-right tabular-nums">{formatCount(d.activeUsers)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The numbers behind the tool bars. */
function ToolTable({ tools }: { tools: Insights["tools"] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-left text-xs">
        <thead className="text-[11px] text-muted-foreground">
          <tr className="border-b">
            <th className="px-2 py-1.5 font-medium">Tool</th>
            <th className="px-2 py-1.5 text-right font-medium">Calls</th>
            <th className="px-2 py-1.5 text-right font-medium">Failed</th>
            <th className="px-2 py-1.5 text-right font-medium">Average time</th>
            <th className="w-40 px-2 py-1.5 font-medium">How often it failed</th>
          </tr>
        </thead>
        <tbody>
          {tools.map((x) => (
            <tr key={x.name} className="border-b last:border-b-0" data-testid="insights-tool-row">
              <td className="px-2 py-2 font-mono text-[11px]">{x.name}</td>
              <td className="px-2 py-2 text-right tabular-nums">{x.calls}</td>
              <td className="px-2 py-2 text-right tabular-nums">{x.errors}</td>
              <td className="px-2 py-2 text-right tabular-nums">{formatDuration(x.avgMs)}</td>
              <td className="px-2 py-2">
                <div className="flex items-center gap-2">
                  <Meter pct={x.failurePct ?? 0} bad={(x.failurePct ?? 0) > 20} label={`${x.name}: share of calls that failed`} />
                  <span className="w-9 text-right tabular-nums">{formatPct(x.failurePct)}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProblemRow({ p }: { p: Problem }) {
  const tone =
    p.reason === "thumbs_down" || p.reason === "handed_off" || p.reason === "slow" ? "border-amber-300 bg-amber-50 text-amber-900" : "border-red-200 bg-red-50 text-red-800";
  return (
    <li className="rounded-lg border bg-white px-3 py-2 text-xs shadow-sm" data-testid="insights-problem-row">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] text-muted-foreground">{ago(p.at)}</span>
        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${tone}`}>{REASON_LABEL[p.reason]}</span>
      </div>
      <p className="mt-1 break-words">{p.message ? `"${p.message}"` : "No text was recorded for this message."}</p>
      {p.detail && <p className="mt-0.5 break-words text-[11px] text-muted-foreground">{p.detail}</p>}
    </li>
  );
}

function Skeleton() {
  return (
    <div className="animate-pulse space-y-4" data-testid="insights-skeleton" aria-busy="true" aria-label="Loading insights">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="h-20 rounded-lg bg-slate-100" />
        ))}
      </div>
      <div className="h-44 rounded-lg bg-slate-100" />
      <div className="h-28 rounded-lg bg-slate-100" />
    </div>
  );
}
