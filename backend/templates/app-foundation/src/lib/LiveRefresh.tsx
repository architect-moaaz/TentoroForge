"use client";

/**
 * LiveRefresh — push-based data freshness for schema pages (R3 live UI).
 *
 * Subscribes to /api/events/stream (the SSE tail of the forge_events bus)
 * and calls router.refresh() — re-running the page's server component, so
 * SSR-resolved dataSources re-fetch — whenever an event lands for one of
 * the page's entities. Mounted by schema-page.tsx for every page that
 * declares dataSources; complements AutoRefresh (which stays the driver
 * for pages with an explicit `poll` spec — those keep their contract).
 *
 * Failure posture: silent. If the stream 404s (older app without the
 * route) or errors, the page simply behaves as before — fresh on navigation.
 *
 * A RECONNECT IS NOT A CHANGE. The platform caps the stream (60–300 s), and
 * this refreshed the page on every reconnect "to cover missed events": every
 * open tab re-read its whole page every few minutes doing nothing. Now each
 * frame carries the stream's watermark as its id; EventSource reconnects with
 * it and the stream replays what came after, so a refresh happens only for an
 * event this page watches.
 *
 * A HIDDEN TAB HOLDS NO STREAM. It closes when the tab is hidden — an open
 * stream polls the database every 2.5 s and keeps it awake — and reopens from
 * the last watermark when the tab is seen again; what landed meanwhile
 * arrives then, and refreshes the page once if it matters to it.
 */
import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

const DEBOUNCE_MS = 600;
const MIN_REFRESH_GAP_MS = 3000;
// Under a prefix (the platform's preview serves the app below one) the
// stream lives below it too; an absolute "/api/events/stream" reached the
// platform instead and answered HTML.
const STREAM_URL = `${(process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "")}/api/events/stream`;

/**
 * Whether the stream is ours to open. The route is gated like every data
 * route: opened signed out it answered the sign-in page, and EventSource
 * logged a MIME error on every public screen — which the trials counted
 * against every control on it (Ecom L1, 2026-10-11). One quiet probe,
 * then the stream, or nothing.
 */
async function streamIsOurs(): Promise<boolean> {
  const controller = new AbortController();
  try {
    const res = await fetch(STREAM_URL, { redirect: "manual", credentials: "same-origin", signal: controller.signal });
    const ok = res.status === 200 && (res.headers.get("content-type") || "").includes("text/event-stream");
    controller.abort();
    return ok;
  } catch {
    return false;
  }
}

interface StreamEvent {
  type: string;
  entity: string | null;
  entityId: string | null;
}

/** A record's name as its events spell it: lowercased, separators gone. */
function slugOf(name: unknown): string {
  return String(name ?? "").replace(/[^a-z0-9]/gi, "").toLowerCase();
}

export function LiveRefresh({ entities }: { entities: string[] }) {
  const router = useRouter();
  // Router identity changes across renders; keep the latest without
  // re-subscribing the EventSource.
  const routerRef = useRef(router);
  routerRef.current = router;
  // One spelling on both sides: a record event names its table with the
  // separators gone (`stage_events` → `stageevents`, events/triggers.ts), and
  // a page may say `stageEvents`, `stage_events` or `stage-events`.
  const watched = entities
    .map((e) => slugOf(e))
    .filter(Boolean)
    .sort()
    .join(",");

  // FILTER SEAM. FilterBar/SavedViewsPicker write the selection to the URL
  // with history.replaceState, which never re-runs this page's server
  // component — so the filter changed the address bar and nothing else.
  // The library emits `forge:urlstate`; refreshing here re-resolves the
  // dataSources with the new filter. Independent of the SSE subscription
  // below, so it works on pages with no live entities too.
  useEffect(() => {
    const onUrlState = () => routerRef.current.refresh();
    window.addEventListener("forge:urlstate", onUrlState);
    return () => window.removeEventListener("forge:urlstate", onUrlState);
  }, []);

  useEffect(() => {
    if (!watched) return;
    const slugs = new Set(watched.split(","));
    let es: EventSource | null = null;
    let debounce: ReturnType<typeof setTimeout> | null = null;
    let lastRefresh = 0;
    let stopped = false;
    let ours = false;
    // The stream's watermark, as its last frame named it.
    let lastId = "";
    // Reopened after being hidden with no watermark to carry on from (an
    // older stream that sends none): refresh once on the first frame.
    let catchUp = false;

    const refresh = () => {
      const now = Date.now();
      if (now - lastRefresh < MIN_REFRESH_GAP_MS) return;
      lastRefresh = now;
      routerRef.current.refresh();
    };

    const scheduleRefresh = () => {
      if (debounce) clearTimeout(debounce);
      debounce = setTimeout(refresh, DEBOUNCE_MS);
    };

    const matches = (evt: StreamEvent): boolean => {
      const entity = slugOf(evt.entity);
      if (entity && slugs.has(entity)) return true;
      // "<slug>.created" events carry the slug in the type prefix too.
      const prefix = slugOf(String(evt.type ?? "").split(".")[0]);
      return !!prefix && slugs.has(prefix);
    };

    const close = () => {
      es?.close();
      es = null;
    };

    const subscribe = () => {
      if (stopped || es || !ours || document.visibilityState === "hidden") return;
      try {
        es = new EventSource(lastId ? `${STREAM_URL}?since=${encodeURIComponent(lastId)}` : STREAM_URL);
      } catch {
        return; // ancient browser / route absent — degrade silently
      }
      es.onmessage = (msg) => {
        if (stopped) return;
        if (msg.lastEventId) lastId = msg.lastEventId;
        if (catchUp) {
          catchUp = false;
          scheduleRefresh();
          return;
        }
        try {
          const data = JSON.parse(msg.data) as { events?: StreamEvent[] };
          if ((data.events ?? []).some(matches)) scheduleRefresh();
        } catch {
          /* malformed frame — ignore */
        }
      };
    };

    const onVisibility = () => {
      if (document.visibilityState === "hidden") close();
      else {
        if (!es && !lastId) catchUp = true;
        subscribe();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    void streamIsOurs().then((yes) => {
      ours = yes;
      subscribe();
    });

    return () => {
      stopped = true;
      if (debounce) clearTimeout(debounce);
      document.removeEventListener("visibilitychange", onVisibility);
      close();
    };
  }, [watched]);

  return null;
}
