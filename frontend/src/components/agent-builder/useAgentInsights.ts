"use client";

/**
 * The numbers behind the Insights view: how an agent is doing, from one of two places.
 *
 * 1. A LIVE app: it pushes every turn to the platform, which keeps minute, hour and day totals. This is asked first, through the project
 *    route (`.../insights/summary`), and needs no Watch live connection.
 * 2. The DEVELOPMENT app connected in Watch live (the snapshot): asked only when the platform has no live numbers for this project and an
 *    app is connected. It only knows whole days.
 *
 * Only one of them is ever shown, and `source` says which. Asked again when the range, the agent or the app address change, every 30
 * seconds for the whole report, and every 5 seconds for the small "right now" strip (live source only), both only while the view is open
 * and the browser tab is showing. When a later ask fails, the last good numbers are kept and the reason is said above them, so a dropped
 * connection does not blank the screen.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { asInsights, devRange, rangeDays, type Freshness, type Insights, type LiveNow, type RangeChoice } from "@/lib/agent-insights";

export const REFRESH_MS = 30_000;
export const STRIP_REFRESH_MS = 5_000;
/** After this many failed strip asks in a row the strip stops claiming to be live. */
const STRIP_FAILS_BEFORE_STALE = 2;

export type InsightsSource = "live" | "dev";

interface Options {
  projectId: string;
  agentId: string;
  /** "tunnel", a localhost address, or "" when no development app is connected (it is then not asked). */
  appUrl: string;
  range: RangeChoice;
}

interface Answer {
  ok: boolean;
  reason?: string;
  insights?: unknown;
}

/** What the strip at the top shows: the last five minutes, and how old the newest event is. */
export interface Strip {
  live: LiveNow | null;
  freshness: Freshness | null;
  exact: boolean | undefined;
  /** True after several asks in a row failed: the numbers are the last ones we got, not current. */
  stale: boolean;
}

const summaryUrl = (projectId: string, range: RangeChoice, agentId: string) =>
  `/api/projects/${projectId}/agent-definitions/insights/summary?range=${range}&agent_id=${encodeURIComponent(agentId)}`;

const stripOf = (d: Insights): Strip => ({ live: d.live ?? null, freshness: d.freshness ?? null, exact: d.exact, stale: false });

export function useAgentInsights({ projectId, agentId, appUrl, range }: Options) {
  const [data, setData] = useState<Insights | null>(null);
  const [source, setSource] = useState<InsightsSource | null>(null);
  const [loading, setLoading] = useState(false);
  // True once the first ask for these choices has finished, so "nothing to show" is not said while it is still loading.
  const [settled, setSettled] = useState(false);
  // The platform itself could not be asked (offline, signed out, a server error): a sentence.
  const [error, setError] = useState<string | null>(null);
  // The platform answered, but the app behind it could not be reached or is not ready: a sentence.
  const [reason, setReason] = useState<string | null>(null);
  // The platform says it has no live numbers for this project (no key yet, or no events): a sentence, shown in the setup card.
  const [liveReason, setLiveReason] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [strip, setStrip] = useState<Strip | null>(null);
  // Only the newest ask may change the screen: an older one that comes back late is dropped.
  const latest = useRef(0);
  const stripBusy = useRef(false);
  const stripFails = useRef(0);
  // A live summary already worked for this project: a later "no data" is then about THIS range, not about the project, so it is not
  // answered by showing the development app instead.
  const liveSeenFor = useRef<string | null>(null);
  const sourceRef = useRef<InsightsSource | null>(null);
  sourceRef.current = source;
  const key = `${projectId}|${agentId}|${appUrl}|${range}`;
  const shownDevRange = devRange(range);

  const load = useCallback(async () => {
    const mine = ++latest.current;
    setLoading(true);
    const dev = async (): Promise<void> => {
      const query = `days=${rangeDays(shownDevRange)}&agent_id=${encodeURIComponent(agentId)}&app_url=${encodeURIComponent(appUrl)}`;
      const res = await api.get<Answer>(`/api/projects/${projectId}/agent-definitions/insights?${query}`);
      if (mine !== latest.current) return;
      if (res?.ok) {
        const parsed = asInsights(res.insights);
        if (parsed) {
          setData(parsed);
          setSource("dev");
          setStrip(null);
          setError(null);
          setReason(null);
          setUpdatedAt(Date.now());
        } else {
          setError("The app answered in a way this screen does not understand. Apply the agent again, then press Refresh.");
        }
      } else {
        setReason(res?.reason || "The app could not be reached.");
        setError(null);
      }
    };
    try {
      let answer: Answer | null = null;
      let platformError: unknown = null;
      try {
        answer = await api.get<Answer>(summaryUrl(projectId, range, agentId));
      } catch (e) {
        // An older platform has no such route, or it could not be reached: the development app may still be askable.
        platformError = e;
      }
      if (mine !== latest.current) return;
      if (answer?.ok) {
        const parsed = asInsights(answer.insights);
        if (parsed) {
          liveSeenFor.current = projectId;
          setData(parsed);
          setSource("live");
          setStrip(stripOf(parsed));
          stripFails.current = 0;
          setError(null);
          setReason(null);
          setLiveReason(null);
          setUpdatedAt(Date.now());
        } else {
          setError("The platform answered in a way this screen does not understand. Try Refresh.");
        }
        return;
      }
      const why = answer && !answer.ok ? (typeof answer.reason === "string" && answer.reason ? answer.reason.slice(0, 300) : "No live app has sent chats yet.") : null;
      if (why) setLiveReason(why);
      if (appUrl && liveSeenFor.current !== projectId) {
        await dev();
        return;
      }
      if (why) {
        // Nothing live to show: the setup card says why. A live app that has simply been quiet in this range gets the sentence above its (empty) report.
        setReason(liveSeenFor.current === projectId ? why : null);
        setError(null);
      } else {
        setError(platformError instanceof Error && platformError.message ? platformError.message : "The platform could not be asked for insights. Try Refresh.");
      }
    } catch (e) {
      if (mine !== latest.current) return;
      setError(e instanceof Error && e.message ? e.message : "The platform could not be asked for insights. Try Refresh.");
    } finally {
      if (mine === latest.current) {
        setLoading(false);
        setSettled(true);
      }
    }
  }, [projectId, agentId, appUrl, range, shownDevRange]);

  const loadRef = useRef(load);
  loadRef.current = load;

  // The little strip: the last five minutes of a live app, asked on its own (and sooner) than the whole report. The route is the same, for
  // the last hour, and only its "right now" part and its freshness are read.
  const loadStrip = useCallback(async () => {
    if (stripBusy.current) return;
    stripBusy.current = true;
    const gen = latest.current;
    try {
      const res = await api.get<Answer>(summaryUrl(projectId, "1h", agentId));
      if (gen !== latest.current) return;
      const parsed = res?.ok ? asInsights(res.insights) : null;
      if (parsed) {
        stripFails.current = 0;
        setStrip(stripOf(parsed));
      } else if (++stripFails.current >= STRIP_FAILS_BEFORE_STALE) {
        setStrip((s) => (s ? { ...s, stale: true } : s));
      }
    } catch {
      if (gen !== latest.current) return;
      if (++stripFails.current >= STRIP_FAILS_BEFORE_STALE) setStrip((s) => (s ? { ...s, stale: true } : s));
    } finally {
      stripBusy.current = false;
    }
  }, [projectId, agentId]);

  const loadStripRef = useRef(loadStrip);
  loadStripRef.current = loadStrip;

  // A different agent, app or range is a different set of numbers: the old ones are not shown under the new title.
  useEffect(() => {
    latest.current++;
    stripBusy.current = false;
    stripFails.current = 0;
    setData(null);
    setSource(null);
    setStrip(null);
    setError(null);
    setReason(null);
    setLiveReason(null);
    setUpdatedAt(null);
    setLoading(false);
    setSettled(false);
    void loadRef.current();
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fresh numbers while it is open and visible.
  useEffect(() => {
    const visible = () => typeof document === "undefined" || document.visibilityState !== "hidden";
    const whole = setInterval(() => {
      if (visible()) void loadRef.current();
    }, REFRESH_MS);
    const onShow = () => {
      if (!visible()) return;
      void loadRef.current();
      if (sourceRef.current === "live") void loadStripRef.current();
    };
    document.addEventListener("visibilitychange", onShow);
    return () => {
      clearInterval(whole);
      document.removeEventListener("visibilitychange", onShow);
    };
  }, [key]);

  // The strip is only asked for a live app.
  useEffect(() => {
    if (source !== "live") return;
    const visible = () => typeof document === "undefined" || document.visibilityState !== "hidden";
    const timer = setInterval(() => {
      if (visible()) void loadStripRef.current();
    }, STRIP_REFRESH_MS);
    return () => clearInterval(timer);
  }, [key, source]);

  const refresh = useCallback(() => load(), [load]);

  return { data, source, loading, settled, error, reason, liveReason, updatedAt, strip, refresh, devRange: shownDevRange };
}
